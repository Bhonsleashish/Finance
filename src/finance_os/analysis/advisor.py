"""Spending advisor: "I want to buy X for €Y" -> Buy now / Wait / Avoid,
with the arithmetic shown, not just an opinion.

Decision inputs:
  - Discretionary headroom: this month's (wants budget - wants spent so far)
  - Emergency fund status: fully funded or not
  - Goal delay: how many months a goal's completion date slips if this
    amount is diverted from savings
  - Opportunity cost: future value of the amount if invested instead,
    at config.advisor.assumed_investment_return, over a few horizons
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from finance_os.analysis.budgeting import budget_vs_actual, generate_budget
from finance_os.analysis.cashflow import monthly_summary
from finance_os.analysis.goals import all_goals_progress, emergency_fund_status
from finance_os.config import load_settings
from finance_os.db import repository as repo
from finance_os.utils.dates import current_period_month


@dataclass
class PurchaseEvaluation:
    item: str
    cost: float
    recommendation: str  # 'Buy now' | 'Wait' | 'Avoid'
    reasons: list[str] = field(default_factory=list)
    can_afford_this_month: bool = True
    emergency_fund_funded: bool = True
    discretionary_headroom: float = 0.0
    goal_delay_months: dict[str, float] = field(default_factory=dict)
    opportunity_cost: dict[str, float] = field(default_factory=dict)
    cheaper_alternative_hint: str = ""


def _future_value(amount: float, annual_return: float, years: float) -> float:
    return amount * ((1 + annual_return) ** years)


def evaluate_purchase(conn: sqlite3.Connection, item: str, cost: float, period_month: str | None = None) -> PurchaseEvaluation:
    settings = load_settings()
    period_month = period_month or current_period_month()
    large_threshold = settings.get("advisor", "large_purchase_threshold", default=150)
    assumed_return = settings.get("advisor", "assumed_investment_return", default=0.06)
    target_months = settings.get("emergency_fund", "target_months_of_expenses", default=6)

    reasons: list[str] = []

    # 1. Discretionary headroom this month
    bva = budget_vs_actual(conn, period_month)
    wants_rows = bva  # bva already merges budget+actual per category; filter to wants below
    from finance_os.config import load_categories

    categories = load_categories()
    wants_categories = {name for name, meta in categories.items() if meta.get("group") == "wants"}
    wants_bva = bva[bva["category"].isin(wants_categories)] if not bva.empty else bva
    wants_budgeted = float(wants_bva["budgeted_amount"].sum()) if not wants_bva.empty else 0.0
    wants_spent = float(wants_bva["actual"].sum()) if not wants_bva.empty else 0.0
    headroom = wants_budgeted - wants_spent
    can_afford = cost <= headroom

    reasons.append(
        f"Discretionary ('wants') budget this month: €{wants_budgeted:,.2f}, already spent €{wants_spent:,.2f}, "
        f"leaving €{headroom:,.2f} of headroom."
    )

    # 2. Emergency fund status
    summary = monthly_summary(conn)
    avg_expenses = float(summary.tail(6)["expenses"].mean()) if not summary.empty else 0.0
    ef = emergency_fund_status(conn, target_months, avg_expenses)
    if not ef["fully_funded"]:
        reasons.append(
            f"Emergency fund covers {ef['months_covered']:.1f} of {target_months} target months "
            f"(€{ef['current_amount']:,.2f} of €{ef['target_amount']:,.2f}) — not yet fully funded."
        )

    # 3. Goal delay: if this amount came out of savings, how much do goals slip?
    goal_delays: dict[str, float] = {}
    for g in all_goals_progress(conn):
        if g.monthly_contribution and g.monthly_contribution > 0:
            delay_months = cost / g.monthly_contribution
            if delay_months >= 0.1:
                goal_delays[g.name] = round(delay_months, 2)
                reasons.append(
                    f"Spending €{cost:,.2f} instead of contributing to '{g.name}' delays it by "
                    f"~{delay_months:.1f} month(s) at the current €{g.monthly_contribution:,.2f}/mo contribution."
                )

    # 4. Opportunity cost if invested instead
    opportunity_cost = {
        "5_years": round(_future_value(cost, assumed_return, 5) - cost, 2),
        "10_years": round(_future_value(cost, assumed_return, 10) - cost, 2),
        "20_years": round(_future_value(cost, assumed_return, 20) - cost, 2),
    }
    reasons.append(
        f"If invested instead at an assumed {assumed_return:.0%}/yr real return, €{cost:,.2f} would grow to "
        f"€{_future_value(cost, assumed_return, 10):,.2f} in 10 years "
        f"(+€{opportunity_cost['10_years']:,.2f})."
    )

    # --- Decision logic ----------------------------------------------------
    recommendation = "Buy now"
    if not ef["fully_funded"] and cost >= large_threshold:
        recommendation = "Wait"
        reasons.append("Recommendation driven by: emergency fund isn't fully funded yet and this is a large purchase.")
    elif not can_afford:
        recommendation = "Avoid" if cost > headroom * 2 else "Wait"
        reasons.append(f"Recommendation driven by: purchase exceeds this month's discretionary headroom by €{cost - headroom:,.2f}.")
    elif goal_delays and cost >= large_threshold:
        recommendation = "Wait"
        reasons.append("Recommendation driven by: purchase would meaningfully delay an active goal.")
    else:
        reasons.append("Recommendation driven by: within discretionary budget, emergency fund funded, no meaningful goal delay.")

    cheaper_hint = ""
    if recommendation != "Buy now":
        cheaper_hint = (
            "Consider: buying secondhand, waiting for a sale, or splitting the purchase across two months "
            "to stay within the discretionary budget."
        )

    return PurchaseEvaluation(
        item=item, cost=cost, recommendation=recommendation, reasons=reasons,
        can_afford_this_month=can_afford, emergency_fund_funded=ef["fully_funded"],
        discretionary_headroom=round(headroom, 2), goal_delay_months=goal_delays,
        opportunity_cost=opportunity_cost, cheaper_alternative_hint=cheaper_hint,
    )
