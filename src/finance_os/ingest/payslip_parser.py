"""Parser for German salary slips (Gehaltsabrechnung / Lohnabrechnung / Verdienstabrechnung).

German payslips do not follow one single layout (DATEV, SAP, Personio, Lexware,
sBüro and in-house templates all differ), so this parser works line-by-line
against a table of label regex patterns rather than assuming fixed
coordinates. Every payslip you feed it that fails to extract a field cleanly
should have its label added to `FIELD_PATTERNS` below — that's the intended
extension point.

Confidence: if fewer than `MIN_FIELDS_FOR_CONFIDENCE` fields are found, the
result is flagged `needs_review=True` so the ingestion pipeline routes it to
the documents.status = 'needs_review' bucket instead of silently trusting it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from finance_os.utils.dates import GERMAN_MONTHS, parse_german_amount

MIN_FIELDS_FOR_CONFIDENCE = 3

# Order matters only for employer/period heuristics; field patterns are
# tried independently per line. Each pattern's first capture group (if any)
# is ignored — we always take the last German-formatted number on the line.
FIELD_PATTERNS: dict[str, list[str]] = {
    "gross_salary": [r"gesamt-?brutto", r"^brutto\b", r"steuerbrutto", r"bruttoentgelt", r"bruttolohn"],
    "net_salary": [r"auszahlungsbetrag", r"netto-?verdienst", r"^netto\b", r"nettoentgelt", r"überweisungsbetrag", r"ueberweisungsbetrag"],
    "income_tax": [r"lohnsteuer(?!.*kirche)", r"lst\b"],
    "solidarity_surcharge": [r"solidarit(ä|ae)tszuschlag", r"\bsolz\b"],
    "church_tax": [r"kirchensteuer", r"\bkist\b"],
    "health_insurance": [r"krankenversicherung", r"\bkv\b(?!\w)"],
    "pension_insurance": [r"rentenversicherung", r"\brv\b(?!\w)"],
    "unemployment_insurance": [r"arbeitslosenversicherung", r"\balv\b"],
    "nursing_care_insurance": [r"pflegeversicherung", r"\bpv\b(?!\w)"],
    "overtime_pay": [r"überstunden", r"ueberstunden", r"mehrarbeit"],
    "bonus": [r"\bbonus\b", r"prämie", r"praemie", r"gratifikation", r"sonderzahlung"],
    "reimbursements": [r"erstattung", r"auslagen", r"spesen", r"fahrtkosten(erstattung)?"],
}

EMPLOYER_HINT_PATTERN = re.compile(
    r"^([A-ZÄÖÜ][\w&.\-\s]{2,60}\b(?:GmbH|AG|KG|GmbH\s?&\s?Co\.?\s?KG|SE|OHG|UG|mbH|e\.V\.))",
)

PERIOD_LABEL_PATTERN = re.compile(
    r"(abrechnungs(?:zeitraum|monat)|für\s+(?:den\s+)?monat|entgeltabrechnung\s+für)\s*[:\-]?\s*"
    r"(\d{1,2})[./](\d{4})",
    re.IGNORECASE,
)
PERIOD_TEXT_MONTH_PATTERN = re.compile(
    r"\b([A-Za-zäöüÄÖÜ]+)\s+(\d{4})\b"
)

AMOUNT_ON_LINE = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2}-?")


@dataclass
class ParsedPayslip:
    period_month: str | None = None
    employer: str | None = None
    fields: dict[str, float] = field(default_factory=dict)
    matched_field_count: int = 0
    needs_review: bool = True
    raw_text: str = ""

    def as_db_fields(self) -> dict:
        return {k: self.fields.get(k) for k in FIELD_PATTERNS}


def _extract_last_amount(line: str) -> float | None:
    matches = AMOUNT_ON_LINE.findall(line)
    if not matches:
        return None
    return parse_german_amount(matches[-1])


def _guess_employer(lines: list[str]) -> str | None:
    for line in lines[:15]:
        m = EMPLOYER_HINT_PATTERN.search(line.strip())
        if m:
            return m.group(1).strip()
    # Fallback: explicit "Arbeitgeber:" label
    for line in lines:
        if "arbeitgeber" in line.lower():
            parts = line.split(":", 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
    return None


def _guess_period(lines: list[str], text: str) -> str | None:
    m = PERIOD_LABEL_PATTERN.search(text)
    if m:
        month, year = int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"
    for line in lines[:20]:
        m2 = PERIOD_TEXT_MONTH_PATTERN.search(line)
        if m2:
            month_name, year = m2.group(1).lower(), int(m2.group(2))
            month_num = GERMAN_MONTHS.get(month_name)
            if month_num:
                return f"{year:04d}-{month_num:02d}"
    return None


def parse_payslip_text(text: str) -> ParsedPayslip:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    result = ParsedPayslip(raw_text=text)

    result.employer = _guess_employer(lines)
    result.period_month = _guess_period(lines, text)

    for line in lines:
        lowered = line.lower()
        for db_field, patterns in FIELD_PATTERNS.items():
            if db_field in result.fields:
                continue
            for pattern in patterns:
                if re.search(pattern, lowered):
                    amount = _extract_last_amount(line)
                    if amount is not None:
                        result.fields[db_field] = abs(amount) if db_field == "gross_salary" or db_field == "net_salary" else amount
                    break

    result.matched_field_count = len(result.fields)
    result.needs_review = result.matched_field_count < MIN_FIELDS_FOR_CONFIDENCE or not result.period_month
    return result
