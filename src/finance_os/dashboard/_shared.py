"""Shared helpers for every dashboard page: DB connection access, common
formatting. Nothing here talks to the network — Streamlit itself runs
entirely on localhost.

Deliberately *not* cached with @st.cache_resource: that cache is shared
process-wide across every browser session, and Streamlit can execute
different sessions' script reruns on different threads. A single sqlite3.
Connection (thread-affine by default) shared that way intermittently raises
"SQLite objects created in a thread can only be used in that same thread."
Opening a fresh connection per rerun costs a fraction of a millisecond on a
local file and sidesteps the problem entirely.
"""

from __future__ import annotations

import sqlite3

import streamlit as st

from finance_os.config import load_settings
from finance_os.db.connection import get_connection, init_db


def get_conn() -> sqlite3.Connection:
    settings = load_settings()
    conn = get_connection(settings)
    init_db(conn)
    return conn


def eur(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"EUR {value:,.2f}"


def pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1%}"


def page_setup(title: str) -> None:
    st.set_page_config(page_title=f"Finance OS - {title}", page_icon="💶", layout="wide")
    st.title(title)
