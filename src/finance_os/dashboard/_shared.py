"""Shared helpers for every dashboard page: one cached local DB connection,
common formatting. Nothing here talks to the network — Streamlit itself runs
entirely on localhost.
"""

from __future__ import annotations

import sqlite3

import streamlit as st

from finance_os.config import load_settings
from finance_os.db.connection import get_connection, init_db


@st.cache_resource(show_spinner=False)
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
