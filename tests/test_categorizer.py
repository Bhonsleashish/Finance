from finance_os.categorize.categorizer import Categorizer
from finance_os.db import repository as repo


def test_known_merchant_matches_exact_pattern(db_conn):
    cat = Categorizer(db_conn)
    result = cat.categorize("REWE SAGT DANKE 12345")
    assert result.category_name == "Groceries"
    assert result.merchant_name == "REWE"
    assert result.confidence == "merchant_exact"


def test_unknown_text_falls_back_to_miscellaneous(db_conn):
    cat = Categorizer(db_conn)
    result = cat.categorize("XYZQ RANDOM UNKNOWN PAYEE 998877")
    assert result.category_name == "Miscellaneous"
    assert result.confidence == "fallback"


def test_keyword_match_when_no_merchant_pattern(db_conn):
    cat = Categorizer(db_conn)
    result = cat.categorize("Miete Wohnung Januar")
    assert result.category_name == "Housing"
    assert result.confidence == "keyword"


def test_learning_from_correction_persists_and_applies_next_time(db_conn):
    cat = Categorizer(db_conn)
    txn_id = repo.insert_transaction(
        db_conn, txn_date="2026-01-10", description_raw="Bobs Cornerstore Berlin",
        amount=-20.0, direction="expense",
    )
    cat.learn_correction(txn_id, "Bobs Cornerstore Berlin", "Groceries")
    db_conn.commit()

    cat2 = Categorizer(db_conn)  # fresh instance re-reads from DB
    result = cat2.categorize("Bobs Cornerstore Berlin")
    assert result.category_name == "Groceries"
    assert result.confidence == "merchant_exact"
