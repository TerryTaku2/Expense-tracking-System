import calendar
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from flask import g

# On Render, DATA_DIR points at the mounted persistent disk so the database
# survives restarts/redeploys; locally it just falls back to this folder.
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent))
DB_PATH = DATA_DIR / "expense_tracker.db"
RECEIPTS_DIR = DATA_DIR / "receipts"

DEFAULT_CATEGORIES = ["Stock", "Staff", "Rent", "Utilities", "Transport", "Supplies", "Marketing", "Bills", "Other"]


def get_connection():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_connection():
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _ensure_column(conn, table, column, ddl):
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            starting_balance REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_id INTEGER NOT NULL REFERENCES days(id),
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
        """
    )
    _ensure_column(conn, "expenses", "receipt_filename", "receipt_filename TEXT")
    _ensure_column(conn, "expenses", "deleted_at", "deleted_at TEXT")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS income (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day_id INTEGER NOT NULL REFERENCES days(id),
            description TEXT NOT NULL,
            amount REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT UNIQUE NOT NULL,
            amount REAL NOT NULL,
            period TEXT NOT NULL CHECK(period IN ('weekly', 'monthly'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recurring (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            frequency TEXT NOT NULL CHECK(frequency IN ('daily', 'weekly', 'monthly')),
            next_date TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    conn.commit()
    conn.close()


# ---------- Days ----------

def get_day(day_date):
    row = get_connection().execute(
        "SELECT * FROM days WHERE date = ?", (day_date,)
    ).fetchone()
    return dict(row) if row else None


def upsert_day(day_date, starting_balance):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO days (date, starting_balance) VALUES (?, ?)
        ON CONFLICT(date) DO UPDATE SET starting_balance = excluded.starting_balance
        """,
        (day_date, starting_balance),
    )
    conn.commit()


def get_previous_day(before_date):
    row = get_connection().execute(
        """
        SELECT d.id AS id, d.date AS date, d.starting_balance AS starting_balance,
               COALESCE(SUM(e.amount), 0) AS total_spent,
               COALESCE((SELECT SUM(amount) FROM income WHERE day_id = d.id), 0) AS total_income
        FROM days d
        LEFT JOIN expenses e ON e.day_id = d.id AND e.deleted_at IS NULL
        WHERE d.date < ?
        GROUP BY d.id
        ORDER BY d.date DESC
        LIMIT 1
        """,
        (before_date,),
    ).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["balance"] = item["starting_balance"] + item["total_income"] - item["total_spent"]
    return item


# ---------- Expenses ----------

