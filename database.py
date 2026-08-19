import calendar
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from flask import g
from werkzeug.security import generate_password_hash

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
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_connection():
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _ensure_column(conn, table, column, ddl):
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _has_column(conn, table, column):
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    return column in cols


def _table_exists(conn, table):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _migrate_legacy_single_user_table(conn, table, create_sql):
    """Older deploys of this app had no user concept, so `days`/`budgets`/
    `recurring` may exist without a user_id column and with constraints that
    are wrong for multi-tenant use (e.g. a single global UNIQUE(date)).
    SQLite can't just ALTER those constraints, so if user_id is missing we
    rename the old table aside (never delete — the data stays recoverable)
    and create a fresh, correctly-constrained table in its place."""
    if not _table_exists(conn, table):
        conn.execute(create_sql)
        return
    if _has_column(conn, table, "user_id"):
        return
    conn.execute(f"ALTER TABLE {table} RENAME TO {table}_pre_accounts")
    conn.execute(create_sql)


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            business_name TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
        """
    )

    _migrate_legacy_single_user_table(
        conn, "days",
        """
        CREATE TABLE days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            date TEXT NOT NULL,
            starting_balance REAL NOT NULL,
            UNIQUE(user_id, date)
        )
        """,
    )
    _migrate_legacy_single_user_table(
        conn, "budgets",
        """
        CREATE TABLE budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            period TEXT NOT NULL CHECK(period IN ('weekly', 'monthly')),
            UNIQUE(user_id, category)
        )
        """,
    )
    _migrate_legacy_single_user_table(
        conn, "recurring",
        """
        CREATE TABLE recurring (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            frequency TEXT NOT NULL CHECK(frequency IN ('daily', 'weekly', 'monthly')),
            next_date TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        )
        """,
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

    _quarantine_orphaned_rows(conn, "expenses")
    _quarantine_orphaned_rows(conn, "income")

    conn.commit()
    conn.close()


def _quarantine_orphaned_rows(conn, table):
    """The days/budgets/recurring migration above rebuilds `days` with its
    own autoincrement starting back at 1, but expenses/income are never
    rebuilt - they're only ever queried through a day_id a caller already
    obtained from a user-scoped day, so leaving them in place seemed
    harmless. It isn't: a freshly migrated `days` table can mint a new
    day with the same id an old, pre-accounts day used to have, and any
    expenses/income still attached to that old id would then leak straight
    into whichever new user happens to land on that id. Sweeping anything
    whose day_id no longer resolves in the current `days` table into a
    same-shaped quarantine table (never deleted) closes that hole, and is
    safe to run on every boot since a legitimate row's day_id always comes
    from a day that still exists."""
    if not _table_exists(conn, table):
        return
    orphaned = conn.execute(
        f"SELECT COUNT(*) AS n FROM {table} WHERE day_id NOT IN (SELECT id FROM days)"
    ).fetchone()["n"]
    if not orphaned:
        return
    if not _table_exists(conn, f"{table}_orphaned"):
        conn.execute(f"CREATE TABLE {table}_orphaned AS SELECT * FROM {table} WHERE 0")
    conn.execute(
        f"INSERT INTO {table}_orphaned SELECT * FROM {table} WHERE day_id NOT IN (SELECT id FROM days)"
    )
    conn.execute(f"DELETE FROM {table} WHERE day_id NOT IN (SELECT id FROM days)")


# ---------- Users ----------

def get_user_by_email(email):
    row = get_connection().execute(
        "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
    ).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id):
    row = get_connection().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def create_user(email, password, business_name):
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, business_name) VALUES (?, ?, ?)",
        (email.lower().strip(), generate_password_hash(password), business_name.strip() or None),
    )
    conn.commit()
    return cur.lastrowid


# ---------- Days ----------

def get_day(user_id, day_date):
    row = get_connection().execute(
        "SELECT * FROM days WHERE user_id = ? AND date = ?", (user_id, day_date)
    ).fetchone()
    return dict(row) if row else None


def upsert_day(user_id, day_date, starting_balance):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO days (user_id, date, starting_balance) VALUES (?, ?, ?)
        ON CONFLICT(user_id, date) DO UPDATE SET starting_balance = excluded.starting_balance
        """,
        (user_id, day_date, starting_balance),
    )
    conn.commit()


