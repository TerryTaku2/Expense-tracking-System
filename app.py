import csv
import io
import json
import os
import secrets
from datetime import date, timedelta

from flask import (Flask, Response, jsonify, redirect, render_template,
                    request, send_from_directory, url_for)
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                          login_user, logout_user)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

import database

app = Flask(__name__)
application = app  # some WSGI hosts (e.g. PythonAnywhere) look for this name

ALLOWED_RECEIPT_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "pdf"}
_DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_hex(16))
MAX_RECEIPT_BYTES = 8 * 1024 * 1024

# Runs on import so the tables exist under a real WSGI server too, not just
# when this file is executed directly with `python app.py`.
database.init_db()


def _get_or_create_secret_key():
    """Prefer an explicit SECRET_KEY env var in production. Falling back to
    one generated on first boot and persisted to the data disk means
    sessions survive restarts even if the env var was never set, instead of
    logging every user out on every deploy."""
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    key_file = database.DATA_DIR / ".secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    database.DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    key_file.write_text(key)
    return key


app.secret_key = _get_or_create_secret_key()
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
# Rejects oversized request bodies before Flask reads them into memory at
# all (receipts cap at 8MB app-side; this just adds headroom + a hard
# backstop for backup/restore uploads).
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024

login_manager = LoginManager()
login_manager.init_app(app)


