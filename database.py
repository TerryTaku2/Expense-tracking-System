import os
import sqlite3
from pathlib import Path

from flask import g

# On Render, DATA_DIR points at the mounted persistent disk so the database
# survives restarts/redeploys; locally it just falls back to this folder.
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent))
DB_PATH = DATA_DIR / "expense_tracker.db"

DEFAULT_CATEGORIES = ["Food", "Transport", "Bills", "Shopping", "Health", "Entertainment", "Other"]


def get_connection():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_connection():
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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
    conn.commit()
    conn.close()


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


def get_expenses(day_id):
    rows = get_connection().execute(
        "SELECT * FROM expenses WHERE day_id = ? ORDER BY created_at DESC, id DESC",
        (day_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_expense(day_id, description, category, amount):
    conn = get_connection()
    conn.execute(
        "INSERT INTO expenses (day_id, description, category, amount) VALUES (?, ?, ?, ?)",
        (day_id, description, category, amount),
    )
    conn.commit()


def delete_expense(expense_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT d.date AS date FROM expenses e JOIN days d ON d.id = e.day_id WHERE e.id = ?",
        (expense_id,),
    ).fetchone()
    if row is None:
        return None
    conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
    conn.commit()
    return row["date"]


def get_previous_day(before_date):
    row = get_connection().execute(
        """
        SELECT d.id AS id, d.date AS date, d.starting_balance AS starting_balance,
               COALESCE(SUM(e.amount), 0) AS total_spent
        FROM days d
        LEFT JOIN expenses e ON e.day_id = d.id
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
    item["balance"] = item["starting_balance"] - item["total_spent"]
    return item


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


def get_all_expenses():
    rows = get_connection().execute(
        """
        SELECT e.id AS id, d.date AS date, e.category AS category,
               e.description AS description, e.amount AS amount, e.created_at AS created_at
        FROM expenses e
        JOIN days d ON d.id = e.day_id
        ORDER BY d.date DESC, e.created_at DESC, e.id DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def get_history():
    rows = get_connection().execute(
        """
        SELECT
            d.date AS date,
            d.starting_balance AS starting_balance,
            COALESCE(SUM(e.amount), 0) AS total_spent,
            COUNT(e.id) AS expense_count
        FROM days d
        LEFT JOIN expenses e ON e.day_id = d.id
        GROUP BY d.id
        ORDER BY d.date DESC
        """
    ).fetchall()
    history = []
    for row in rows:
        item = dict(row)
        item["balance"] = item["starting_balance"] - item["total_spent"]
        history.append(item)
    return history
