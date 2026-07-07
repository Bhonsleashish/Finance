"""Weekly review: wins, mistakes, overspending, best saving opportunity,
goal progress, financial health score, top recommendations.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

import pandas as pd

from finance_os.analysis.budgeting import budget_vs_actual
from finance_os.analysis.cashflow import spending_by_category, trailing_average
from finance_os.analysis.goals import all_goals_progress
from finance_os.analysis.health_score import compute_health_score
from finance_os.db import repository as repo
from finance_os.utils.dates import iso_week_bounds


def _week_transactions(conn: sqlite3.Connection, start: date, end: date) -> pd.DataFrame:
    df = repo.get_transactions_df(conn)
    if df.empty:
        return df
    mask = (df["txn_date"].dt.date >= start) & (df["txn_date"].dt.date <= end)
    return df[mask]


def generate_weekly_review(conn: sqlite3.Connection, reference_date: date | None = None) -> dict:
    start, end, week_key = iso_week_bounds(reference_date)
    week_txns = _week_transactions(conn, start, end)
    period_month = start.strftime("%Y-%m")

    expenses = week_txns[week_txns["direction"] == "expense"] if not week_txns.empty else week_txns
    income = week_txns[week_txns["direction"] == "income"] if not week_txns.empty else week_txns
    total_spent = float(expenses["amount"].abs().sum()) if not expenses.empty else 0.0
    total_income = float(income["amount"].sum()) if not income.empty else 0.0

    wins: list[str] = []
    mistakes: list[str] = []
    overspending: list[dict] = []

    if not expenses.empty:
        by_cat = expenses.groupby("category")["amount"].sum().abs()
        for category, total in by_cat.items():
            baseline_weekly = trailing_average(conn, category or "Uncategorized", months=3, before_month=period_month) / 4.33
            if baseline_weekly > 0 and total > baseline_weekly * 1.3:
                overspending.append({
                    "category": category, "spent_this_week": round(float(total), 2),
                    "typical_weekly": round(float(baseline_weekly), 2),
                })
                mistakes.append(f"Overspent on {category}: €{total:,.2f} vs typical €{baseline_weekly:,.2f}/week.")
            elif baseline_weekly > 0 and total < baseline_weekly * 0.7:
                wins.append(f"Kept {category} spending low this week: €{total:,.2f} vs typical €{baseline_weekly:,.2f}.")

    if total_income > total_spent:
        wins.append(f"Positive cash flow this week: +€{total_income - total_spent:,.2f}.")
    elif total_spent > 0:
        mistakes.append(f"Spent more than earned this week: -€{total_spent - total_income:,.2f}.")

    best_opportunity = None
    if overspending:
        biggest = max(overspending, key=lambda o: o["spent_this_week"] - o["typical_weekly"])
        best_opportunity = (
            f"Cutting {biggest['category']} back to its typical €{biggest['typical_weekly']:,.2f}/week "
            f"would save ~€{biggest['spent_this_week'] - biggest['typical_weekly']:,.2f}/week "
            f"(~€{(biggest['spent_this_week'] - biggest['typical_weekly']) * 4.33:,.2f}/month)."
        )

    goals = [g.__dict__ for g in all_goals_progress(conn)]
    health = compute_health_score(conn, period_month)

    recommendations: list[str] = []
    if best_opportunity:
        recommendations.append(best_opportunity)
    if health.total < 60:
        recommendations.append(f"Financial health score is {health.total}/100 — see monthly review for details.")
    if not recommendations:
        recommendations.append("Nothing urgent this week — stay the course.")

    payload = {
        "week": week_key,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "total_income": round(total_income, 2),
        "total_spent": round(total_spent, 2),
        "net": round(total_income - total_spent, 2),
        "wins": wins or ["No standout wins detected — keep tracking."],
        "mistakes": mistakes or ["No major mistakes detected this week."],
        "overspending": overspending,
        "best_saving_opportunity": best_opportunity or "No clear overspending pattern detected this week.",
        "goals_progress": goals,
        "financial_health_score": {"total": health.total, "components": health.components},
        "top_recommendations": recommendations,
    }

    repo.save_review(conn, "weekly", week_key, json.dumps(payload, default=str))
    return payload
