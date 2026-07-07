"""Generic parser for German bank-statement PDFs (N26, ING, Sparkasse,
Commerzbank, DKB, ...). Statement layouts vary a lot, so this uses a
line-oriented heuristic: a transaction line starts with a date
(DD.MM.YYYY or DD.MM.) and ends with a German-formatted amount; everything
between is the description. Multi-line descriptions are merged into the
transaction that precedes them until the next date-prefixed line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from finance_os.utils.dates import parse_german_amount, parse_german_date

LINE_START_DATE = re.compile(r"^(\d{2}\.\d{2}\.(?:\d{4}|\d{2}))\s+(.*)")
TRAILING_AMOUNT = re.compile(r"(-?\d{1,3}(?:\.\d{3})*,\d{2}-?)\s*(?:EUR|€)?\s*$")


@dataclass
class ParsedTransaction:
    txn_date: date
    description: str
    amount: float


def parse_statement_text(text: str, statement_year_hint: int | None = None) -> list[ParsedTransaction]:
    lines = [ln.rstrip() for ln in text.splitlines()]
    transactions: list[ParsedTransaction] = []
    current: dict | None = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        m = LINE_START_DATE.match(stripped)
        if m:
            if current is not None:
                _finalize(current, transactions)
            date_str, rest = m.groups()
            parsed_date = parse_german_date(date_str)
            if parsed_date is None:
                current = None
                continue
            current = {"date": parsed_date, "desc_parts": [rest]}
        elif current is not None:
            current["desc_parts"].append(stripped)

    if current is not None:
        _finalize(current, transactions)

    return transactions


def _finalize(current: dict, out: list[ParsedTransaction]) -> None:
    full_text = " ".join(current["desc_parts"]).strip()
    amount_match = TRAILING_AMOUNT.search(full_text)
    if not amount_match:
        return
    amount = parse_german_amount(amount_match.group(1))
    if amount is None:
        return
    description = full_text[: amount_match.start()].strip(" -")
    if not description:
        description = "(no description)"
    out.append(ParsedTransaction(txn_date=current["date"], description=description, amount=amount))
