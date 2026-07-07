"""Best-effort extraction of merchant / date / total from receipts, invoices
and screenshots (after OCR). Heuristic, line-oriented — designed to hand off
a sane default to the categorizer, with the user able to correct it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from finance_os.utils.dates import parse_german_amount, parse_german_date

TOTAL_LABEL_PATTERN = re.compile(
    r"(gesamt(betrag)?|summe|total|zu\s*zahlen|endbetrag|rechnungsbetrag|betrag)\s*[:\-]?\s*"
    r"(-?\d{1,3}(?:\.\d{3})*,\d{2})",
    re.IGNORECASE,
)
DATE_PATTERN = re.compile(r"\d{2}\.\d{2}\.\d{2,4}")


@dataclass
class ParsedReceipt:
    merchant_guess: str | None
    txn_date: date | None
    amount: float | None
    raw_text: str


def parse_receipt_text(text: str) -> ParsedReceipt:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    merchant_guess = lines[0] if lines else None

    amount = None
    for line in reversed(lines):  # totals are usually near the bottom
        m = TOTAL_LABEL_PATTERN.search(line)
        if m:
            amount = parse_german_amount(m.group(3))
            break

    txn_date = None
    for line in lines:
        m = DATE_PATTERN.search(line)
        if m:
            txn_date = parse_german_date(m.group(0))
            if txn_date:
                break

    return ParsedReceipt(merchant_guess=merchant_guess, txn_date=txn_date, amount=amount, raw_text=text)