class User(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.email = row["email"]
        self.business_name = row["business_name"]

    def get_id(self):
        return str(self.id)


@login_manager.user_loader
def load_user(user_id):
    row = database.get_user_by_id(int(user_id))
    return User(row) if row else None


@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith("/api/") or request.path.startswith("/receipts/"):
        return jsonify({"error": "authentication required"}), 401
    return redirect(url_for("login_page", next=request.path))


@app.before_request
def block_cross_origin_writes():
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
            return jsonify({"error": "cross-origin request blocked"}), 403


@app.teardown_appcontext
def close_db(_exc):
    database.close_connection()


@app.route("/service-worker.js")
def service_worker():
    response = send_from_directory(app.static_folder, "service-worker.js")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


# ---------- Auth ----------

@app.route("/signup", methods=["GET", "POST"])
def signup_page():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "GET":
        return render_template("signup.html")

    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    business_name = (data.get("business_name") or "").strip()

    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return jsonify({"error": "enter a valid email address"}), 400
    if len(password) < 8:
        return jsonify({"error": "password must be at least 8 characters"}), 400
    if database.get_user_by_email(email):
        return jsonify({"error": "an account with that email already exists"}), 400

    user_id = database.create_user(email, password, business_name)
    login_user(User(database.get_user_by_id(user_id)), remember=True)
    return jsonify({"status": "ok"})


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "GET":
        return render_template("login.html")

    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    row = database.get_user_by_email(email)
    # Hash against a dummy value even when the user doesn't exist, so a
    # "no such account" response doesn't return measurably faster than a
    # "wrong password" one and let an attacker enumerate registered emails.
    password_hash = row["password_hash"] if row else _DUMMY_PASSWORD_HASH
    password_ok = check_password_hash(password_hash, password)
    if row is None or not password_ok:
        return jsonify({"error": "incorrect email or password"}), 401

    login_user(User(row), remember=True)
    return jsonify({"status": "ok"})


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return jsonify({"status": "ok"})


# ---------- Pages ----------

@app.route("/")
@login_required
def index():
    return render_template("index.html", active_page="today")


@app.route("/history")
@login_required
def history_page():
    return render_template("history.html", active_page="history")


@app.route("/transactions")
@login_required
def transactions_page():
    return render_template("transactions.html", active_page="transactions")


@app.route("/budgets")
@login_required
def budgets_page():
    return render_template("budgets.html", active_page="budgets")


@app.route("/insights")
@login_required
def insights_page():
    return render_template("insights.html", active_page="insights")


# ---------- API: categories ----------

@app.route("/api/categories")
@login_required
def get_categories():
    return jsonify(database.get_used_categories(current_user.id))


# ---------- API: day ----------

def _day_response(day_date):
    day = database.get_day(current_user.id, day_date)
    if day is None:
        return jsonify({"date": day_date, "starting_balance": None, "expenses": [], "income": [],
                         "total_spent": 0, "total_income": 0, "balance": None,
                         "previous_day": database.get_previous_day(current_user.id, day_date)})

    database.apply_due_recurring(current_user.id, day_date)
    expenses = database.get_expenses(day["id"])
    income = database.get_income(day["id"])
    total_spent = sum(e["amount"] for e in expenses)
    total_income = sum(i["amount"] for i in income)
    return jsonify({
        "date": day["date"],
        "starting_balance": day["starting_balance"],
        "expenses": expenses,
        "income": income,
        "total_spent": total_spent,
        "total_income": total_income,
        "balance": day["starting_balance"] + total_income - total_spent,
    })


@app.route("/api/day/<day_date>")
@login_required
def get_day(day_date):
    return _day_response(day_date)


@app.route("/api/day", methods=["POST"])
@login_required
def set_day():
    data = request.get_json(force=True)
    day_date = data.get("date")
    starting_balance = data.get("starting_balance")

    if not day_date or starting_balance is None:
        return jsonify({"error": "date and starting_balance are required"}), 400
    try:
        starting_balance = float(starting_balance)
    except (TypeError, ValueError):
        return jsonify({"error": "starting_balance must be a number"}), 400

    database.upsert_day(current_user.id, day_date, starting_balance)
    return _day_response(day_date)


# ---------- API: expenses ----------

@app.route("/api/expenses", methods=["POST"])
@login_required
def add_expense():
    data = request.get_json(force=True)
    day_date = data.get("date")
    description = (data.get("description") or "").strip()
    category = (data.get("category") or "").strip() or "Other"
    amount = data.get("amount")

    if not day_date:
        return jsonify({"error": "date is required"}), 400
    if not description:
        description = category
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400
    if amount <= 0:
        return jsonify({"error": "amount must be greater than zero"}), 400
    category = category[:40]

    day = database.get_day(current_user.id, day_date)
    if day is None:
        return jsonify({"error": "set a starting balance for this day first"}), 400

    new_id = database.add_expense(day["id"], description, category, amount)
    response = _day_response(day_date)
    payload = response.get_json()
    payload["new_expense_id"] = new_id
    return jsonify(payload)


@app.route("/api/expenses/<int:expense_id>", methods=["PUT"])
@login_required
def edit_expense(expense_id):
    existing = database.get_expense(current_user.id, expense_id)
    if existing is None:
        return jsonify({"error": "expense not found"}), 404

    data = request.get_json(force=True)
    description = (data.get("description") or "").strip()
    category = (data.get("category") or "").strip() or "Other"
    amount = data.get("amount")

    if not description:
        description = category
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400
    if amount <= 0:
        return jsonify({"error": "amount must be greater than zero"}), 400
    category = category[:40]

    database.update_expense(current_user.id, expense_id, description, category, amount)
    return _day_response(existing["date"])


@app.route("/api/expenses/<int:expense_id>", methods=["DELETE"])
@login_required
def delete_expense(expense_id):
    day_date = database.delete_expense(current_user.id, expense_id)
    if day_date is None:
        return jsonify({"error": "expense not found"}), 404
    response = _day_response(day_date)
    payload = response.get_json()
    payload["deleted_expense_id"] = expense_id
    return jsonify(payload)


@app.route("/api/expenses/<int:expense_id>/restore", methods=["POST"])
@login_required
def restore_expense(expense_id):
    day_date = database.restore_expense(current_user.id, expense_id)
    if day_date is None:
        return jsonify({"error": "expense not found or not deleted"}), 404
    return _day_response(day_date)


@app.route("/api/expenses/<int:expense_id>/receipt", methods=["POST"])
@login_required
def upload_receipt(expense_id):
    existing = database.get_expense(current_user.id, expense_id)
    if existing is None:
        return jsonify({"error": "expense not found"}), 404

    file = request.files.get("receipt")
    if file is None or file.filename == "":
        return jsonify({"error": "no file uploaded"}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_RECEIPT_EXTENSIONS:
        return jsonify({"error": "unsupported file type"}), 400

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_RECEIPT_BYTES:
        return jsonify({"error": "file is too large (max 8MB)"}), 400

    filename = secure_filename(f"{expense_id}_{file.filename}")
    file.save(database.RECEIPTS_DIR / filename)
    database.set_expense_receipt(current_user.id, expense_id, filename)
    return _day_response(existing["date"])


@app.route("/receipts/<int:expense_id>/<path:filename>")
@login_required
def get_receipt(expense_id, filename):
    expense = database.get_expense(current_user.id, expense_id)
    if expense is None or expense["receipt_filename"] != filename:
        return jsonify({"error": "not found"}), 404
    return send_from_directory(database.RECEIPTS_DIR, filename)


# ---------- API: income ----------

@app.route("/api/income", methods=["POST"])
@login_required
def add_income():
    data = request.get_json(force=True)
    day_date = data.get("date")
    description = (data.get("description") or "").strip() or "Income"
    amount = data.get("amount")

    if not day_date:
        return jsonify({"error": "date is required"}), 400
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400
    if amount <= 0:
        return jsonify({"error": "amount must be greater than zero"}), 400

    day = database.get_day(current_user.id, day_date)
    if day is None:
        return jsonify({"error": "set a starting balance for this day first"}), 400

    database.add_income(day["id"], description, amount)
    return _day_response(day_date)


@app.route("/api/income/<int:income_id>", methods=["DELETE"])
@login_required
def delete_income(income_id):
    day_date = database.delete_income(current_user.id, income_id)
    if day_date is None:
        return jsonify({"error": "income entry not found"}), 404
    return _day_response(day_date)


# ---------- API: history / transactions ----------

@app.route("/api/history")
@login_required
def get_history():
    return jsonify(database.get_history(current_user.id))


@app.route("/api/transactions")
@login_required
def get_transactions():
    q = request.args.get("q") or None
    category = request.args.get("category") or None
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    min_amount = request.args.get("min_amount")
    max_amount = request.args.get("max_amount")

    try:
        min_amount = float(min_amount) if min_amount else None
        max_amount = float(max_amount) if max_amount else None
    except ValueError:
        return jsonify({"error": "min_amount/max_amount must be numbers"}), 400

    return jsonify(database.get_all_expenses(
        current_user.id, q=q, category=category, date_from=date_from, date_to=date_to,
        min_amount=min_amount, max_amount=max_amount,
    ))


@app.route("/api/export/csv")
@login_required
def export_csv():
    rows = database.get_all_expenses(current_user.id)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Date", "Category", "Description", "Amount"])
    for r in rows:
        writer.writerow([r["date"], r["category"], r["description"], r["amount"]])

    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=expenses.csv"},
    )


# ---------- API: budgets ----------

@app.route("/api/budgets")
@login_required
def get_budgets():
    return jsonify(database.get_budget_progress(current_user.id))


@app.route("/api/budgets", methods=["POST"])
@login_required
def set_budget():
    data = request.get_json(force=True)
    category = (data.get("category") or "").strip()
    amount = data.get("amount")
    period = data.get("period")

    if not category:
        return jsonify({"error": "category is required"}), 400
    if period not in ("weekly", "monthly"):
        return jsonify({"error": "period must be 'weekly' or 'monthly'"}), 400
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400
    if amount <= 0:
        return jsonify({"error": "amount must be greater than zero"}), 400

    database.upsert_budget(current_user.id, category[:40], amount, period)
    return jsonify(database.get_budget_progress(current_user.id))


@app.route("/api/budgets/<category>", methods=["DELETE"])
@login_required
def remove_budget(category):
    database.delete_budget(current_user.id, category)
    return jsonify(database.get_budget_progress(current_user.id))


# ---------- API: recurring ----------

@app.route("/api/recurring")
@login_required
def get_recurring():
    return jsonify(database.get_recurring(current_user.id))


@app.route("/api/recurring", methods=["POST"])
@login_required
def add_recurring():
    data = request.get_json(force=True)
    description = (data.get("description") or "").strip()
    category = (data.get("category") or "").strip() or "Other"
    amount = data.get("amount")
    frequency = data.get("frequency")
    start_date = data.get("start_date") or date.today().isoformat()

    if not description:
        return jsonify({"error": "description is required"}), 400
    if frequency not in ("daily", "weekly", "monthly"):
        return jsonify({"error": "frequency must be daily, weekly, or monthly"}), 400
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400
    if amount <= 0:
        return jsonify({"error": "amount must be greater than zero"}), 400

    database.add_recurring(current_user.id, description, category[:40], amount, frequency, start_date)
    return jsonify(database.get_recurring(current_user.id))


@app.route("/api/recurring/<int:recurring_id>", methods=["PUT"])
@login_required
def toggle_recurring(recurring_id):
    data = request.get_json(force=True)
    database.set_recurring_active(current_user.id, recurring_id, bool(data.get("active", True)))
    return jsonify(database.get_recurring(current_user.id))


@app.route("/api/recurring/<int:recurring_id>", methods=["DELETE"])
@login_required
def remove_recurring(recurring_id):
    database.delete_recurring(current_user.id, recurring_id)
    return jsonify(database.get_recurring(current_user.id))


# ---------- API: insights ----------

@app.route("/api/trends")
@login_required
def get_trends():
    days = request.args.get("days", 30, type=int)
    return jsonify(database.get_trends(current_user.id, days=min(max(days, 1), 365)))


@app.route("/api/summary")
@login_required
def get_summary():
    period = request.args.get("period", "week")
    today = date.today()
    if period == "month":
        start = today.replace(day=1)
        prev_end = start - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
    else:
        start = today - timedelta(days=today.weekday())
        prev_end = start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=6)

    return jsonify(database.get_summary(
        current_user.id, start.isoformat(), today.isoformat(), prev_start.isoformat(), prev_end.isoformat()
    ))