def get_previous_day(user_id, before_date):
    row = get_connection().execute(
        """
        SELECT d.id AS id, d.date AS date, d.starting_balance AS starting_balance,
               COALESCE(SUM(e.amount), 0) AS total_spent,
               COALESCE((SELECT SUM(amount) FROM income WHERE day_id = d.id), 0) AS total_income
        FROM days d
        LEFT JOIN expenses e ON e.day_id = d.id AND e.deleted_at IS NULL
        WHERE d.user_id = ? AND d.date < ?
        GROUP BY d.id
        ORDER BY d.date DESC
        LIMIT 1
        """,
        (user_id, before_date),
    ).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["balance"] = item["starting_balance"] + item["total_income"] - item["total_spent"]
    return item


# ---------- Expenses ----------
# day_id-based helpers below are only ever called with a day_id that the
# caller already obtained from a user-scoped get_day(user_id, ...), so
# ownership is implied. Anything reachable by a bare id from a URL
# (get_expense, update/delete/restore, receipts) re-checks user_id itself.

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


def get_expense(user_id, expense_id):
    row = get_connection().execute(
        """
        SELECT e.*, d.date AS date FROM expenses e
        JOIN days d ON d.id = e.day_id
        WHERE e.id = ? AND d.user_id = ?
        """,
        (expense_id, user_id),
    ).fetchone()
    return dict(row) if row else None


def update_expense(user_id, expense_id, description, category, amount):
    conn = get_connection()
    conn.execute(
        """
        UPDATE expenses SET description = ?, category = ?, amount = ?
        WHERE id = ? AND day_id IN (SELECT id FROM days WHERE user_id = ?)
        """,
        (description, category, amount, expense_id, user_id),
    )
    conn.commit()


def set_expense_receipt(user_id, expense_id, filename):
    conn = get_connection()
    conn.execute(
        """
        UPDATE expenses SET receipt_filename = ?
        WHERE id = ? AND day_id IN (SELECT id FROM days WHERE user_id = ?)
        """,
        (filename, expense_id, user_id),
    )
    conn.commit()


def delete_expense(user_id, expense_id):
    conn = get_connection()
    row = conn.execute(
        """
        SELECT d.date AS date FROM expenses e JOIN days d ON d.id = e.day_id
        WHERE e.id = ? AND d.user_id = ? AND e.deleted_at IS NULL
        """,
        (expense_id, user_id),
    ).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE expenses SET deleted_at = datetime('now', 'localtime') WHERE id = ?", (expense_id,))
    conn.commit()
    return row["date"]


def restore_expense(user_id, expense_id):
    conn = get_connection()
    row = conn.execute(
        """
        SELECT d.date AS date FROM expenses e JOIN days d ON d.id = e.day_id
        WHERE e.id = ? AND d.user_id = ? AND e.deleted_at IS NOT NULL
        """,
        (expense_id, user_id),
    ).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE expenses SET deleted_at = NULL WHERE id = ?", (expense_id,))
    conn.commit()
    return row["date"]


def get_used_categories(user_id):
    rows = get_connection().execute(
        """
        SELECT DISTINCT e.category FROM expenses e
        JOIN days d ON d.id = e.day_id
        WHERE d.user_id = ?
        ORDER BY e.category COLLATE NOCASE
        """,
        (user_id,),
    ).fetchall()
    used = [r["category"] for r in rows]
    merged = list(DEFAULT_CATEGORIES)
    for c in used:
        if c not in merged:
            merged.append(c)
    return merged


def get_all_expenses(user_id, q=None, category=None, date_from=None, date_to=None,
                      min_amount=None, max_amount=None):
    sql = """
        SELECT e.id AS id, d.date AS date, e.category AS category,
               e.description AS description, e.amount AS amount, e.created_at AS created_at,
               e.receipt_filename AS receipt_filename
        FROM expenses e
        JOIN days d ON d.id = e.day_id
        WHERE e.deleted_at IS NULL AND d.user_id = ?
    """
    params = [user_id]
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


def delete_income(user_id, income_id):
    conn = get_connection()
    row = conn.execute(
        """
        SELECT d.date AS date FROM income i JOIN days d ON d.id = i.day_id
        WHERE i.id = ? AND d.user_id = ?
        """,
        (income_id, user_id),
    ).fetchone()
    if row is None:
        return None
    conn.execute("DELETE FROM income WHERE id = ?", (income_id,))
    conn.commit()
    return row["date"]


# ---------- History ----------

