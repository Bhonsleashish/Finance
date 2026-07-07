"""Comprehensive monthly review: income, expenses, savings, net worth, debt,
investments, largest purchases/savings, budget performance, recommendations.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date

from finance_os.analysis.alerts import evaluate_alerts
from finance_os.analysis.budgeting import budget_vs_actual, generate_budget, persist_budget
from finance_os.analysis.cashflow import monthly_summary, spending_by_category
from finance_os.analysis.goals import all_goals_progress
from finance_os.analysis.health_score import compute_health_score
from finance_os.analysis.networth import net_worth_change, net_worth_trend
from finance_os.analysis.salary import highlight_changes
from finance_os.analysis.subscriptions import detect_subscriptions, persist_subscriptions, total_monthly_subscription_cost
from finance_os.db import repository as repo


def _largest_transactions(conn: sqlite3.Connection, period_month: str, direction: str, n: int = 5):
    df = repo.get_transactions_df(conn, period_month, period_month)
    if df.empty:
        return []
    subset = df[df["direction"] == direction].copy()
    subset["abs_amount"] = subset["amount"].abs()
    subset = subset.sort_values("abs_amount", ascending=False).head(n)
    return subset[["txn_date", "description_raw", "merchant", "category", "amount"]].assign(
        txn_date=lambda d: d["txn_date"].dt.strftime("%Y-%m-%d")
    ).to_dict("records")


def generate_monthly_review(conn: sqlite3.Connection, period_month: str) -> dict:
    summary = monthly_summary(conn, end_month=period_month)
    current = summary[summary["period_month"] == period_month]
    income = float(current.iloc[0]["income"]) if not current.empty else 0.0
    expenses = float(current.iloc[0]["expenses"]) if not current.empty else 0.0
    net_cashflow = float(current.iloc[0]["net_cashflow"]) if not current.empty else 0.0
    savings_rate = float(current.iloc[0]["savings_rate"]) if not current.empty else 0.0

    by_category = spending_by_category(conn, period_month).to_dict("records")

    budget_lines = generate_budget(conn, period_month)
    persist_budget(conn, period_month, budget_lines)
    bva = budget_vs_actual(conn, period_month).to_dict("records")

    nw_trend = net_worth_trend(conn)
    nw_change = net_worth_change(conn)
    current_net_worth = float(nw_trend.iloc[-1]["net_worth"]) if not nw_trend.empty else None

    debt_categories = repo.get_transactions_df(conn, period_month, period_month)
    debt_paid = 0.0
    if not debt_categories.empty:
        debt_rows = debt_categories[(debt_categories["category"] == "Debt") & (debt_categories["direction"] == "expense")]
        debt_paid = float(debt_rows["amount"].abs().sum())

    investment_rows = repo.get_transactions_df(conn, period_month, period_month)
    invested = 0.0
    if not investment_rows.empty:
        inv = investment_rows[(investment_rows["category"] == "Investments") & (investment_rows["direction"] == "expense")]
        invested = float(inv["amount"].abs().sum())

    detected_subs = detect_subscriptions(conn)
    persist_subscriptions(conn, detected_subs)

    goals = [g.__dict__ for g in all_goals_progress(conn)]
    salary_changes = [c.__dict__ for c in highlight_changes(conn) if c.period_month == period_month]
    health = compute_health_score(conn, period_month, monthly_debt_payment=debt_paid)
    alerts = evaluate_alerts(conn, period_month)

    recommendations = _build_recommendations(bva, health, detected_subs, savings_rate)

    payload = {
        "period_month": period_month,
        "generated_at": date.today().isoformat(),
        "income": round(income, 2),
        "expenses": round(expenses, 2),
        "net_cashflow": round(net_cashflow, 2),
        "savings_rate": round(savings_rate, 4),
        "spending_by_category": by_category,
        "largest_purchases": _largest_transactions(conn, period_month, "expense"),
        "largest_savings_contributions": _largest_transactions(conn, period_month, "income"),
        "net_worth": current_net_worth,
        "net_worth_change": nw_change,
        "debt_paid_this_month": round(debt_paid, 2),
        "invested_this_month": round(invested, 2),
        "budget_performance": bva,
        "subscriptions": [s.__dict__ for s in detected_subs],
        "subscription_monthly_total": total_monthly_subscription_cost(detected_subs),
        "goals": goals,
        "salary_changes": salary_changes,
        "financial_health_score": {"total": health.total, "components": health.components},
        "alerts": alerts,
        "recommendations": recommendations,
    }

    repo.save_review(conn, "monthly", period_month, json.dumps(payload, default=str))
    return payload


def _build_recommendations(bva, health, detected_subs, savings_rate) -> list[str]:
    recs: list[str] = []
    if savings_rate < 0.20:
        recs.append(
            f"Savings rate is {savings_rate:.1%}, below the 20% target. Look at the top overspent categories below."
        )
    over_budget = [row for row in bva if row.get("pct_used") and row["pct_used"] > 1.0]
    for row in sorted(over_budget, key=lambda r: r["variance"])[:3]:
        recs.append(
            f"{row['category']} is €{abs(row['variance']):,.2f} over budget this month — review recent charges."
        )
    stale_subs = [s for s in detected_subs if s.recommend_cancel]
    for s in stale_subs[:3]:
        recs.append(f"Consider cancelling '{s.label}' (€{s.monthly_cost:,.2f}/mo): {s.reason}")
    if health.total < 60:
        weakest = min(health.components.items(), key=lambda kv: kv[1]["score"])
        recs.append(f"Financial health score is {health.total}/100. Weakest area: {weakest[0]} — {weakest[1]['detail']}.")
    if not recs:
        recs.append("No major issues detected this month — keep it up.")
    return recs