# ---------- API: backup / restore ----------

@app.route("/api/backup")
@login_required
def backup():
    payload = database.export_backup(current_user.id)
    return Response(
        json.dumps(payload, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=expense-tracker-backup.json"},
    )


@app.route("/api/restore", methods=["POST"])
@login_required
def restore():
    file = request.files.get("backup")
    if file is None:
        return jsonify({"error": "no backup file uploaded"}), 400
    try:
        data = json.load(file.stream)
    except (ValueError, UnicodeDecodeError):
        return jsonify({"error": "invalid backup file"}), 400

    required_keys = {"days", "expenses", "income", "budgets", "recurring"}
    if not isinstance(data, dict) or not required_keys.issubset(data.keys()):
        return jsonify({"error": "backup file is missing expected data"}), 400
    if not all(isinstance(data[key], list) for key in required_keys):
        return jsonify({"error": "backup file is malformed"}), 400

    try:
        database.import_backup(current_user.id, data)
    except (KeyError, TypeError, database.sqlite3.DatabaseError):
        # Any partial writes made before the error roll back automatically
        # (nothing is committed until import_backup finishes), so the
        # user's existing data is safe even though the restore failed.
        return jsonify({"error": "backup file is malformed"}), 400
    return jsonify({"status": "restored"})


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=debug)
