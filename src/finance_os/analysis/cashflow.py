"""Monthly cash flow, savings rate, spending-by-category trends."""

from __future__ import annotations

import sqlite3

import pandas as pd

from finance_os.db import repository as repo


def monthly_summary(conn: sqlite3.Connection, start_month: str | None = None, end_month: str | None = None) -> pd.DataFrame:
    """One row per month: income, expenses, net_cashflow, savings_rate."""
    df = repo.get_transactions_df(conn, start_month, end_month)
    if df.empty:
        return pd.DataFrame(columns=["period_month", "income", "expenses", "net_cashflow", "savings_rate"])

    income = df[df["direction"] == "income"].groupby("period_month")["amount"].sum()
    expenses = df[df["direction"] == "expense"].groupby("period_month")["amount"].sum().abs()

    summary = pd.DataFrame({"income": income, "expenses": expenses}).fillna(0.0)
    summary["net_cashflow"] = summary["income"] - summary["expenses"]
    summary["savings_rate"] = summary.apply(
        lambda r: (r["net_cashflow"] / r["income"]) if r["income"] else 0.0, axis=1
    )
    summary = summary.reset_index().rename(columns={"index": "period_month"}).sort_values("period_month")
    return summary


def spending_by_category(conn: sqlite3.Connection, period_month: str) -> pd.DataFrame:
    df = repo.get_transactions_df(conn, period_month, period_month)
    if df.empty:
        return pd.DataFrame(columns=["category", "total"])
    expenses = df[df["direction"] == "expense"].copy()
    expenses["category"] = expenses["category"].fillna("Uncategorized")
    grouped = expenses.groupby("category")["amount"].sum().abs().sort_values(ascending=False)
    return grouped.reset_index().rename(columns={"amount": "total"})


def top_spending_categories(conn: sqlite3.Connection, period_month: str, n: int = 5) -> pd.DataFrame:
    return spending_by_category(conn, period_month).head(n)


def category_trend(conn: sqlite3.Connection, category: str, months: int = 12) -> pd.DataFrame:
    df = repo.get_transactions_df(conn, category=category)
    if df.empty:
        return pd.DataFrame(columns=["period_month", "total"])
    expenses = df[df["direction"] == "expense"]
    grouped = expenses.groupby("period_month")["amount"].sum().abs().reset_index()
    grouped = grouped.rename(columns={"amount": "total"}).sort_values("period_month")
    return grouped.tail(months)


def trailing_average(conn: sqlite3.Connection, category: str, months: int = 3, before_month: str | None = None) -> float:
    trend = category_trend(conn, category, months=months + 1)
    if before_month:
        trend = trend[trend["period_month"] < before_month]
    trend = trend.tail(months)
    if trend.empty:
        return 0.0
    return float(trend["total"].mean())


def recurring_bills(conn: sqlite3.Connection) -> pd.DataFrame:
    """Fixed-category transactions, useful as the 'known bills' baseline."""
    from finance_os.config import load_settings

    settings = load_settings()
    fixed_categories = settings.get("budgeting", "fixed_categories", default=[])
    df = repo.get_transactions_df(conn)
    if df.empty:
        return pd.DataFrame()
    return df[(df["direction"] == "expense") & (df["category"].isin(fixed_categories))]
