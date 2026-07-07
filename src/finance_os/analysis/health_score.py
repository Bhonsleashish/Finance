"""Composite financial health score (0-100), combining five weighted
sub-scores. Every sub-score and the final weighted result are returned so
the reasoning is fully transparent (never a bare number)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from finance_os.analysis.budgeting import budget_vs_actual
from finance_os.analysis.cashflow import monthly_summary
from finance_os.analysis.goals import emergency_fund_status
from finance_os.config import load_settings
from finance_os.db import repository as repo


@dataclass
class HealthScore:
    total: float
    components: dict[str, dict]  # name -> {"score": 0-100, "weight": pts, "weighted": pts, "detail": str}


def _score_savings_rate(rate: float) -> float:
    # 20%+ savings rate = full marks; 0% or negative = 0.
    return max(0.0, min(rate / 0.20, 1.0)) * 100


def _score_emergency_fund(months_covered: float, target_months: int) -> float:
    return max(0.0, min(months_covered / target_months, 1.0)) * 100 if target_months else 0.0


def _score_debt_to_income(monthly_debt_payment: float, monthly_income: float) -> float:
    if monthly_income <= 0:
        return 50.0
    ratio = monthly_debt_payment / monthly_income
    # 0% DTI = 100, 36%+ DTI (common lending threshold) = 0.
    return max(0.0, min(1.0 - ratio / 0.36, 1.0)) * 100


def _score_budget_adherence(conn: sqlite3.Connection, period_month: str) -> float:
    bva = budget_vs_actual(conn, period_month)
    if bva.empty or bva["budgeted_amount"].sum() == 0:
        return 50.0  # neutral, no budget set yet
    within_budget = bva[bva["pct_used"].fillna(0) <= 1.0]
    return (len(within_budget) / len(bva)) * 100


def _score_spending_stability(conn: sqlite3.Connection) -> float:
    summary = monthly_summary(conn)
    if len(summary) < 2:
        return 50.0
    recent = summary.tail(6)
    mean_expense = recent["expenses"].mean()
    if mean_expense == 0:
        return 100.0
    std_expense = recent["expenses"].std() or 0.0
    coefficient_of_variation = std_expense / mean_expense
    # Lower volatility = higher score. CoV of 0 -> 100, CoV of 0.5+ -> 0.
    return max(0.0, min(1.0 - coefficient_of_variation / 0.5, 1.0)) * 100


def compute_health_score(conn: sqlite3.Connection, period_month: str, monthly_debt_payment: float = 0.0) -> HealthScore:
    settings = load_settings()
    weights = settings.get("health_score", "weights", default={
        "savings_rate": 30, "emergency_fund_coverage": 25, "debt_to_income": 20,
        "budget_adherence": 15, "spending_stability": 10,
    })
    target_months = settings.get("emergency_fund", "target_months_of_expenses", default=6)

    summary = monthly_summary(conn, end_month=period_month)
    latest = summary[summary["period_month"] == period_month]
    savings_rate = float(latest.iloc[0]["savings_rate"]) if not latest.empty else 0.0
    avg_expenses = float(summary.tail(6)["expenses"].mean()) if not summary.empty else 0.0
    monthly_income = float(latest.iloc[0]["income"]) if not latest.empty else 0.0

    ef = emergency_fund_status(conn, target_months, avg_expenses)

    scores = {
        "savings_rate": (_score_savings_rate(savings_rate), f"Savings rate this month: {savings_rate:.1%}"),
        "emergency_fund_coverage": (
            _score_emergency_fund(ef["months_covered"], target_months),
            f"Emergency fund covers {ef['months_covered']:.1f} of {target_months} target months",
        ),
        "debt_to_income": (
            _score_debt_to_income(monthly_debt_payment, monthly_income),
            f"Debt payments are {(monthly_debt_payment / monthly_income):.1%} of income" if monthly_income else "No income data",
        ),
        "budget_adherence": (
            _score_budget_adherence(conn, period_month),
            "Share of categories that stayed within budget",
        ),
        "spending_stability": (
            _score_spending_stability(conn),
            "Consistency of monthly spending over the last 6 months",
        ),
    }

    components = {}
    total_weighted = 0.0
    total_weight = sum(weights.values()) or 1
    for name, (score, detail) in scores.items():
        weight = weights.get(name, 0)
        weighted = score * weight / total_weight
        components[name] = {"score": round(score, 1), "weight": weight, "weighted": round(weighted, 1), "detail": detail}
        total_weighted += weighted

    return HealthScore(total=round(total_weighted, 1), components=components)
