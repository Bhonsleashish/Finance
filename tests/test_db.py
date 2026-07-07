from finance_os.db import repository as repo


def test_init_seeds_categories_and_merchants(db_conn):
    categories = db_conn.execute("SELECT COUNT(*) AS n FROM categories").fetchone()["n"]
    merchants = db_conn.execute("SELECT COUNT(*) AS n FROM merchants").fetchone()["n"]
    assert categories > 10
    assert merchants > 10


def test_insert_transaction_deduplicates(db_conn):
    first = repo.insert_transaction(
        db_conn, txn_date="2026-01-01", description_raw="Test Merchant", amount=-10.0, direction="expense",
    )
    duplicate = repo.insert_transaction(
        db_conn, txn_date="2026-01-01", description_raw="Test Merchant", amount=-10.0, direction="expense",
    )
    assert first is not None
    assert duplicate is None
    count = db_conn.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()["n"]
    assert count == 1


def test_upsert_salary_slip_updates_existing_row(db_conn):
    repo.upsert_salary_slip(db_conn, "2026-01", employer="Acme GmbH", gross_salary=4000.0, net_salary=2600.0)
    repo.upsert_salary_slip(db_conn, "2026-01", employer="Acme GmbH", gross_salary=4200.0, net_salary=2700.0)
    df = repo.get_salary_slips_df(db_conn)
    assert len(df) == 1
    assert df.iloc[0]["gross_salary"] == 4200.0


def test_goal_contribution_updates_current_amount(db_conn):
    goal_id = repo.upsert_goal(db_conn, "Emergency Fund", "emergency_fund", target_amount=10000, current_amount=0)
    repo.contribute_to_goal(db_conn, goal_id, 500.0, "2026-01-15")
    goals = repo.list_goals(db_conn)
    assert goals.iloc[0]["current_amount"] == 500.0
