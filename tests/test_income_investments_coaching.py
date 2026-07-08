from __future__ import annotations

from finance_os.analysis.coaching import STARTER_EMERGENCY_FUND, money_management_tips
from finance_os.analysis.investments import portfolio_summary
from finance_os.analysis.salary import estimate_month_income
from finance_os.db import repository as repo


def test_estimate_income_uses_confirmed_payslip_when_available(db_conn):
    repo.upsert_salary_slip(db_conn, "2026-03", employer="Acme GmbH", gross_salary=4500.0, net_salary=2900.0)
    db_conn.commit()
    est = estimate_month_income(db_conn, "2026-03")
    assert est.basis == "confirmed_payslip"
    assert est.estimated_total == 2900.0
    assert est.remaining_expected == 2900.0  # nothing received yet as a transaction


def test_estimate_income_falls_back_to_payslip_average(db_conn):
    for month in ("2026-01", "2026-02"):
        repo.upsert_salary_slip(db_conn, month, employer="Acme GmbH", gross_salary=4500.0, net_salary=2900.0)
    db_conn.commit()
    est = estimate_month_income(db_conn, "2026-03")  # no payslip for March yet
    assert est.basis == "average_of_last_3_payslips"
    assert est.estimated_total == 2900.0


def test_estimate_income_received_so_far_reduces_remaining(db_conn):
    repo.upsert_salary_slip(db_conn, "2026-03", employer="Acme GmbH", gross_salary=4500.0, net_salary=2900.0)
    repo.insert_transaction(db_conn, txn_date="2026-03-05", description_raw="Gehalt", amount=2900.0, direction="income")
    db_conn.commit()
    est = estimate_month_income(db_conn, "2026-03")
    assert est.received_so_far == 2900.0
    assert est.remaining_expected == 0.0


def test_investment_add_and_portfolio_summary_at_cost(db_conn):
    repo.add_investment(db_conn, "VWCE", "2026-01-15", 1000.0, asset_type="etf")
    repo.add_investment(db_conn, "Bitcoin", "2026-02-01", 500.0, asset_type="crypto", current_value=600.0)
    db_conn.commit()
    summary = portfolio_summary(db_conn)
    assert summary.holdings_count == 2
    assert summary.total_invested == 1500.0
    assert summary.total_current_value == 1600.0  # VWCE at cost (1000) + Bitcoin updated (600)
    assert summary.unrealized_gain == 100.0
    assert summary.stale_value_count == 1  # VWCE never had its value updated


def test_investment_delete_removes_holding(db_conn):
    inv_id = repo.add_investment(db_conn, "VWCE", "2026-01-15", 1000.0)
    db_conn.commit()
    assert repo.delete_investment(db_conn, inv_id) is True
    summary = portfolio_summary(db_conn)
    assert summary.holdings_count == 0


def test_coaching_prioritizes_starter_emergency_fund_when_empty(db_conn):
    repo.upsert_salary_slip(db_conn, "2026-01", employer="Acme GmbH", net_salary=2900.0, gross_salary=4500.0)
    repo.insert_transaction(db_conn, txn_date="2026-01-05", description_raw="Gehalt", amount=2900.0, direction="income")
    repo.insert_transaction(db_conn, txn_date="2026-01-06", description_raw="REWE", amount=-100.0, direction="expense")
    db_conn.commit()
    tips = money_management_tips(db_conn, "2026-01")
    assert tips[0].priority == 1
    assert "starter emergency fund" in tips[0].title.lower()


def test_coaching_cold_start_returns_generic_tips(db_conn):
    tips = money_management_tips(db_conn)
    assert len(tips) >= 3
    assert tips[0].priority == 1
