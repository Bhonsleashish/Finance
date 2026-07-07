"""Net worth tracking: snapshots over time + derived trend/change metrics."""

from __future__ import annotations

import sqlite3

import pandas as pd

from finance_os.db import repository as repo


def record_snapshot(conn: sqlite3.Connection, snapshot_date: str, assets_total: float, liabilities_total: float, notes: str | None = None) -> None:
    repo.upsert_net_worth_snapshot(conn, snapshot_date, assets_total, liabilities_total, notes)


def net_worth_trend(conn: sqlite3.Connection) -> pd.DataFrame:
    return repo.get_net_worth_df(conn)


def latest_net_worth(conn: sqlite3.Connection) -> float | None:
    df = net_worth_trend(conn)
    if df.empty:
        return None
    return float(df.sort_values("snapshot_date").iloc[-1]["net_worth"])


def net_worth_change(conn: sqlite3.Connection, months_back: int = 1) -> dict:
    df = net_worth_trend(conn)
    if len(df) < 2:
        return {"change": None, "change_pct": None}
    df = df.sort_values("snapshot_date").reset_index(drop=True)
    idx = max(0, len(df) - 1 - months_back)
    prev, cur = df.iloc[idx]["net_worth"], df.iloc[-1]["net_worth"]
    change = cur - prev
    change_pct = (change / abs(prev)) if prev else None
    return {"change": change, "change_pct": change_pct, "previous": prev, "current": cur}


def estimate_net_worth_from_cashflow(conn: sqlite3.Connection, opening_net_worth: float = 0.0) -> pd.DataFrame:
    """When no explicit net-worth snapshots exist yet, approximate net worth
    growth as opening balance + cumulative net cash flow (a reasonable proxy
    until the user records real account/investment/debt snapshots)."""
    from finance_os.analysis.cashflow import monthly_summary

    summary = monthly_summary(conn)
    if summary.empty:
        return summary
    summary = summary.sort_values("period_month").copy()
    summary["estimated_net_worth"] = opening_net_worth + summary["net_cashflow"].cumsum()
    return summary[["period_month", "estimated_net_worth"]]
