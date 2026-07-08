"""Money-management coaching: a rule-based priority ladder (the standard
personal-finance order of operations — starter emergency fund, then
high-interest debt, then a full emergency fund, then investing) applied to
your actual numbers, plus evergreen tips when there isn't much data yet.

Every tip explains *why*, with the calculation behind it where one exists —
this is meant to read like advice from an advisor, not a canned quote list.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from finance_os.analysis.budgeting import budget_vs_actual
from finance_os.analysis.cashflow import monthly_summary
from finance_os.analysis.goals import emergency_fund_status
from finance_os.analysis.investments import portfolio_summary
from finance_os.analysis.salary import highlight_changes
from finance_os.analysis.subscriptions import detect_subscriptions, total_monthly_subscription_cost
from finance_os.config import load_settings
from finance_os.db import repository as repo
from finance_os.utils.dates import current_period_month

STARTER_EMERGENCY_FUND = 1000.0  # a conventional "starter" buffer before other priorities


@dataclass
class Tip:
    priority: int  # 1 = most important
    title: str
    detail: str


def money_management_tips(conn: sqlite3.Connection, period_month: str | None = None) -> list[Tip]:
    period_month = period_month or current_period_month()
    settings = load_settings()
    target_months = settings.get("emergency_fund", "target_months_of_expenses", default=6)

    summary = monthly_summary(conn)
    tips: list[Tip] = []

    if summary.empty:
        return _cold_start_tips()

    avg_expenses = float(summary.tail(6)["expenses"].mean())
    avg_income = float(summary.tail(6)["income"].mean())
    ef = emergency_fund_status(conn, target_months, avg_expenses)

    has_debt_activity = False
    df = repo.get_transactions_df(conn)
    debt_monthly = 0.0
    if not df.empty:
        debt_rows = df[(df["category"] == "Debt") & (df["direction"] == "expense")]
        has_debt_activity = not debt_rows.empty
        if has_debt_activity:
            debt_monthly = float(debt_rows.groupby("period_month")["amount"].sum().abs().tail(3).mean())

    # 1. Starter emergency fund first — before anything else, even debt payoff,
    #    so a small surprise expense doesn't force you back onto a credit card.
    if ef["current_amount"] < STARTER_EMERGENCY_FUND:
        gap = STARTER_EMERGENCY_FUND - ef["current_amount"]
        have_clause = "no" if ef["current_amount"] == 0 else f"only EUR {ef['current_amount']:,.2f} of"
        tips.append(Tip(
            1, "Build a starter emergency fund first",
            f"You have {have_clause} emergency fund. Before anything else — even extra debt payments — "
            f"get EUR {gap:,.2f} more saved (a EUR {STARTER_EMERGENCY_FUND:,.0f} starter buffer) so a surprise "
            f"bill doesn't become new debt.",
        ))

    # 2. High-interest debt beats almost everything except the starter fund.
    if has_debt_activity:
        tips.append(Tip(
            2, "Prioritize high-interest debt over extra saving/investing",
            f"You're paying roughly EUR {debt_monthly:,.2f}/month toward debt. Credit card and consumer-loan "
            f"interest (often 10-20%/yr in Germany) usually beats any safe return you'd get by saving or "
            f"investing that same money instead — pay it down aggressively once the starter fund is in place.",
        ))

    # 3. Full emergency fund (once starter + high-interest debt are handled).
    if ef["current_amount"] >= STARTER_EMERGENCY_FUND and not ef["fully_funded"]:
        tips.append(Tip(
            3, f"Finish your {target_months}-month emergency fund",
            f"You're at {ef['months_covered']:.1f} of {target_months} target months "
            f"(EUR {ef['current_amount']:,.2f} of EUR {ef['target_amount']:,.2f}, based on your "
            f"EUR {avg_expenses:,.2f}/month average spending). Keep funding this before increasing investments.",
        ))

    # 4. Once the emergency fund is full and there's no debt drag, flag idle cash.
    portfolio = portfolio_summary(conn)
    if ef["fully_funded"] and not has_debt_activity and portfolio.holdings_count == 0:
        tips.append(Tip(
            4, "Put your surplus to work",
            "Your emergency fund is funded and you have no debt showing up in your transactions, but no "
            "investments are recorded yet. Money sitting in a checking account loses purchasing power to "
            "inflation — consider a low-cost diversified ETF for long-term goals once you're comfortable.",
        ))

    # 5. Savings rate below the 20% target.
    latest = summary[summary["period_month"] == period_month]
    savings_rate = float(latest.iloc[0]["savings_rate"]) if not latest.empty else None
    if savings_rate is not None and savings_rate < 0.20:
        tips.append(Tip(
            5, "Savings rate is below the 20% target",
            f"This month's savings rate is {savings_rate:.1%} (income EUR {avg_income:,.2f}/mo average). "
            f"Automating a transfer to savings on payday — before you see the money in checking — is the "
            f"single most reliable way to raise this.",
        ))

    # 6. Subscription bloat.
    subs = detect_subscriptions(conn)
    stale = [s for s in subs if s.recommend_cancel]
    if stale:
        total_stale = round(sum(s.monthly_cost for s in stale), 2)
        tips.append(Tip(
            6, "Cancel unused or duplicate subscriptions",
            f"{len(stale)} subscription(s) look unused or duplicated, totalling EUR {total_stale:,.2f}/month "
            f"(EUR {total_stale * 12:,.2f}/year). See the Subscriptions page for which ones.",
        ))

    # 7. Lifestyle inflation: income growing faster than it's being kept.
    changes = [c for c in highlight_changes(conn) if c.field == "net_salary" and c.delta > 0]
    if changes and savings_rate is not None:
        last_raise = changes[-1]
        if savings_rate < 0.20:
            tips.append(Tip(
                7, "Watch for lifestyle inflation after your raise",
                f"Net salary increased by EUR {last_raise.delta:,.2f} ({last_raise.delta_pct:+.1%}) in "
                f"{last_raise.period_month}, but your savings rate is still {savings_rate:.1%}. Try directing "
                f"most of a raise straight to savings/investing before your spending adjusts to match it.",
            ))

    # 8. Budget adherence.
    bva = budget_vs_actual(conn, period_month)
    if not bva.empty:
        over = bva[bva["pct_used"].fillna(0) > 1.0]
        if len(over) >= 2:
            tips.append(Tip(
                8, "Several categories are over budget",
                f"{len(over)} categories are over their adaptive budget this month "
                f"({', '.join(over['category'].tolist()[:4])}). Check `finance budget status` for the full list.",
            ))

    if not tips:
        tips.append(Tip(1, "You're in good shape", (
            "Emergency fund funded, no debt drag detected, savings rate on target, and no subscription bloat "
            "found. Keep reviewing weekly/monthly and revisit your goals as income changes."
        )))

    return sorted(tips, key=lambda t: t.priority)


def _cold_start_tips() -> list[Tip]:
    return [
        Tip(1, "Start with a starter emergency fund",
            f"Before anything else, save EUR {STARTER_EMERGENCY_FUND:,.0f} as a buffer against surprise expenses "
            f"— this is the standard first step before debt payoff or investing."),
        Tip(2, "Pay off high-interest debt before investing",
            "Credit cards and consumer loans in Germany often run 10-20%/yr interest — that beats almost any "
            "safe investment return, so it comes before extra saving or investing (after the starter fund)."),
        Tip(3, "Automate savings on payday",
            "Set up a standing order that moves money to savings the day you're paid, before you see it in "
            "checking. What you never see, you don't spend."),
        Tip(4, "Track everything for a month before optimizing",
            "Run `finance ingest` on a month of bank statements/CSVs (or add manual entries) so the budgeting "
            "and coaching tips here start reflecting your actual numbers instead of generic advice."),
        Tip(5, "Once the emergency fund is full, invest for the long term",
            "A low-cost, diversified ETF is a reasonable default for money you won't need for 5+ years — "
            "log purchases on the Investments page so this app can track your allocation and returns."),
    ]
