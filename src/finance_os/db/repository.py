"""Data-access layer. Every read/write to the database goes through here so
the rest of the codebase never writes raw SQL inline.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, fields
from datetime import date, datetime
from typing import Any, Optional

import pandas as pd

# ---------------------------------------------------------------------------
# Hashing helpers (dedup)
# ---------------------------------------------------------------------------


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def transaction_dedup_hash(txn_date: str, amount: float, description: str, account_name: str = "") -> str:
    raw = f"{txn_date}|{round(amount, 2)}|{description.strip().lower()}|{account_name.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# documents
# ---------------------------------------------------------------------------


def find_document_by_hash(conn: sqlite3.Connection, content_hash: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM documents WHERE content_hash = ?", (content_hash,)).fetchone()


def insert_document(
    conn: sqlite3.Connection,
    doc_type: str,
    source_path: str,
    content_hash: str,
    period_month: Optional[str] = None,
    extraction_method: Optional[str] = None,
    raw_text: Optional[str] = None,
    status: str = "processed",
    notes: Optional[str] = None,
) -> int:
    existing = find_document_by_hash(conn, content_hash)
    if existing:
        return existing["id"]
    cur = conn.execute(
        """INSERT INTO documents
           (doc_type, source_path, content_hash, period_month, extraction_method, raw_text, status, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (doc_type, source_path, content_hash, period_month, extraction_method, raw_text, status, notes),
    )
    return cur.lastrowid


# ---------------------------------------------------------------------------
# categories / merchants
# ---------------------------------------------------------------------------


def get_category_id(conn: sqlite3.Connection, name: str) -> Optional[int]:
    row = conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()
    return row["id"] if row else None


def get_or_create_category(conn: sqlite3.Connection, name: str, group: str = "wants") -> int:
    existing = get_category_id(conn, name)
    if existing:
        return existing
    cur = conn.execute(
        'INSERT INTO categories (name, "group", is_custom) VALUES (?, ?, 1)', (name, group)
    )
    return cur.lastrowid


