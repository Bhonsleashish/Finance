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

# Synthetic fixture modeled on a real N26-style export (fake name/IBAN/
# amounts) — trailing "DD.MM.YYYY +/-amount€" block terminator, a repeating
# page header/footer between pages, and a bank-assigned category tag
# ("Business Mastercard • Lebensmittel") on each card transaction.
N26_STYLE_SAMPLE = """
MAX MUSTERMANN
Musterstraße 1, 10115 Berlin
IBAN: DE00000000000000000000 • BIC: NTSBDEB1XXX
Erstellt am
08.07.2026
Nr. 01/2026
1 / 2
Beschreibung Verbuchungsdatum Betrag
N26
N26 Cashback
Wertstellung 01.01.2026
01.01.2026 +0,55€
REWE Jens Heimbrod
Business Mastercard • Lebensmittel
Wertstellung 01.01.2026
01.01.2026 -5,38€
Employer GmbH
Gutschriften
IBAN: DE11111111111111111111 • BIC: TESTDEFFXXX
Salary January
Wertstellung 02.01.2026
02.01.2026 +2900,00€
Uniqlo Berlin
Business Mastercard • Shopping
Wertstellung 03.01.2026
03.01.2026 -25,90€
MAX MUSTERMANN
Musterstraße 1, 10115 Berlin
IBAN: DE00000000000000000000 • BIC: NTSBDEB1XXX
Erstellt am
08.07.2026
Nr. 01/2026
2 / 2
Beschreibung Verbuchungsdatum Betrag
GESOBAU AG
Lastschriften
IBAN: DE22222222222222222222 • BIC: BELADEBEXXX
1003358699MIETE 01/2026
Wertstellung 04.01.2026
04.01.2026 -654,50€
Zusammenfassung Nr. 01/2026
01.01.2026 bis 31.01.2026

Beschreibung
Dein alter Kontostand +135,65€
Dein neuer Kontostand +2.150,42€
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


def test_n26_style_trailing_amount_layout_extracts_all_transactions():
    txns = parse_statement_text(N26_STYLE_SAMPLE)
    amounts = sorted(t.amount for t in txns)
    assert amounts == [-654.50, -25.90, -5.38, 0.55, 2900.00]
    assert len(txns) == 5


def test_n26_style_layout_strips_page_boilerplate_from_descriptions():
    txns = parse_statement_text(N26_STYLE_SAMPLE)
    all_descriptions = " ".join(t.description for t in txns)
    # None of the repeating header/footer content should leak into any description.
    assert "MUSTERMANN" not in all_descriptions
    assert "Erstellt am" not in all_descriptions
    assert "IBAN:" not in all_descriptions
    assert "Beschreibung" not in all_descriptions


def test_n26_style_layout_recovers_real_merchant_descriptions():
    txns = parse_statement_text(N26_STYLE_SAMPLE)
    rewe = next(t for t in txns if t.amount == -5.38)
    assert "REWE Jens Heimbrod" in rewe.description
    rent = next(t for t in txns if t.amount == -654.50)
    assert "GESOBAU" in rent.description
    assert "MIETE" in rent.description.upper()


def test_n26_style_layout_extracts_bank_category_hint():
    txns = parse_statement_text(N26_STYLE_SAMPLE)
    uniqlo = next(t for t in txns if t.amount == -25.90)
    assert uniqlo.category_hint == "Shopping"
    rewe = next(t for t in txns if t.amount == -5.38)
    assert rewe.category_hint == "Groceries"
    # Transactions with no "X • Y" tag line (salary, cashback, rent) have no hint.
    salary = next(t for t in txns if t.amount == 2900.00)
    assert salary.category_hint is None


def test_summary_page_produces_no_phantom_transactions():
    txns = parse_statement_text(N26_STYLE_SAMPLE)
    # "Dein alter Kontostand +135,65€" etc. have no leading date, so they
    # must never be mistaken for a transaction.
    assert not any(abs(t.amount) == 135.65 for t in txns)
    assert not any(abs(t.amount) == 2150.42 for t in txns)
