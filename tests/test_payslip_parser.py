from finance_os.ingest.payslip_parser import parse_payslip_text

SAMPLE = """
Musterfirma GmbH
Abrechnung fuer Januar 2026
Abrechnungszeitraum: 01/2026

Gesamt-Brutto                 4.500,00
Lohnsteuer                      612,50
Solidaritaetszuschlag             10,20
Kirchensteuer                    49,00
Krankenversicherung             350,10
Rentenversicherung              418,50
Arbeitslosenversicherung         58,50
Pflegeversicherung               81,00
Ueberstunden                     120,00
Auszahlungsbetrag              2.920,20
"""


def test_parses_period_and_employer():
    result = parse_payslip_text(SAMPLE)
    assert result.period_month == "2026-01"
    assert result.employer == "Musterfirma GmbH"


def test_parses_all_expected_fields():
    result = parse_payslip_text(SAMPLE)
    assert result.fields["gross_salary"] == 4500.0
    assert result.fields["net_salary"] == 2920.2
    assert result.fields["income_tax"] == 612.5
    assert result.fields["solidarity_surcharge"] == 10.2
    assert result.fields["church_tax"] == 49.0
    assert result.fields["health_insurance"] == 350.1
    assert result.fields["pension_insurance"] == 418.5
    assert result.fields["unemployment_insurance"] == 58.5
    assert result.fields["nursing_care_insurance"] == 81.0
    assert result.fields["overtime_pay"] == 120.0
    assert not result.needs_review


def test_sparse_payslip_flags_needs_review():
    result = parse_payslip_text("Some random unrelated document with no payslip fields.")
    assert result.needs_review
    assert result.matched_field_count < 3


def test_as_db_fields_only_contains_known_columns():
    result = parse_payslip_text(SAMPLE)
    db_fields = result.as_db_fields()
    assert "gross_salary" in db_fields
    assert "employer" not in db_fields  # employer is passed separately, not a "field"
