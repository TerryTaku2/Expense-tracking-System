import os

from flask import Flask, jsonify, render_template, request, send_from_directory

import database

app = Flask(__name__)
application = app  # some WSGI hosts (e.g. PythonAnywhere) look for this name

# Runs on import so the tables exist under a real WSGI server too, not just
# when this file is executed directly with `python app.py`.
database.init_db()


@app.teardown_appcontext
def close_db(_exc):
    database.close_connection()


@app.route("/service-worker.js")
def service_worker():
    response = send_from_directory(app.static_folder, "service-worker.js")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


# ---------- Pages ----------

@app.route("/")
def index():
    return render_template("index.html", active_page="today")


@app.route("/history")
def history_page():
    return render_template("history.html", active_page="history")


@app.route("/transactions")
def transactions_page():
    return render_template("transactions.html", active_page="transactions")


# ---------- API: categories ----------

@app.route("/api/categories")
def get_categories():
    return jsonify(database.get_used_categories())


# ---------- API: day ----------

@app.route("/api/day/<day_date>")
def get_day(day_date):
    day = database.get_day(day_date)
    if day is None:
        return jsonify({"date": day_date, "starting_balance": None, "expenses": [],
                         "total_spent": 0, "balance": None,
                         "previous_day": database.get_previous_day(day_date)})

    expenses = database.get_expenses(day["id"])
    total_spent = sum(e["amount"] for e in expenses)
    return jsonify({
        "date": day["date"],
        "starting_balance": day["starting_balance"],
        "expenses": expenses,
        "total_spent": total_spent,
        "balance": day["starting_balance"] - total_spent,
    })


@app.route("/api/day", methods=["POST"])
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

    database.upsert_day(day_date, starting_balance)
    return get_day(day_date)


# ---------- API: expenses ----------

@app.route("/api/expenses", methods=["POST"])
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

    day = database.get_day(day_date)
    if day is None:
        return jsonify({"error": "set a starting balance for this day first"}), 400

    database.add_expense(day["id"], description, category, amount)
    return get_day(day_date)


@app.route("/api/expenses/<int:expense_id>", methods=["DELETE"])
def delete_expense(expense_id):
    day_date = database.delete_expense(expense_id)
    if day_date is None:
        return jsonify({"error": "expense not found"}), 404
    return get_day(day_date)


# ---------- API: history ----------

@app.route("/api/history")
def get_history():
    return jsonify(database.get_history())


@app.route("/api/transactions")
def get_transactions():
    return jsonify(database.get_all_expenses())


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=debug)