def get_expenses(day_id):
    rows = get_connection().execute(
        "SELECT * FROM expenses WHERE day_id = ? AND deleted_at IS NULL ORDER BY created_at DESC, id DESC",
        (day_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_expense(day_id, description, category, amount):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO expenses (day_id, description, category, amount) VALUES (?, ?, ?, ?)",
        (day_id, description, category, amount),
    )
    conn.commit()
    return cur.lastrowid


def get_expense(expense_id):
    row = get_connection().execute(
        "SELECT e.*, d.date AS date FROM expenses e JOIN days d ON d.id = e.day_id WHERE e.id = ?",
        (expense_id,),
    ).fetchone()
    return dict(row) if row else None


def update_expense(expense_id, description, category, amount):
    conn = get_connection()
    conn.execute(
        "UPDATE expenses SET description = ?, category = ?, amount = ? WHERE id = ?",
        (description, category, amount, expense_id),
    )
    conn.commit()


def set_expense_receipt(expense_id, filename):
    conn = get_connection()
    conn.execute("UPDATE expenses SET receipt_filename = ? WHERE id = ?", (filename, expense_id))
    conn.commit()


def delete_expense(expense_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT d.date AS date FROM expenses e JOIN days d ON d.id = e.day_id WHERE e.id = ? AND e.deleted_at IS NULL",
        (expense_id,),
    ).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE expenses SET deleted_at = datetime('now', 'localtime') WHERE id = ?", (expense_id,))
    conn.commit()
    return row["date"]


def restore_expense(expense_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT d.date AS date FROM expenses e JOIN days d ON d.id = e.day_id WHERE e.id = ? AND e.deleted_at IS NOT NULL",
        (expense_id,),
    ).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE expenses SET deleted_at = NULL WHERE id = ?", (expense_id,))
    conn.commit()
    return row["date"]


def get_used_categories():
    rows = get_connection().execute(
        "SELECT DISTINCT category FROM expenses ORDER BY category COLLATE NOCASE"
    ).fetchall()
    used = [r["category"] for r in rows]
    merged = list(DEFAULT_CATEGORIES)
    for c in used:
        if c not in merged:
            merged.append(c)
    return merged


def get_all_expenses(q=None, category=None, date_from=None, date_to=None,
                      min_amount=None, max_amount=None):
    sql = """
        SELECT e.id AS id, d.date AS date, e.category AS category,
               e.description AS description, e.amount AS amount, e.created_at AS created_at,
               e.receipt_filename AS receipt_filename
        FROM expenses e
        JOIN days d ON d.id = e.day_id
        WHERE e.deleted_at IS NULL
    """
    params = []
    if q:
        sql += " AND (e.description LIKE ? OR e.category LIKE ?)"
        like = f"%{q}%"
        params += [like, like]
    if category:
        sql += " AND e.category = ?"
        params.append(category)
    if date_from:
        sql += " AND d.date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND d.date <= ?"
        params.append(date_to)
    if min_amount is not None:
        sql += " AND e.amount >= ?"
        params.append(min_amount)
    if max_amount is not None:
        sql += " AND e.amount <= ?"
        params.append(max_amount)
    sql += " ORDER BY d.date DESC, e.created_at DESC, e.id DESC"

    rows = get_connection().execute(sql, params).fetchall()
    return [dict(r) for r in rows]


# ---------- Income ----------

def get_income(day_id):
    rows = get_connection().execute(
        "SELECT * FROM income WHERE day_id = ? ORDER BY created_at DESC, id DESC",
        (day_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_income(day_id, description, amount):
    conn = get_connection()
    conn.execute(
        "INSERT INTO income (day_id, description, amount) VALUES (?, ?, ?)",
        (day_id, description, amount),
    )
    conn.commit()


def delete_income(income_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT d.date AS date FROM income i JOIN days d ON d.id = i.day_id WHERE i.id = ?",
        (income_id,),
    ).fetchone()
    if row is None:
        return None
    conn.execute("DELETE FROM income WHERE id = ?", (income_id,))
    conn.commit()
    return row["date"]


def get_used_categories_with(extra_table_amounts=True):
    return get_used_categories()


# ---------- History ----------

def get_history():
    rows = get_connection().execute(
        """
        SELECT
            d.date AS date,
            d.starting_balance AS starting_balance,
            COALESCE((SELECT SUM(amount) FROM expenses WHERE day_id = d.id AND deleted_at IS NULL), 0) AS total_spent,
            COALESCE((SELECT SUM(amount) FROM income WHERE day_id = d.id), 0) AS total_income,
            (SELECT COUNT(*) FROM expenses WHERE day_id = d.id AND deleted_at IS NULL) AS expense_count
        FROM days d
        ORDER BY d.date DESC
        """
    ).fetchall()
    history = []
    for row in rows:
        item = dict(row)
        item["balance"] = item["starting_balance"] + item["total_income"] - item["total_spent"]
        history.append(item)
    return history


def get_trends(days=30):
    rows = get_connection().execute(
        """
        SELECT
            d.date AS date,
            d.starting_balance AS starting_balance,
            COALESCE((SELECT SUM(amount) FROM expenses WHERE day_id = d.id AND deleted_at IS NULL), 0) AS total_spent,
            COALESCE((SELECT SUM(amount) FROM income WHERE day_id = d.id), 0) AS total_income
        FROM days d
        ORDER BY d.date DESC
        LIMIT ?
        """,
        (days,),
    ).fetchall()
    trends = [dict(r) for r in rows]
    trends.reverse()
    return trends


def get_summary(period_start, period_end, prev_start, prev_end):
    def totals(start, end):
        row = get_connection().execute(
            """
            SELECT
                COALESCE((SELECT SUM(e.amount) FROM expenses e JOIN days d ON d.id = e.day_id
                          WHERE e.deleted_at IS NULL AND d.date >= ? AND d.date <= ?), 0) AS total_spent,
                COALESCE((SELECT SUM(i.amount) FROM income i JOIN days d ON d.id = i.day_id
                          WHERE d.date >= ? AND d.date <= ?), 0) AS total_income,
                (SELECT COUNT(DISTINCT d.id) FROM days d WHERE d.date >= ? AND d.date <= ?) AS days_tracked
            """,
            (start, end, start, end, start, end),
        ).fetchone()
        return dict(row)

    current = totals(period_start, period_end)
    previous = totals(prev_start, prev_end)

    top_row = get_connection().execute(
        """
        SELECT e.category AS category, SUM(e.amount) AS total
        FROM expenses e JOIN days d ON d.id = e.day_id
        WHERE e.deleted_at IS NULL AND d.date >= ? AND d.date <= ?
        GROUP BY e.category
        ORDER BY total DESC
        LIMIT 1
        """,
        (period_start, period_end),
    ).fetchone()

    return {
        "total_spent": current["total_spent"],
        "total_income": current["total_income"],
        "days_tracked": current["days_tracked"],
        "avg_daily_spent": (current["total_spent"] / current["days_tracked"]) if current["days_tracked"] else 0,
        "top_category": top_row["category"] if top_row else None,
        "top_category_amount": top_row["total"] if top_row else 0,
        "previous_total_spent": previous["total_spent"],
    }


# ---------- Budgets ----------

def get_budgets():
    rows = get_connection().execute("SELECT * FROM budgets ORDER BY category COLLATE NOCASE").fetchall()
    return [dict(r) for r in rows]


def upsert_budget(category, amount, period):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO budgets (category, amount, period) VALUES (?, ?, ?)
        ON CONFLICT(category) DO UPDATE SET amount = excluded.amount, period = excluded.period
        """,
        (category, amount, period),
    )
    conn.commit()


def delete_budget(category):
    conn = get_connection()
    conn.execute("DELETE FROM budgets WHERE category = ?", (category,))
    conn.commit()


def get_budget_progress():
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    progress = []
    for b in get_budgets():
        start = week_start if b["period"] == "weekly" else month_start
        row = get_connection().execute(
            """
            SELECT COALESCE(SUM(e.amount), 0) AS spent
            FROM expenses e JOIN days d ON d.id = e.day_id
            WHERE e.deleted_at IS NULL AND e.category = ? AND d.date >= ? AND d.date <= ?
            """,
            (b["category"], start.isoformat(), today.isoformat()),
        ).fetchone()
        spent = row["spent"]
        progress.append({
            "category": b["category"],
            "amount": b["amount"],
            "period": b["period"],
            "spent": spent,
            "remaining": b["amount"] - spent,
            "pct": min(100, (spent / b["amount"] * 100) if b["amount"] > 0 else 0),
            "period_start": start.isoformat(),
        })
    return progress


# ---------- Recurring ----------

def get_recurring():
    rows = get_connection().execute("SELECT * FROM recurring ORDER BY next_date").fetchall()
    return [dict(r) for r in rows]


def add_recurring(description, category, amount, frequency, start_date):
    conn = get_connection()
    conn.execute(
        "INSERT INTO recurring (description, category, amount, frequency, next_date) VALUES (?, ?, ?, ?, ?)",
        (description, category, amount, frequency, start_date),
    )
    conn.commit()


def set_recurring_active(recurring_id, active):
    conn = get_connection()
    conn.execute("UPDATE recurring SET active = ? WHERE id = ?", (1 if active else 0, recurring_id))
    conn.commit()


def delete_recurring(recurring_id):
    conn = get_connection()
    conn.execute("DELETE FROM recurring WHERE id = ?", (recurring_id,))
    conn.commit()


def _advance_date(iso_date, frequency):
    d = date.fromisoformat(iso_date)
    if frequency == "daily":
        d += timedelta(days=1)
    elif frequency == "weekly":
        d += timedelta(weeks=1)
    else:  # monthly
        month = d.month + 1
        year = d.year
        if month > 12:
            month = 1
            year += 1
        day_num = min(d.day, calendar.monthrange(year, month)[1])
        d = date(year, month, day_num)
    return d.isoformat()


def apply_due_recurring(target_date):
    """Applies any recurring items due on/before target_date into that day,
    catching up on missed occurrences one at a time. Only runs if the day
    already exists (has a starting balance), since there's nowhere to file
    the expense otherwise."""
    day = get_day(target_date)
    if day is None:
        return []

    conn = get_connection()
    applied = []
    for _ in range(60):  # safety cap against runaway catch-up loops
        due = conn.execute(
            "SELECT * FROM recurring WHERE active = 1 AND next_date <= ? ORDER BY next_date LIMIT 1",
            (target_date,),
        ).fetchone()
        if due is None:
            break
        add_expense(day["id"], due["description"], due["category"], due["amount"])
        next_date = _advance_date(due["next_date"], due["frequency"])
        conn.execute("UPDATE recurring SET next_date = ? WHERE id = ?", (next_date, due["id"]))
        conn.commit()
        applied.append(due["description"])
    return applied


# ---------- Backup / restore ----------

def export_backup():
    conn = get_connection()
    return {
        "days": [dict(r) for r in conn.execute("SELECT * FROM days").fetchall()],
        "expenses": [dict(r) for r in conn.execute("SELECT * FROM expenses").fetchall()],
        "income": [dict(r) for r in conn.execute("SELECT * FROM income").fetchall()],
        "budgets": [dict(r) for r in conn.execute("SELECT * FROM budgets").fetchall()],
        "recurring": [dict(r) for r in conn.execute("SELECT * FROM recurring").fetchall()],
    }


def import_backup(data):
    conn = get_connection()
    conn.execute("DELETE FROM income")
    conn.execute("DELETE FROM expenses")
    conn.execute("DELETE FROM budgets")
    conn.execute("DELETE FROM recurring")
    conn.execute("DELETE FROM days")

    for d in data.get("days", []):
        conn.execute(
            "INSERT INTO days (id, date, starting_balance) VALUES (?, ?, ?)",
            (d["id"], d["date"], d["starting_balance"]),
        )
    for e in data.get("expenses", []):
        conn.execute(
            """
            INSERT INTO expenses (id, day_id, description, category, amount, created_at, receipt_filename, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (e["id"], e["day_id"], e["description"], e["category"], e["amount"],
             e.get("created_at"), e.get("receipt_filename"), e.get("deleted_at")),
        )
    for i in data.get("income", []):
        conn.execute(
            "INSERT INTO income (id, day_id, description, amount, created_at) VALUES (?, ?, ?, ?, ?)",
            (i["id"], i["day_id"], i["description"], i["amount"], i.get("created_at")),
        )
    for b in data.get("budgets", []):
        conn.execute(
            "INSERT INTO budgets (id, category, amount, period) VALUES (?, ?, ?, ?)",
            (b["id"], b["category"], b["amount"], b["period"]),
        )
    for r in data.get("recurring", []):
        conn.execute(
            """
            INSERT INTO recurring (id, description, category, amount, frequency, next_date, active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (r["id"], r["description"], r["category"], r["amount"], r["frequency"], r["next_date"], r["active"]),
        )
    conn.commit()
