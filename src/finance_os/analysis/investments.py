"""Investment/holdings tracking.

This app never calls a live market-data API (no external calls at all, by
design), so "current value" is whatever you last told it — via
`finance investment update-value` or the dashboard. Until you update it, a
position is valued at cost (amount_invested), so totals are always at least
as conservative as your actual cost basis.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pandas as pd

from finance_os.db import repository as repo


@dataclass
class PortfolioSummary:
    total_invested: float
    total_current_value: float
    unrealized_gain: float
    unrealized_gain_pct: float | None
    holdings_count: int
    stale_value_count: int  # holdings whose current_value has never been set


def holdings_df(conn: sqlite3.Connection) -> pd.DataFrame:
    df = repo.get_investments_df(conn)
    if df.empty:
        return df
    df = df.copy()
    df["value_is_estimated"] = df["current_value"].isna()
    df["effective_value"] = df["current_value"].fillna(df["amount_invested"])
    df["unrealized_gain"] = df["effective_value"] - df["amount_invested"]
    df["unrealized_gain_pct"] = df.apply(
        lambda r: (r["unrealized_gain"] / r["amount_invested"]) if r["amount_invested"] else None, axis=1
    )
    return df


def portfolio_summary(conn: sqlite3.Connection) -> PortfolioSummary:
    df = holdings_df(conn)
    if df.empty:
        return PortfolioSummary(0.0, 0.0, 0.0, None, 0, 0)
    total_invested = float(df["amount_invested"].sum())
    total_current_value = float(df["effective_value"].sum())
    gain = total_current_value - total_invested
    gain_pct = (gain / total_invested) if total_invested else None
    return PortfolioSummary(
        total_invested=round(total_invested, 2),
        total_current_value=round(total_current_value, 2),
        unrealized_gain=round(gain, 2),
        unrealized_gain_pct=gain_pct,
        holdings_count=len(df),
        stale_value_count=int(df["value_is_estimated"].sum()),
    )


def allocation_by_asset_type(conn: sqlite3.Connection) -> pd.DataFrame:
    df = holdings_df(conn)
    if df.empty:
        return df
    return df.groupby("asset_type")["effective_value"].sum().reset_index().rename(columns={"effective_value": "value"})


def allocation_by_holding(conn: sqlite3.Connection) -> pd.DataFrame:
    df = holdings_df(conn)
    if df.empty:
        return df
    return df.groupby("name")["effective_value"].sum().reset_index().rename(columns={"effective_value": "value"}).sort_values("value", ascending=False)