def get_history(user_id):
    rows = get_connection().execute(
        """
        SELECT
            d.date AS date,
            d.starting_balance AS starting_balance,
            COALESCE((SELECT SUM(amount) FROM expenses WHERE day_id = d.id AND deleted_at IS NULL), 0) AS total_spent,
            COALESCE((SELECT SUM(amount) FROM income WHERE day_id = d.id), 0) AS total_income,
            (SELECT COUNT(*) FROM expenses WHERE day_id = d.id AND deleted_at IS NULL) AS expense_count
        FROM days d
        WHERE d.user_id = ?
        ORDER BY d.date DESC
        """,
        (user_id,),
    ).fetchall()
    history = []
    for row in rows:
        item = dict(row)
        item["balance"] = item["starting_balance"] + item["total_income"] - item["total_spent"]
        history.append(item)
    return history


def get_trends(user_id, days=30):
    rows = get_connection().execute(
        """
        SELECT
            d.date AS date,
            d.starting_balance AS starting_balance,
            COALESCE((SELECT SUM(amount) FROM expenses WHERE day_id = d.id AND deleted_at IS NULL), 0) AS total_spent,
            COALESCE((SELECT SUM(amount) FROM income WHERE day_id = d.id), 0) AS total_income
        FROM days d
        WHERE d.user_id = ?
        ORDER BY d.date DESC
        LIMIT ?
        """,
        (user_id, days),
    ).fetchall()
    trends = [dict(r) for r in rows]
    trends.reverse()
    return trends


