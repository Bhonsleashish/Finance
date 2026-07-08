from __future__ import annotations

from pathlib import Path

import pytest

from finance_os.categorize.categorizer import Categorizer
from finance_os.db import repository as repo
from finance_os.ingest.ingest_pipeline import _handle_text_document, guess_doc_type, ingest_path

PAYSLIP_TEXT = """
Musterfirma GmbH
Abrechnung fuer Maerz 2026
Abrechnungszeitraum: 03/2026

Gesamt-Brutto                 4.500,00
Lohnsteuer                      612,50
Krankenversicherung             350,10
Auszahlungsbetrag              2.920,20
"""

STATEMENT_TEXT = """
05.03.2026 REWE SAGT DANKE
-45,30

06.03.2026 Netflix.com
-12,99
"""


def test_guess_doc_type_defaults_to_receipt_for_unrecognized_pdf(tmp_path: Path):
    misnamed = tmp_path / "random_name.pdf"
    misnamed.write_bytes(b"%PDF-1.4 fake")
    assert guess_doc_type(misnamed) == "receipt"


def test_explicit_doc_type_overrides_guess_for_misplaced_payslip(db_conn, tmp_path: Path):
    """A payslip that isn't sitting in data/salary_slips/ would otherwise be
    guessed as a generic receipt and fail to extract any salary fields —
    forcing doc_type='payslip' (as the CLI --type flag / dashboard Upload
    page do) must route it through the real payslip parser regardless of
    where the file lives or what it's named.
    """
    misnamed = tmp_path / "random_name.pdf"
    misnamed.write_bytes(b"placeholder")  # content doesn't matter; we call the text handler directly below

    categorizer = Categorizer(db_conn)
    result = _handle_text_document(db_conn, misnamed, "somehash1", "payslip", PAYSLIP_TEXT, "native_text", categorizer)

    assert result.doc_type == "payslip"
    assert result.status == "imported"

    salary = repo.get_salary_slips_df(db_conn)
    assert len(salary) == 1
    assert salary.iloc[0]["period_month"] == "2026-03"
    assert salary.iloc[0]["net_salary"] == 2920.2


def test_explicit_doc_type_bank_statement_via_text_handler(db_conn, tmp_path: Path):
    """Same shared code path handles bank statements too — this is what
    lets an OCR'd screenshot of a bank statement (not just a PDF) be
    correctly parsed, since both funnel through _handle_text_document."""
    path = tmp_path / "screenshot.png"
    categorizer = Categorizer(db_conn)
    result = _handle_text_document(db_conn, path, "somehash2", "bank_statement", STATEMENT_TEXT, "ocr", categorizer)

    assert result.doc_type == "bank_statement"
    assert result.transactions_added == 2

    txns = repo.get_transactions_df(db_conn)
    assert len(txns) == 2
    assert set(txns["category"]) == {"Groceries", "Subscriptions"}


def test_ingest_path_rejects_doc_type_override_on_a_directory(db_conn, tmp_path: Path):
    (tmp_path / "a.pdf").write_bytes(b"placeholder")
    with pytest.raises(ValueError):
        ingest_path(db_conn, tmp_path, doc_type="payslip")
