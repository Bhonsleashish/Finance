"""Adaptive monthly budgeting engine.

Unlike a static budget, this recomputes the plan every time it's asked,
using:
  - current income (trailing 3-month average net salary, so one bonus month
    doesn't blow up next month's budget)
  - fixed bills (their own trailing 3-month average — you don't get to
    "budget less" for rent, but growth there is flagged as an alert)
  - recent actual spending per flexible category, scaled to fit inside the
    needs/wants/savings target allocation from config.yaml
  - active goals: savings budget is never allowed to fall below the sum of
    committed monthly goal contributions (emergency fund, debt payoff, ...)

With little history (< min_history_months_for_adaptation) it falls back to
splitting the static target allocation evenly across each group's categories,
since there isn't enough signal yet to adapt to actual behavior.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pandas as pd

from finance_os.analysis.cashflow import monthly_summary, trailing_average
from finance_os.analysis.salary import average_net_income, latest_net_income
from finance_os.config import load_categories, load_settings
from finance_os.db import repository as repo

GROWTH_CAP = 1.15  # a flexible category's budget can't jump more than 15% above its own recent average


@dataclass
class BudgetLine:
    category: str
    group: str
    budgeted_amount: float
    basis: str  # 'fixed_actual' | 'scaled_flexible' | 'static_target' | 'goal_floor'


def _history_month_count(conn: sqlite3.Connection) -> int:
    summary = monthly_summary(conn)
    return len(summary)


def generate_budget(conn: sqlite3.Connection, period_month: str) -> list[BudgetLine]:
    settings = load_settings()
    categories = load_categories()
    fixed_categories = set(settings.get("budgeting", "fixed_categories", default=[]))
    target_alloc = settings.get("budgeting", "target_allocation", default={"needs": 0.5, "wants": 0.3, "savings": 0.2})
    min_history = settings.get("budgeting", "min_history_months_for_adaptation", default=2)

    income = average_net_income(conn, last_n_months=3) or latest_net_income(conn)
    if not income:
        # No parsed payslips yet — fall back to average monthly income seen
        # in the transaction ledger itself (e.g. salary deposits from a
        # bank statement/CSV import).
        recent_income = monthly_summary(conn).tail(3)
        if not recent_income.empty:
            income = float(recent_income["income"].mean())
    history_months = _history_month_count(conn)
    has_enough_history = history_months >= min_history and income > 0

    by_group: dict[str, list[str]] = {"needs": [], "wants": [], "savings": []}
    for name, meta in categories.items():
        group = meta.get("group", "wants") if isinstance(meta, dict) else "wants"
        if group in by_group:
            by_group[group].append(name)

    lines: list[BudgetLine] = []

    # --- needs & wants: adaptive scaling around actuals -----------------
    for group in ("needs", "wants"):
        group_categories = by_group[group]
        group_target = target_alloc.get(group, 0.0) * income

        if not has_enough_history or income == 0:
            if group_categories:
                even_split = (group_target / len(group_categories)) if income else 0.0
                for cat in group_categories:
                    lines.append(BudgetLine(cat, group, round(even_split, 2), "static_target"))
            continue

        actuals = {cat: trailing_average(conn, cat, months=3, before_month=period_month) for cat in group_categories}
        fixed_amount = sum(v for k, v in actuals.items() if k in fixed_categories)
        flexible = {k: v for k, v in actuals.items() if k not in fixed_categories}
        flexible_total = sum(flexible.values())
        remaining_for_flexible = max(group_target - fixed_amount, 0.0)

        flexible_categories = [c for c in group_categories if c not in fixed_categories]
        for cat in group_categories:
            if cat in fixed_categories:
                lines.append(BudgetLine(cat, group, round(actuals[cat], 2), "fixed_actual"))
            else:
                actual = flexible.get(cat, 0.0)
                if flexible_total > 0:
                    scaled = actual * (remaining_for_flexible / flexible_total)
                    capped = min(scaled, actual * GROWTH_CAP) if actual > 0 else scaled
                    amount = capped if actual > 0 else scaled
                elif flexible_categories:
                    # No spending history at all for this group's flexible
                    # categories: don't let the target allocation go
                    # unbudgeted, split it evenly as a starting point.
                    amount = remaining_for_flexible / len(flexible_categories)
                else:
                    amount = 0.0
                lines.append(BudgetLine(cat, group, round(max(amount, 0.0), 2), "scaled_flexible"))

    # --- savings: target allocation, floored by committed goal contributions
    savings_target = target_alloc.get("savings", 0.0) * income
    goals_df = repo.list_goals(conn)
    goal_floor = float(goals_df["monthly_contribution"].fillna(0).sum()) if not goals_df.empty else 0.0
    savings_categories = by_group["savings"] or ["Savings"]
    savings_amount = max(savings_target, goal_floor)
    if savings_categories:
        per_cat = savings_amount / len(savings_categories)
        for cat in savings_categories:
            basis = "goal_floor" if goal_floor > savings_target else "static_target"
            lines.append(BudgetLine(cat, "savings", round(per_cat, 2), basis))

    return lines


def persist_budget(conn: sqlite3.Connection, period_month: str, lines: list[BudgetLine]) -> None:
    for line in lines:
        category_id = repo.get_or_create_category(conn, line.category, line.group)
        repo.set_budget(conn, period_month, category_id, line.budgeted_amount, source="engine")


def budget_vs_actual(conn: sqlite3.Connection, period_month: str) -> pd.DataFrame:
    from finance_os.analysis.cashflow import spending_by_category

    budgets = repo.get_budgets_df(conn, period_month)
    actuals = spending_by_category(conn, period_month).rename(columns={"total": "actual"})
    if budgets.empty and actuals.empty:
        return pd.DataFrame(columns=["category", "budgeted_amount", "actual", "variance", "pct_used"])
    merged = pd.merge(budgets, actuals, on="category", how="outer").fillna(0.0)
    merged["variance"] = merged["budgeted_amount"] - merged["actual"]
    merged["pct_used"] = merged.apply(
        lambda r: (r["actual"] / r["budgeted_amount"]) if r["budgeted_amount"] else None, axis=1
    )
    return merged.sort_values("actual", ascending=False)
