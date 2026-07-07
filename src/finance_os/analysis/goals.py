"""Goal tracking: emergency fund, debt payoff, vacation, custom targets, with
completion-date estimation based on each goal's committed monthly
contribution (falling back to a supplied average if none is set)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

import pandas as pd
from dateutil.relativedelta import relativedelta

from finance_os.db import repository as repo


@dataclass
class GoalProgress:
    name: str
    goal_type: str
    target_amount: float
    current_amount: float
    monthly_contribution: float
    progress_pct: float
    remaining_amount: float
    estimated_months_remaining: float | None
    estimated_completion_date: date | None
    user_target_date: date | None
    on_track: bool | None


def create_or_update_goal(conn: sqlite3.Connection, name: str, goal_type: str, target_amount: float, current_amount: float = 0.0, monthly_contribution: float = 0.0, target_date: str | None = None, notes: str | None = None) -> int:
    return repo.upsert_goal(conn, name, goal_type, target_amount, current_amount, monthly_contribution, target_date, notes)


def record_contribution(conn: sqlite3.Connection, goal_name: str, amount: float, contributed_on: str) -> None:
    goals = repo.list_goals(conn)
    row = goals[goals["name"] == goal_name]
    if row.empty:
        raise ValueError(f"Unknown goal: {goal_name}")
    repo.contribute_to_goal(conn, int(row.iloc[0]["id"]), amount, contributed_on)


def _estimate_completion(target: float, current: float, monthly_rate: float) -> tuple[float | None, date | None]:
    remaining = max(target - current, 0.0)
    if remaining == 0:
        return 0.0, date.today()
    if monthly_rate <= 0:
        return None, None
    months = remaining / monthly_rate
    completion = date.today() + relativedelta(months=int(months) + (1 if months % 1 > 0 else 0))
    return months, completion


def all_goals_progress(conn: sqlite3.Connection, fallback_monthly_rate: float = 0.0) -> list[GoalProgress]:
    goals = repo.list_goals(conn)
    results: list[GoalProgress] = []
    for _, g in goals.iterrows():
        monthly_rate = g["monthly_contribution"] or fallback_monthly_rate
        months_remaining, completion = _estimate_completion(g["target_amount"], g["current_amount"], monthly_rate)
        progress_pct = min(g["current_amount"] / g["target_amount"], 1.0) if g["target_amount"] else 0.0
        user_target = pd.to_datetime(g["target_date"]).date() if pd.notna(g["target_date"]) and g["target_date"] else None
        on_track = None
        if user_target and completion:
            on_track = completion <= user_target
        results.append(GoalProgress(
            name=g["name"], goal_type=g["goal_type"], target_amount=g["target_amount"],
            current_amount=g["current_amount"], monthly_contribution=monthly_rate,
            progress_pct=round(progress_pct, 4), remaining_amount=max(g["target_amount"] - g["current_amount"], 0.0),
            estimated_months_remaining=months_remaining, estimated_completion_date=completion,
            user_target_date=user_target, on_track=on_track,
        ))
    return results


def emergency_fund_status(conn: sqlite3.Connection, target_months_of_expenses: int, avg_monthly_expenses: float) -> dict:
    goals = repo.list_goals(conn)
    ef = goals[goals["goal_type"] == "emergency_fund"]
    target_amount = avg_monthly_expenses * target_months_of_expenses
    current = float(ef.iloc[0]["current_amount"]) if not ef.empty else 0.0
    months_covered = (current / avg_monthly_expenses) if avg_monthly_expenses else 0.0
    return {
        "target_amount": round(target_amount, 2),
        "current_amount": round(current, 2),
        "months_covered": round(months_covered, 2),
        "target_months": target_months_of_expenses,
        "fully_funded": current >= target_amount,
    }
