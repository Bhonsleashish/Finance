"""SQLite connection management, schema initialization and reference-data seeding.

The whole system is one file: `database/finance.db`. There is no server, no
network socket, nothing to configure — just a local file on disk.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from finance_os.config import Settings, load_categories, load_merchants, load_settings

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection(settings: Settings | None = None, db_path: Path | None = None) -> sqlite3.Connection:
    """Open (and lazily initialize) the local SQLite database."""
    settings = settings or load_settings()
    path = db_path or settings.database_file
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connect(settings: Settings | None = None, db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = get_connection(settings, db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables (idempotent) and seed categories/merchants."""
    with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
        conn.executescript(fh.read())
    _seed_categories(conn)
    _seed_merchants(conn)
    conn.commit()


def _seed_categories(conn: sqlite3.Connection) -> None:
    categories = load_categories()
    for name, meta in categories.items():
        group = meta.get("group", "wants") if isinstance(meta, dict) else "wants"
        conn.execute(
            'INSERT OR IGNORE INTO categories (name, "group", is_custom) VALUES (?, ?, 0)',
            (name, group),
        )


def _seed_merchants(conn: sqlite3.Connection) -> None:
    merchants = load_merchants()
    for name, meta in merchants.items():
        category = meta.get("category") if isinstance(meta, dict) else None
        patterns = meta.get("patterns", []) if isinstance(meta, dict) else []
        category_id = None
        if category:
            row = conn.execute("SELECT id FROM categories WHERE name = ?", (category,)).fetchone()
            category_id = row["id"] if row else None
        conn.execute(
            "INSERT OR IGNORE INTO merchants (name, default_category_id, is_learned) VALUES (?, ?, 0)",
            (name, category_id),
        )
        merchant_row = conn.execute("SELECT id FROM merchants WHERE name = ?", (name,)).fetchone()
        merchant_id = merchant_row["id"]
        for pattern in patterns:
            conn.execute(
                "INSERT OR IGNORE INTO merchant_patterns (merchant_id, pattern) VALUES (?, ?)",
                (merchant_id, pattern.lower()),
            )


def ensure_initialized(settings: Settings | None = None) -> Path:
    """Convenience helper: open the DB, run init_db, return the file path."""
    settings = settings or load_settings()
    with connect(settings) as conn:
        init_db(conn)
    return settings.database_file
