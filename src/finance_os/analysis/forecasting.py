"""Forward-looking projections: bank balance, savings, cash flow, debt
payoff, emergency fund completion, over 1/3/6/12/60-month horizons.

Method: simple linear trend on trailing monthly net cash flow (ordinary
least squares via numpy.polyfit on the last N months, N = min(12, history)).
This is intentionally transparent and explainable — every number the
forecaster produces can be traced back to "average monthly net cash flow
over the last N months, projected forward" rather than a black-box model.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

from finance_os.analysis.cashflow import monthly_summary
from finance_os.analysis.networth import latest_net_worth

HORIZONS_MONTHS = {"1_month": 1, "3_months": 3, "6_months": 6, "1_year": 12, "5_years": 60}


def _trend_monthly_cashflow(conn: sqlite3.Connection, lookback_months: int = 12) -> tuple[float, float]:
    """Returns (average_monthly_net_cashflow, linear_trend_slope_per_month)."""
    summary = monthly_summary(conn)
    if summary.empty:
        return 0.0, 0.0
    recent = summary.sort_values("period_month").tail(lookback_months)
    values = recent["net_cashflow"].to_numpy()
    if len(values) == 1:
        return float(values[0]), 0.0
    x = np.arange(len(values))
    slope, intercept = np.polyfit(x, values, 1)
    avg = float(values.mean())
    return avg, float(slope)


def forecast_balance(conn: sqlite3.Connection, current_balance: float) -> dict[str, float]:
    avg, slope = _trend_monthly_cashflow(conn)
    projections = {}
    for label, months in HORIZONS_MONTHS.items():
        # Project using average cash flow plus half the observed trend (a
        # damped trend, so we don't extrapolate a single volatile month
        # aggressively out to 5 years).
        projected = current_balance + sum(avg + slope * 0.5 * i for i in range(1, months + 1))
        projections[label] = round(projected, 2)
    return projections


def forecast_savings(conn: sqlite3.Connection, current_savings: float) -> dict[str, float]:
    summary = monthly_summary(conn)
    if summary.empty:
        return {label: current_savings for label in HORIZONS_MONTHS}
    avg_savings_rate = summary.tail(6)["savings_rate"].mean()
    avg_income = summary.tail(6)["income"].mean()
    monthly_savings = avg_income * max(avg_savings_rate, 0.0)
    return {
        label: round(current_savings + monthly_savings * months, 2)
        for label, months in HORIZONS_MONTHS.items()
    }


def forecast_debt_payoff(current_debt: float, monthly_payment: float) -> dict:
    if monthly_payment <= 0 or current_debt <= 0:
        return {"months_remaining": None, "payoff_date": None}
    months = current_debt / monthly_payment
    payoff_date = pd.Timestamp.today().date() + relativedelta(months=int(months) + (1 if months % 1 > 0 else 0))
    return {"months_remaining": round(months, 1), "payoff_date": payoff_date.isoformat()}


def forecast_emergency_fund_completion(current_amount: float, target_amount: float, monthly_contribution: float) -> dict:
    remaining = max(target_amount - current_amount, 0.0)
    if remaining == 0:
        return {"months_remaining": 0, "completion_date": pd.Timestamp.today().date().isoformat()}
    if monthly_contribution <= 0:
        return {"months_remaining": None, "completion_date": None}
    months = remaining / monthly_contribution
    completion_date = pd.Timestamp.today().date() + relativedelta(months=int(months) + (1 if months % 1 > 0 else 0))
    return {"months_remaining": round(months, 1), "completion_date": completion_date.isoformat()}


def full_trajectory_report(conn: sqlite3.Connection, current_balance: float, current_net_worth: float | None = None) -> dict:
    current_net_worth = current_net_worth if current_net_worth is not None else (latest_net_worth(conn) or current_balance)
    avg, slope = _trend_monthly_cashflow(conn)
    net_worth_projection = {
        label: round(current_net_worth + sum(avg + slope * 0.5 * i for i in range(1, months + 1)), 2)
        for label, months in HORIZONS_MONTHS.items()
    }
    return {
        "avg_monthly_cashflow": round(avg, 2),
        "trend_slope_per_month": round(slope, 2),
        "balance_projection": forecast_balance(conn, current_balance),
        "net_worth_projection": net_worth_projection,
    }