def get_summary(user_id, period_start, period_end, prev_start, prev_end):
    def totals(start, end):
        row = get_connection().execute(
            """
            SELECT
                COALESCE((SELECT SUM(e.amount) FROM expenses e JOIN days d ON d.id = e.day_id
                          WHERE e.deleted_at IS NULL AND d.user_id = ? AND d.date >= ? AND d.date <= ?), 0) AS total_spent,
                COALESCE((SELECT SUM(i.amount) FROM income i JOIN days d ON d.id = i.day_id
                          WHERE d.user_id = ? AND d.date >= ? AND d.date <= ?), 0) AS total_income,
                (SELECT COUNT(DISTINCT d.id) FROM days d WHERE d.user_id = ? AND d.date >= ? AND d.date <= ?) AS days_tracked
            """,
            (user_id, start, end, user_id, start, end, user_id, start, end),
        ).fetchone()
        return dict(row)

    current = totals(period_start, period_end)
    previous = totals(prev_start, prev_end)

    top_row = get_connection().execute(
        """
        SELECT e.category AS category, SUM(e.amount) AS total
        FROM expenses e JOIN days d ON d.id = e.day_id
        WHERE e.deleted_at IS NULL AND d.user_id = ? AND d.date >= ? AND d.date <= ?
        GROUP BY e.category
        ORDER BY total DESC
        LIMIT 1
        """,
        (user_id, period_start, period_end),
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

def get_budgets(user_id):
    rows = get_connection().execute(
        "SELECT * FROM budgets WHERE user_id = ? ORDER BY category COLLATE NOCASE", (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_budget(user_id, category, amount, period):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO budgets (user_id, category, amount, period) VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, category) DO UPDATE SET amount = excluded.amount, period = excluded.period
        """,
        (user_id, category, amount, period),
    )
    conn.commit()


def delete_budget(user_id, category):
    conn = get_connection()
    conn.execute("DELETE FROM budgets WHERE user_id = ? AND category = ?", (user_id, category))
    conn.commit()


def get_budget_progress(user_id):
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    progress = []
    for b in get_budgets(user_id):
        start = week_start if b["period"] == "weekly" else month_start
        row = get_connection().execute(
            """
            SELECT COALESCE(SUM(e.amount), 0) AS spent
            FROM expenses e JOIN days d ON d.id = e.day_id
            WHERE e.deleted_at IS NULL AND d.user_id = ? AND e.category = ? AND d.date >= ? AND d.date <= ?
            """,
            (user_id, b["category"], start.isoformat(), today.isoformat()),
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

def get_recurring(user_id):
    rows = get_connection().execute(
        "SELECT * FROM recurring WHERE user_id = ? ORDER BY next_date", (user_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def add_recurring(user_id, description, category, amount, frequency, start_date):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO recurring (user_id, description, category, amount, frequency, next_date)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, description, category, amount, frequency, start_date),
    )
    conn.commit()


def set_recurring_active(user_id, recurring_id, active):
    conn = get_connection()
    conn.execute(
        "UPDATE recurring SET active = ? WHERE id = ? AND user_id = ?",
        (1 if active else 0, recurring_id, user_id),
    )
    conn.commit()


def delete_recurring(user_id, recurring_id):
    conn = get_connection()
    conn.execute("DELETE FROM recurring WHERE id = ? AND user_id = ?", (recurring_id, user_id))
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


def apply_due_recurring(user_id, target_date):
    """Applies any recurring items due on/before target_date into that day,
    catching up on missed occurrences one at a time. Only runs if the day
    already exists (has a starting balance), since there's nowhere to file
    the expense otherwise."""
    day = get_day(user_id, target_date)
    if day is None:
        return []

    conn = get_connection()
    applied = []
    for _ in range(60):  # safety cap against runaway catch-up loops
        due = conn.execute(
            "SELECT * FROM recurring WHERE user_id = ? AND active = 1 AND next_date <= ? ORDER BY next_date LIMIT 1",
            (user_id, target_date),
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

def export_backup(user_id):
    conn = get_connection()
    days = [dict(r) for r in conn.execute("SELECT * FROM days WHERE user_id = ?", (user_id,)).fetchall()]
    day_ids = [d["id"] for d in days]
    placeholders = ",".join("?" * len(day_ids)) if day_ids else "NULL"
    expenses = (
        [dict(r) for r in conn.execute(f"SELECT * FROM expenses WHERE day_id IN ({placeholders})", day_ids).fetchall()]
        if day_ids else []
    )
    income = (
        [dict(r) for r in conn.execute(f"SELECT * FROM income WHERE day_id IN ({placeholders})", day_ids).fetchall()]
        if day_ids else []
    )
    budgets = [dict(r) for r in conn.execute("SELECT * FROM budgets WHERE user_id = ?", (user_id,)).fetchall()]
    recurring = [dict(r) for r in conn.execute("SELECT * FROM recurring WHERE user_id = ?", (user_id,)).fetchall()]
    return {"days": days, "expenses": expenses, "income": income, "budgets": budgets, "recurring": recurring}


def import_backup(user_id, data):
    """Replaces only the current user's data with the contents of the
    backup. Rows are re-inserted with fresh ids (never the original ones,
    since those ids are shared across all accounts) and day_id references
    in expenses/income are remapped to match."""
    conn = get_connection()
    conn.execute("DELETE FROM income WHERE day_id IN (SELECT id FROM days WHERE user_id = ?)", (user_id,))
    conn.execute("DELETE FROM expenses WHERE day_id IN (SELECT id FROM days WHERE user_id = ?)", (user_id,))
    conn.execute("DELETE FROM budgets WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM recurring WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM days WHERE user_id = ?", (user_id,))

    day_id_map = {}
    for d in data.get("days", []):
        cur = conn.execute(
            "INSERT INTO days (user_id, date, starting_balance) VALUES (?, ?, ?)",
            (user_id, d["date"], d["starting_balance"]),
        )
        day_id_map[d["id"]] = cur.lastrowid

    for e in data.get("expenses", []):
        new_day_id = day_id_map.get(e["day_id"])
        if new_day_id is None:
            continue
        conn.execute(
            """
            INSERT INTO expenses (day_id, description, category, amount, created_at, receipt_filename, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (new_day_id, e["description"], e["category"], e["amount"],
             e.get("created_at"), e.get("receipt_filename"), e.get("deleted_at")),
        )
    for i in data.get("income", []):
        new_day_id = day_id_map.get(i["day_id"])
        if new_day_id is None:
            continue
        conn.execute(
            "INSERT INTO income (day_id, description, amount, created_at) VALUES (?, ?, ?, ?)",
            (new_day_id, i["description"], i["amount"], i.get("created_at")),
        )
    for b in data.get("budgets", []):
        conn.execute(
            "INSERT INTO budgets (user_id, category, amount, period) VALUES (?, ?, ?, ?)",
            (user_id, b["category"], b["amount"], b["period"]),
        )
    for r in data.get("recurring", []):
        conn.execute(
            """
            INSERT INTO recurring (user_id, description, category, amount, frequency, next_date, active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, r["description"], r["category"], r["amount"], r["frequency"], r["next_date"], r["active"]),
        )
    conn.commit()
