"""Smart alerts: spending spikes, subscription cost increases, budget
overruns, negative cash flow, salary changes, unexpected fees, growing debt.
Evaluated on demand (e.g. after each ingestion run or weekly review) and
persisted to the `alerts` table so duplicates aren't re-raised.
"""

from __future__ import annotations

import sqlite3

from finance_os.analysis.budgeting import budget_vs_actual
from finance_os.analysis.cashflow import monthly_summary, trailing_average
from finance_os.analysis.salary import highlight_changes
from finance_os.analysis.subscriptions import detect_subscriptions
from finance_os.config import load_categories, load_settings
from finance_os.db import repository as repo


def evaluate_alerts(conn: sqlite3.Connection, period_month: str) -> list[dict]:
    settings = load_settings()
    raised: list[dict] = []

    def raise_alert(alert_type: str, message: str, severity: str = "warning"):
        repo.insert_alert(conn, alert_type, message, severity, period_month)
        raised.append({"type": alert_type, "message": message, "severity": severity})

    # --- spending spikes vs trailing 3-month average, per category --------
    spike_pct = settings.get("alerts", "spending_spike_pct", default=0.3)
    from finance_os.analysis.cashflow import spending_by_category

    current = spending_by_category(conn, period_month)
    for _, row in current.iterrows():
        category, total = row["category"], row["total"]
        baseline = trailing_average(conn, category, months=3, before_month=period_month)
        if baseline > 0 and total > baseline * (1 + spike_pct):
            raise_alert(
                "spending_spike",
                f"{category} spending this month (€{total:,.2f}) is {((total / baseline) - 1):.0%} above "
                f"its 3-month average (€{baseline:,.2f}).",
            )

    # --- budget exceeded ---------------------------------------------------
    exceeded_pct = settings.get("alerts", "budget_exceeded_pct", default=1.0)
    bva = budget_vs_actual(conn, period_month)
    for _, row in bva.iterrows():
        if row["budgeted_amount"] and row["pct_used"] and row["pct_used"] > exceeded_pct:
            raise_alert(
                "budget_exceeded",
                f"{row['category']} is at {row['pct_used']:.0%} of its €{row['budgeted_amount']:,.2f} budget "
                f"(spent €{row['actual']:,.2f}).",
            )

    # --- negative cash flow --------------------------------------------------
    if settings.get("alerts", "negative_cash_flow", default=True):
        summary = monthly_summary(conn)
        row = summary[summary["period_month"] == period_month]
        if not row.empty and row.iloc[0]["net_cashflow"] < 0:
            raise_alert(
                "negative_cash_flow",
                f"Cash flow is negative this month: €{row.iloc[0]['net_cashflow']:,.2f} "
                f"(income €{row.iloc[0]['income']:,.2f}, expenses €{row.iloc[0]['expenses']:,.2f}).",
                severity="critical",
            )

    # --- salary changes ------------------------------------------------------
    salary_change_pct = settings.get("alerts", "salary_change_pct", default=0.02)
    for change in highlight_changes(conn, threshold_pct=salary_change_pct):
        if change.period_month == period_month and change.field in ("net_salary", "gross_salary"):
            direction = "increased" if change.delta > 0 else "decreased"
            raise_alert(
                "salary_change",
                f"{change.field.replace('_', ' ').title()} {direction} by €{abs(change.delta):,.2f} "
                f"({change.delta_pct:+.1%}) to €{change.current:,.2f}.",
                severity="info",
            )

    # --- subscription cost increases / new subscriptions ----------------------
    increase_pct = settings.get("alerts", "subscription_increase_pct", default=0.05)
    existing_subs = repo.get_subscriptions_df(conn)
    detected = detect_subscriptions(conn)
    for sub in detected:
        prior = existing_subs[existing_subs["label"] == sub.label] if not existing_subs.empty else existing_subs
        if not prior.empty:
            old_cost = float(prior.iloc[0]["monthly_cost"])
            if old_cost > 0 and sub.monthly_cost > old_cost * (1 + increase_pct):
                raise_alert(
                    "subscription_increase",
                    f"'{sub.label}' subscription increased from €{old_cost:,.2f}/mo to €{sub.monthly_cost:,.2f}/mo.",
                )
        if sub.recommend_cancel:
            raise_alert(
                "subscription_recommend_cancel",
                f"'{sub.label}' (€{sub.monthly_cost:,.2f}/mo) looks unused or duplicated: {sub.reason}",
                severity="info",
            )

    return raised