def list_categories(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query('SELECT id, name, "group" FROM categories ORDER BY name', conn)


def get_or_create_merchant(
    conn: sqlite3.Connection, name: str, category_id: Optional[int] = None, is_learned: bool = False
) -> int:
    row = conn.execute("SELECT id FROM merchants WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO merchants (name, default_category_id, is_learned) VALUES (?, ?, ?)",
        (name, category_id, int(is_learned)),
    )
    return cur.lastrowid


def add_merchant_pattern(conn: sqlite3.Connection, merchant_id: int, pattern: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO merchant_patterns (merchant_id, pattern) VALUES (?, ?)",
        (merchant_id, pattern.lower().strip()),
    )


def all_merchant_patterns(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT mp.pattern AS pattern, m.id AS merchant_id, m.name AS merchant_name,
                  m.default_category_id AS category_id
           FROM merchant_patterns mp JOIN merchants m ON m.id = mp.merchant_id"""
    ).fetchall()


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------


def get_or_create_account(
    conn: sqlite3.Connection, name: str, institution: Optional[str] = None, account_type: str = "checking"
) -> int:
    row = conn.execute("SELECT id FROM accounts WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO accounts (name, institution, account_type) VALUES (?, ?, ?)",
        (name, institution, account_type),
    )
    return cur.lastrowid


# ---------------------------------------------------------------------------
# transactions
# ---------------------------------------------------------------------------


def insert_transaction(
    conn: sqlite3.Connection,
    txn_date: str,
    description_raw: str,
    amount: float,
    direction: str,
    document_id: Optional[int] = None,
    account_id: Optional[int] = None,
    merchant_id: Optional[int] = None,
    category_id: Optional[int] = None,
    is_manual_entry: bool = False,
    account_name: str = "",
) -> Optional[int]:
    """Insert a transaction. Returns the new row id, or None if it was a
    duplicate of an already-imported transaction (same date/amount/desc/account).
    """
    period_month = txn_date[:7]
    dedup_hash = transaction_dedup_hash(txn_date, amount, description_raw, account_name)
    existing = conn.execute("SELECT id FROM transactions WHERE dedup_hash = ?", (dedup_hash,)).fetchone()
    if existing:
        return None
    cur = conn.execute(
        """INSERT INTO transactions
           (document_id, account_id, txn_date, period_month, description_raw, merchant_id,
            category_id, amount, direction, is_manual_entry, dedup_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            document_id,
            account_id,
            txn_date,
            period_month,
            description_raw,
            merchant_id,
            category_id,
            amount,
            direction,
            int(is_manual_entry),
            dedup_hash,
        ),
    )
    return cur.lastrowid


def correct_transaction_category(
    conn: sqlite3.Connection, transaction_id: int, new_category_id: int, merchant_text: Optional[str] = None
) -> None:
    row = conn.execute("SELECT category_id FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
    old_category_id = row["category_id"] if row else None
    conn.execute(
        "UPDATE transactions SET category_id = ?, is_corrected = 1 WHERE id = ?",
        (new_category_id, transaction_id),
    )
    conn.execute(
        """INSERT INTO category_corrections (transaction_id, merchant_text, old_category_id, new_category_id)
           VALUES (?, ?, ?, ?)""",
        (transaction_id, merchant_text, old_category_id, new_category_id),
    )


def get_transactions_df(
    conn: sqlite3.Connection,
    start_month: Optional[str] = None,
    end_month: Optional[str] = None,
    category: Optional[str] = None,
) -> pd.DataFrame:
    query = """
        SELECT t.id, t.txn_date, t.period_month, t.description_raw, t.amount, t.direction,
               t.is_manual_entry, t.is_corrected,
               m.name AS merchant, c.name AS category, c."group" AS category_group,
               a.name AS account
        FROM transactions t
        LEFT JOIN merchants m ON m.id = t.merchant_id
        LEFT JOIN categories c ON c.id = t.category_id
        LEFT JOIN accounts a ON a.id = t.account_id
        WHERE 1=1
    """
    params: list[Any] = []
    if start_month:
        query += " AND t.period_month >= ?"
        params.append(start_month)
    if end_month:
        query += " AND t.period_month <= ?"
        params.append(end_month)
    if category:
        query += " AND c.name = ?"
        params.append(category)
    query += " ORDER BY t.txn_date"
    df = pd.read_sql_query(query, conn, params=params)
    if not df.empty:
        df["txn_date"] = pd.to_datetime(df["txn_date"])
    return df


def delete_transaction(conn: sqlite3.Connection, transaction_id: int) -> bool:
    cur = conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
    return cur.rowcount > 0


def uncategorized_transactions(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT id, txn_date, description_raw, amount FROM transactions WHERE category_id IS NULL ORDER BY txn_date",
        conn,
    )


# ---------------------------------------------------------------------------
# salary slips
# ---------------------------------------------------------------------------

SALARY_FIELDS = [
    "employer",
    "gross_salary",
    "net_salary",
    "income_tax",
    "solidarity_surcharge",
    "church_tax",
    "health_insurance",
    "pension_insurance",
    "unemployment_insurance",
    "nursing_care_insurance",
    "overtime_pay",
    "bonus",
    "reimbursements",
    "other_deductions",
    "other_earnings",
]


def upsert_salary_slip(
    conn: sqlite3.Connection,
    period_month: str,
    document_id: Optional[int] = None,
    **fields_: Any,
) -> int:
    employer = fields_.get("employer") or "Unknown"
    row = conn.execute(
        "SELECT id FROM salary_slips WHERE period_month = ? AND employer = ?", (period_month, employer)
    ).fetchone()
    values = {k: fields_.get(k) for k in SALARY_FIELDS}
    if row:
        set_clause = ", ".join(f"{k} = :{k}" for k in SALARY_FIELDS)
        conn.execute(
            f"UPDATE salary_slips SET {set_clause}, document_id = :document_id WHERE id = :id",
            {**values, "document_id": document_id, "id": row["id"]},
        )
        return row["id"]
    columns = ["document_id", "period_month", *SALARY_FIELDS]
    placeholders = ", ".join(f":{c}" for c in columns)
    cur = conn.execute(
        f"INSERT INTO salary_slips ({', '.join(columns)}) VALUES ({placeholders})",
        {**values, "document_id": document_id, "period_month": period_month},
    )
    return cur.lastrowid


def get_salary_slips_df(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query("SELECT * FROM salary_slips ORDER BY period_month", conn)
    return df


# ---------------------------------------------------------------------------
# goals
# ---------------------------------------------------------------------------


def upsert_goal(
    conn: sqlite3.Connection,
    name: str,
    goal_type: str,
    target_amount: float,
    current_amount: float = 0.0,
    monthly_contribution: float = 0.0,
    target_date: Optional[str] = None,
    notes: Optional[str] = None,
) -> int:
    row = conn.execute("SELECT id FROM goals WHERE name = ?", (name,)).fetchone()
    if row:
        conn.execute(
            """UPDATE goals SET goal_type=?, target_amount=?, current_amount=?, monthly_contribution=?,
               target_date=?, notes=? WHERE id=?""",
            (goal_type, target_amount, current_amount, monthly_contribution, target_date, notes, row["id"]),
        )
        return row["id"]
    cur = conn.execute(
        """INSERT INTO goals (name, goal_type, target_amount, current_amount, monthly_contribution,
           target_date, notes) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (name, goal_type, target_amount, current_amount, monthly_contribution, target_date, notes),
    )
    return cur.lastrowid


def list_goals(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM goals WHERE is_active = 1 ORDER BY created_at", conn)


def deactivate_goal(conn: sqlite3.Connection, goal_id: int) -> None:
    """Soft-delete: goals are kept (with their contribution history) but
    hidden from list_goals()/the dashboard once deactivated."""
    conn.execute("UPDATE goals SET is_active = 0 WHERE id = ?", (goal_id,))


def contribute_to_goal(conn: sqlite3.Connection, goal_id: int, amount: float, contributed_on: str) -> None:
    conn.execute(
        "INSERT INTO goal_contributions (goal_id, amount, contributed_on) VALUES (?, ?, ?)",
        (goal_id, amount, contributed_on),
    )
    conn.execute("UPDATE goals SET current_amount = current_amount + ? WHERE id = ?", (amount, goal_id))


# ---------------------------------------------------------------------------
# investments
# ---------------------------------------------------------------------------


def add_investment(
    conn: sqlite3.Connection,
    name: str,
    purchase_date: str,
    amount_invested: float,
    asset_type: str = "other",
    broker: Optional[str] = None,
    quantity: Optional[float] = None,
    current_value: Optional[float] = None,
    currency: str = "EUR",
    document_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> int:
    value_updated_at = datetime.utcnow().isoformat(sep=" ", timespec="seconds") if current_value is not None else None
    cur = conn.execute(
        """INSERT INTO investments
           (document_id, name, asset_type, broker, purchase_date, quantity, amount_invested,
            current_value, currency, value_updated_at, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            document_id, name, asset_type, broker, purchase_date, quantity, amount_invested,
            current_value, currency, value_updated_at, notes,
        ),
    )
    return cur.lastrowid


def update_investment_value(conn: sqlite3.Connection, investment_id: int, current_value: float) -> bool:
    value_updated_at = datetime.utcnow().isoformat(sep=" ", timespec="seconds")
    cur = conn.execute(
        "UPDATE investments SET current_value = ?, value_updated_at = ? WHERE id = ?",
        (current_value, value_updated_at, investment_id),
    )
    return cur.rowcount > 0


def deactivate_investment(conn: sqlite3.Connection, investment_id: int) -> None:
    conn.execute("UPDATE investments SET is_active = 0 WHERE id = ?", (investment_id,))


def delete_investment(conn: sqlite3.Connection, investment_id: int) -> bool:
    cur = conn.execute("DELETE FROM investments WHERE id = ?", (investment_id,))
    return cur.rowcount > 0


def get_investments_df(conn: sqlite3.Connection, active_only: bool = True) -> pd.DataFrame:
    query = "SELECT * FROM investments"
    if active_only:
        query += " WHERE is_active = 1"
    query += " ORDER BY purchase_date"
    return pd.read_sql_query(query, conn)


# ---------------------------------------------------------------------------
# budgets
# ---------------------------------------------------------------------------


def set_budget(conn: sqlite3.Connection, period_month: str, category_id: int, amount: float, source: str = "engine") -> None:
    conn.execute(
        """INSERT INTO budgets (period_month, category_id, budgeted_amount, source)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(period_month, category_id) DO UPDATE SET budgeted_amount=excluded.budgeted_amount, source=excluded.source""",
        (period_month, category_id, amount, source),
    )


def get_budgets_df(conn: sqlite3.Connection, period_month: str) -> pd.DataFrame:
    return pd.read_sql_query(
        """SELECT b.period_month, c.name AS category, c."group" AS category_group, b.budgeted_amount, b.source
           FROM budgets b JOIN categories c ON c.id = b.category_id WHERE b.period_month = ?""",
        conn,
        params=[period_month],
    )


# ---------------------------------------------------------------------------
# net worth
# ---------------------------------------------------------------------------


def upsert_net_worth_snapshot(
    conn: sqlite3.Connection, snapshot_date: str, assets_total: float, liabilities_total: float, notes: Optional[str] = None
) -> None:
    net_worth = assets_total - liabilities_total
    conn.execute(
        """INSERT INTO net_worth_snapshots (snapshot_date, assets_total, liabilities_total, net_worth, notes)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(snapshot_date) DO UPDATE SET assets_total=excluded.assets_total,
               liabilities_total=excluded.liabilities_total, net_worth=excluded.net_worth, notes=excluded.notes""",
        (snapshot_date, assets_total, liabilities_total, net_worth, notes),
    )


def get_net_worth_df(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM net_worth_snapshots ORDER BY snapshot_date", conn)


# ---------------------------------------------------------------------------
# subscriptions
# ---------------------------------------------------------------------------


def upsert_subscription(
    conn: sqlite3.Connection,
    merchant_id: Optional[int],
    label: str,
    monthly_cost: float,
    interval_days: int,
    first_seen: str,
    last_seen: str,
    occurrences: int,
    recommend_cancel: bool = False,
    status: str = "active",
) -> None:
    conn.execute(
        """INSERT INTO subscriptions (merchant_id, label, monthly_cost, interval_days, first_seen, last_seen,
               occurrences, status, recommend_cancel)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(merchant_id, label) DO UPDATE SET monthly_cost=excluded.monthly_cost,
               interval_days=excluded.interval_days, last_seen=excluded.last_seen,
               occurrences=excluded.occurrences, status=excluded.status,
               recommend_cancel=excluded.recommend_cancel""",
        (merchant_id, label, monthly_cost, interval_days, first_seen, last_seen, occurrences, status, int(recommend_cancel)),
    )


def get_subscriptions_df(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM subscriptions ORDER BY monthly_cost DESC", conn)


# ---------------------------------------------------------------------------
# alerts
# ---------------------------------------------------------------------------


def insert_alert(conn: sqlite3.Connection, alert_type: str, message: str, severity: str = "info", period_month: Optional[str] = None) -> None:
    dup = conn.execute(
        "SELECT id FROM alerts WHERE alert_type=? AND message=? AND period_month IS ?",
        (alert_type, message, period_month),
    ).fetchone()
    if dup:
        return
    conn.execute(
        "INSERT INTO alerts (alert_type, severity, period_month, message) VALUES (?, ?, ?, ?)",
        (alert_type, severity, period_month, message),
    )


def get_alerts_df(conn: sqlite3.Connection, unacknowledged_only: bool = False) -> pd.DataFrame:
    query = "SELECT * FROM alerts"
    if unacknowledged_only:
        query += " WHERE acknowledged = 0"
    query += " ORDER BY created_at DESC"
    return pd.read_sql_query(query, conn)


# ---------------------------------------------------------------------------
# reviews cache
# ---------------------------------------------------------------------------


def save_review(conn: sqlite3.Connection, review_type: str, period_key: str, payload_json: str) -> None:
    conn.execute(
        """INSERT INTO reviews (review_type, period_key, payload_json) VALUES (?, ?, ?)
           ON CONFLICT(review_type, period_key) DO UPDATE SET payload_json=excluded.payload_json,
               generated_at=datetime('now')""",
        (review_type, period_key, payload_json),
    )


def get_review(conn: sqlite3.Connection, review_type: str, period_key: str) -> Optional[str]:
    row = conn.execute(
        "SELECT payload_json FROM reviews WHERE review_type = ? AND period_key = ?", (review_type, period_key)
    ).fetchone()
    return row["payload_json"] if row else None
