from pathlib import Path

from finance_os.ingest.bank_statement_parser import parse_statement_text
from finance_os.ingest.csv_importer import parse_csv

STATEMENT_SAMPLE = """
Kontoauszug Januar 2026

05.01.2026 REWE SAGT DANKE
Kartenzahlung
-45,30

06.01.2026 Netflix.com Mitgliedschaft
-12,99

07.01.2026 Gehalt Musterfirma GmbH
2.920,20
"""


def test_parse_statement_text_extracts_transactions():
    txns = parse_statement_text(STATEMENT_SAMPLE)
    assert len(txns) == 3
    assert txns[0].amount == -45.30
    assert "REWE" in txns[0].description
    assert txns[2].amount == 2920.20


def test_parse_csv_semicolon_delimited(tmp_path: Path):
    csv_path = tmp_path / "statement.csv"
    csv_path.write_text(
        "Buchungstag;Verwendungszweck;Betrag\n"
        "05.01.2026;REWE SAGT DANKE;-45,30\n"
        "07.01.2026;Gehalt Musterfirma GmbH;2920,20\n",
        encoding="utf-8",
    )
    txns = parse_csv(csv_path)
    assert len(txns) == 2
    assert txns[0].amount == -45.30
    assert txns[1].amount == 2920.20
