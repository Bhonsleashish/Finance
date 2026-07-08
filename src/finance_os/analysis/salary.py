"""Month-over-month German payslip analysis: diffs, highlighted changes."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pandas as pd

from finance_os.db import repository as repo

TRACKED_FIELDS = [
    "gross_salary", "net_salary", "income_tax", "solidarity_surcharge", "church_tax",
    "health_insurance", "pension_insurance", "unemployment_insurance", "nursing_care_insurance",
    "overtime_pay", "bonus", "reimbursements",
]

SIGNIFICANT_CHANGE_PCT = 0.02  # 2%


@dataclass
class SalaryChange:
    period_month: str
    field: str
    previous: float
    current: float
    delta: float
    delta_pct: float | None


def get_salary_history(conn: sqlite3.Connection) -> pd.DataFrame:
    return repo.get_salary_slips_df(conn)


def month_over_month(conn: sqlite3.Connection) -> pd.DataFrame:
    df = get_salary_history(conn)
    if df.empty:
        return df
    df = df.sort_values("period_month").reset_index(drop=True)
    for field_name in TRACKED_FIELDS:
        df[f"{field_name}_delta"] = df[field_name].diff()
        df[f"{field_name}_delta_pct"] = df[field_name].pct_change()
    return df


def highlight_changes(conn: sqlite3.Connection, threshold_pct: float = SIGNIFICANT_CHANGE_PCT) -> list[SalaryChange]:
    df = get_salary_history(conn)
    if df.empty or len(df) < 2:
        return []
    df = df.sort_values("period_month").reset_index(drop=True)
    changes: list[SalaryChange] = []
    for i in range(1, len(df)):
        prev_row, cur_row = df.iloc[i - 1], df.iloc[i]
        for field_name in TRACKED_FIELDS:
            prev_val, cur_val = prev_row.get(field_name), cur_row.get(field_name)
            if pd.isna(prev_val) or pd.isna(cur_val):
                continue
            delta = cur_val - prev_val
            delta_pct = (delta / prev_val) if prev_val else None
            if delta_pct is not None and abs(delta_pct) >= threshold_pct:
                changes.append(SalaryChange(
                    period_month=cur_row["period_month"], field=field_name,
                    previous=prev_val, current=cur_val, delta=delta, delta_pct=delta_pct,
                ))
    return changes


def latest_net_income(conn: sqlite3.Connection) -> float:
    df = get_salary_history(conn)
    if df.empty:
        return 0.0
    latest = df.sort_values("period_month").iloc[-1]
    return float(latest.get("net_salary") or 0.0)


def average_net_income(conn: sqlite3.Connection, last_n_months: int = 3, before_month: str | None = None) -> float:
    df = get_salary_history(conn)
    if df.empty:
        return 0.0
    df = df.sort_values("period_month")
    if before_month:
        df = df[df["period_month"] < before_month]
    recent = df.tail(last_n_months)
    return float(recent["net_salary"].dropna().mean() or 0.0)


def has_payslip_for_month(conn: sqlite3.Connection, period_month: str) -> bool:
    df = get_salary_history(conn)
    return not df.empty and (df["period_month"] == period_month).any()


def net_salary_for_month(conn: sqlite3.Connection, period_month: str) -> float:
    df = get_salary_history(conn)
    if df.empty:
        return 0.0
    matches = df[df["period_month"] == period_month]
    if matches.empty:
        return 0.0
    return float(matches["net_salary"].dropna().sum())


@dataclass
class IncomeEstimate:
    period_month: str
    received_so_far: float
    estimated_total: float
    remaining_expected: float
    basis: str


def estimate_month_income(conn: sqlite3.Connection, period_month: str | None = None) -> IncomeEstimate:
    """Estimate total income for a month, combining what's already landed in
    the transaction ledger with a projection for the rest:
      1. If a payslip has been parsed for this month, that net salary is the
         estimated total (the most reliable source we have).
      2. Otherwise, use the average net salary from the last 3 parsed
         payslips before this month.
      3. If no payslips exist at all yet, fall back to the average total
         income seen in the transaction ledger over the last 3 months.
    `basis` always says which of these was used, so the number is never a
    black box.
    """
    from finance_os.analysis.cashflow import monthly_summary
    from finance_os.db import repository as repo
    from finance_os.utils.dates import current_period_month

    period_month = period_month or current_period_month()

    txn_df = repo.get_transactions_df(conn, period_month, period_month)
    received_so_far = float(txn_df[txn_df["direction"] == "income"]["amount"].sum()) if not txn_df.empty else 0.0

    if has_payslip_for_month(conn, period_month):
        estimated_total = net_salary_for_month(conn, period_month)
        basis = "confirmed_payslip"
    else:
        avg_payslip = average_net_income(conn, last_n_months=3, before_month=period_month)
        if avg_payslip:
            estimated_total = avg_payslip
            basis = "average_of_last_3_payslips"
        else:
            summary = monthly_summary(conn)
            history = summary[summary["period_month"] < period_month] if not summary.empty else summary
            avg_txn_income = float(history.tail(3)["income"].mean()) if not history.empty else 0.0
            estimated_total = avg_txn_income
            basis = "average_of_last_3_months_transactions" if avg_txn_income else "no_history_yet"

    estimated_total = max(estimated_total, received_so_far)
    remaining_expected = max(estimated_total - received_so_far, 0.0)

    return IncomeEstimate(
        period_month=period_month,
        received_so_far=round(received_so_far, 2),
        estimated_total=round(estimated_total, 2),
        remaining_expected=round(remaining_expected, 2),
        basis=basis,
    )
