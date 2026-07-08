"""Best-effort extraction of a purchase from a broker screenshot/confirmation
(after OCR). Broker apps (Trade Republic, Scalable Capital, DEGIRO,
Comdirect, ...) vary wildly in layout, so this is intentionally conservative:
it looks for a total amount and a purchase date using the same heuristics as
receipts, plus a name guess from the first line. Every result from this
parser is routed to `documents.status = 'needs_review'` by the ingestion
pipeline — treat it as a draft to confirm/correct, not a trusted entry.
The reliable path is `finance investment add` or the Investments dashboard
page, where you type the numbers yourself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from finance_os.ingest.receipt_parser import DATE_PATTERN, TOTAL_LABEL_PATTERN
from finance_os.utils.dates import parse_german_amount, parse_german_date

BROKER_HINTS = ["trade republic", "scalable capital", "degiro", "comdirect", "consorsbank",
                "ing depot", "flatex", "justtrade", "smartbroker", "coinbase", "binance"]


@dataclass
class ParsedInvestment:
    name_guess: str | None
    broker_guess: str | None
    purchase_date: date | None
    amount: float | None
    raw_text: str


def parse_investment_text(text: str) -> ParsedInvestment:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    lowered = text.lower()

    broker_guess = next((b.title() for b in BROKER_HINTS if b in lowered), None)

    amount = None
    for line in reversed(lines):
        m = TOTAL_LABEL_PATTERN.search(line)
        if m:
            amount = parse_german_amount(m.group(3))
            break

    purchase_date = None
    for line in lines:
        m = DATE_PATTERN.search(line)
        if m:
            purchase_date = parse_german_date(m.group(0))
            if purchase_date:
                break

    name_guess = lines[0] if lines else None

    return ParsedInvestment(name_guess=name_guess, broker_guess=broker_guess,
                             purchase_date=purchase_date, amount=amount, raw_text=text)
