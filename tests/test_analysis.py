from __future__ import annotations

import sqlite3

from finance_os.analysis.advisor import evaluate_purchase
from finance_os.analysis.budgeting import budget_vs_actual, generate_budget, persist_budget
from finance_os.analysis.cashflow import monthly_summary
from finance_os.analysis.forecasting import forecast_balance
from finance_os.analysis.subscriptions import detect_subscriptions
from finance_os.categorize.categorizer import Categorizer
from finance_os.db import repository as repo


def _seed_months(conn: sqlite3.Connection, categorizer: Categorizer) -> None:
    """Three months of salary + recurring Netflix/REWE spending."""
    for i, month in enumerate(["2026-01", "2026-02", "2026-03"]):
        repo.upsert_salary_slip(conn, month, employer="Acme GmbH", gross_salary=4500.0, net_salary=2900.0)
        day = f"{month}-05"
        cat = categorizer.categorize("Gehalt Acme GmbH")
        repo.insert_transaction(
            conn, txn_date=day, description_raw="Gehalt Acme GmbH", amount=2900.0,
            direction="income", category_id=cat.category_id, account_name="checking",
        )
        rewe_cat = categorizer.categorize("REWE SAGT DANKE")
        repo.insert_transaction(
            conn, txn_date=f"{month}-06", description_raw="REWE SAGT DANKE", amount=-50.0 - i,
            direction="expense", merchant_id=rewe_cat.merchant_id, category_id=rewe_cat.category_id, account_name="checking",
        )
        netflix_cat = categorizer.categorize("Netflix.com")
        repo.insert_transaction(
            conn, txn_date=f"{month}-10", description_raw="Netflix.com", amount=-12.99,
            direction="expense", merchant_id=netflix_cat.merchant_id, category_id=netflix_cat.category_id, account_name="checking",
        )
    conn.commit()


def test_generate_budget_uses_income_and_recent_actuals(db_conn):
    categorizer = Categorizer(db_conn)
    _seed_months(db_conn, categorizer)
    lines = generate_budget(db_conn, "2026-03")
    persist_budget(db_conn, "2026-03", lines)
    groceries = next(l for l in lines if l.category == "Groceries")
    subscriptions = next(l for l in lines if l.category == "Subscriptions")
    assert groceries.budgeted_amount > 0
    assert subscriptions.budgeted_amount > 0

    bva = budget_vs_actual(db_conn, "2026-03")
    assert not bva.empty


def test_detect_subscriptions_finds_recurring_netflix(db_conn):
    categorizer = Categorizer(db_conn)
    _seed_months(db_conn, categorizer)
    detected = detect_subscriptions(db_conn)
    labels = [s.label for s in detected]
    assert "Netflix" in labels
    netflix = next(s for s in detected if s.label == "Netflix")
    assert 11 <= netflix.monthly_cost <= 14
    assert netflix.occurrences == 3


def test_forecast_balance_projects_positive_trend(db_conn):
    categorizer = Categorizer(db_conn)
    _seed_months(db_conn, categorizer)
    projections = forecast_balance(db_conn, current_balance=1000.0)
    assert projections["1_month"] > 1000.0
    assert projections["1_year"] > projections["1_month"]


def test_advisor_recommends_wait_or_avoid_when_no_history(db_conn):
    evaluation = evaluate_purchase(db_conn, "Fancy Watch", 2000.0)
    assert evaluation.recommendation in ("Wait", "Avoid")
    assert evaluation.reasons  # always explains itself


def test_advisor_buy_now_for_small_affordable_purchase(db_conn):
    categorizer = Categorizer(db_conn)
    _seed_months(db_conn, categorizer)
    # Fund the emergency fund goal so it doesn't block small purchases.
    repo.upsert_goal(db_conn, "Emergency Fund", "emergency_fund", target_amount=100.0, current_amount=100.0)
    lines = generate_budget(db_conn, "2026-03")
    persist_budget(db_conn, "2026-03", lines)
    db_conn.commit()
    evaluation = evaluate_purchase(db_conn, "Coffee", 4.0, period_month="2026-03")
    assert evaluation.recommendation == "Buy now"
