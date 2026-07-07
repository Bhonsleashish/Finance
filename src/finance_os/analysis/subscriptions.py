"""Recurring-subscription detection: groups transactions by merchant (or
normalized description when no merchant was matched), looks at the gaps
between charges and their amounts, and flags anything that repeats on a
roughly-fixed interval as a subscription. Also flags duplicates (two active
subscriptions in the same category doing the same job, e.g. two music
streaming services) and staleness (no charge in a long time -> recommend
cancellation, since the user probably forgot about it).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from finance_os.config import load_settings
from finance_os.db import repository as repo


@dataclass
class DetectedSubscription:
    label: str
    merchant_id: int | None
    category: str | None
    monthly_cost: float
    interval_days: int
    first_seen: date
    last_seen: date
    occurrences: int
    is_stale: bool
    recommend_cancel: bool
    reason: str = ""


def detect_subscriptions(conn: sqlite3.Connection) -> list[DetectedSubscription]:
    settings = load_settings()
    interval_tolerance = settings.get("subscriptions", "interval_days_tolerance", default=4)
    min_occurrences = settings.get("subscriptions", "min_occurrences", default=2)
    amount_tolerance_pct = settings.get("subscriptions", "amount_tolerance_pct", default=0.1)
    stale_after_days = settings.get("subscriptions", "stale_after_days", default=45)

    df = repo.get_transactions_df(conn)
    if df.empty:
        return []
    expenses = df[df["direction"] == "expense"].copy()
    expenses["amount_abs"] = expenses["amount"].abs()
    expenses["group_key"] = expenses["merchant"].fillna(expenses["description_raw"].str.lower().str.strip())

    detected: list[DetectedSubscription] = []
    today = date.today()

    for key, group in expenses.groupby("group_key"):
        if len(group) < min_occurrences:
            continue
        group = group.sort_values("txn_date")
        dates = group["txn_date"].dt.date.tolist()
        amounts = group["amount_abs"].tolist()
        gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
        if not gaps:
            continue
        avg_gap = sum(gaps) / len(gaps)
        # A subscription must recur roughly monthly-ish (weekly to yearly)
        if not (5 <= avg_gap <= 370):
            continue
        gap_consistent = all(abs(g - avg_gap) <= interval_tolerance + avg_gap * 0.15 for g in gaps)
        avg_amount = sum(amounts) / len(amounts)
        amount_consistent = all(abs(a - avg_amount) <= avg_amount * amount_tolerance_pct + 0.01 for a in amounts)
        if not (gap_consistent and amount_consistent):
            continue

        last_seen = dates[-1]
        is_stale = (today - last_seen).days > stale_after_days
        monthly_cost = avg_amount * (30.44 / avg_gap)
        category = group["category"].dropna().iloc[-1] if group["category"].notna().any() else None

        detected.append(DetectedSubscription(
            label=str(key),
            merchant_id=None,
            category=category,
            monthly_cost=round(monthly_cost, 2),
            interval_days=round(avg_gap),
            first_seen=dates[0],
            last_seen=last_seen,
            occurrences=len(dates),
            is_stale=is_stale,
            recommend_cancel=is_stale,
            reason="No charge in over %d days" % stale_after_days if is_stale else "",
        ))

    _flag_duplicates(detected)
    return sorted(detected, key=lambda s: s.monthly_cost, reverse=True)


def _flag_duplicates(subs: list[DetectedSubscription]) -> None:
    by_category: dict[str, list[DetectedSubscription]] = {}
    for s in subs:
        if s.category:
            by_category.setdefault(s.category, []).append(s)
    for category, group in by_category.items():
        if category in ("Subscriptions", "Entertainment") and len(group) > 1:
            for s in group:
                if not s.recommend_cancel:
                    s.recommend_cancel = True
                    s.reason = f"Possible duplicate: {len(group)} active subscriptions in '{category}'"


def persist_subscriptions(conn: sqlite3.Connection, detected: list[DetectedSubscription]) -> None:
    for sub in detected:
        status = "stale" if sub.is_stale else "active"
        repo.upsert_subscription(
            conn, sub.merchant_id, sub.label, sub.monthly_cost, sub.interval_days,
            sub.first_seen.isoformat(), sub.last_seen.isoformat(), sub.occurrences,
            recommend_cancel=sub.recommend_cancel, status=status,
        )


def total_monthly_subscription_cost(detected: list[DetectedSubscription]) -> float:
    return round(sum(s.monthly_cost for s in detected if not s.is_stale), 2)
