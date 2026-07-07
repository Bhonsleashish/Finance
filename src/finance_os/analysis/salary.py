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


def average_net_income(conn: sqlite3.Connection, last_n_months: int = 3) -> float:
    df = get_salary_history(conn)
    if df.empty:
        return 0.0
    recent = df.sort_values("period_month").tail(last_n_months)
    return float(recent["net_salary"].dropna().mean() or 0.0)
