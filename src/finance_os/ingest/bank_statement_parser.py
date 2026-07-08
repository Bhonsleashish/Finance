"""Parsers for German bank-statement PDFs. Two distinct layouts are common
enough to support explicitly, tried in this order:

1. **Trailing date+amount** (N26, and similar modern "card style" exports):
   each transaction is a short block — merchant name, a category/type line,
   optional IBAN/BIC, optional notes — terminated by its own
   "Wertstellung DD.MM.YYYY" line followed by a line that is *just*
   "DD.MM.YYYY ±amount€". Nothing else shares that exact shape, so it's a
   reliable block terminator. These statements also repeat a page
   header/footer (account holder name/address, "Erstellt am", page number,
   column headers) between every page's worth of transactions, which is
   stripped out via `_strip_page_boilerplate` rather than parsed as content.

2. **Leading date** (traditional statements — Sparkasse, Commerzbank, DKB,
   ...): each transaction starts with a line beginning "DD.MM.YYYY ...",
   and everything up to the next such line (including a trailing amount) is
   one transaction.

`parse_statement_text` tries (1) first since its block terminator is
unambiguous; if that finds nothing, it falls back to (2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from finance_os.utils.dates import parse_german_amount, parse_german_date

LINE_START_DATE = re.compile(r"^(\d{2}\.\d{2}\.(?:\d{4}|\d{2}))\s+(.*)")
TRAILING_AMOUNT = re.compile(r"(-?\d{1,3}(?:\.\d{3})*,\d{2}-?)\s*(?:EUR|€)?\s*$")

TRAILER_LINE = re.compile(r"^\d{2}\.\d{2}\.\d{2,4}\s+([+-]?\d+(?:\.\d{3})*,\d{2})\s*€?\s*$")
VALUE_DATE_LINE = re.compile(r"^Wertstellung\s+\d{2}\.\d{2}\.\d{4}$", re.IGNORECASE)
IBAN_BIC_LINE = re.compile(r"^IBAN:.*BIC:", re.IGNORECASE)
BANK_CATEGORY_TAG = re.compile(r"\s•\s(.+)$")  # "Business Mastercard • Lebensmittel" -> "Lebensmittel"

# Statement-generation boilerplate ("Erstellt am ...", account holder name/
# address, page number, column headers) repeats between every page. It has
# no fixed wording we can rely on for the name/address itself, but it's
# reliably *bounded*: it starts at "Erstellt am" and ends at the next
# column-header line starting with "Beschreibung". Everything in between
# is discarded rather than parsed as transaction content.
BOILERPLATE_START = re.compile(r"^Erstellt am$", re.IGNORECASE)
BOILERPLATE_END = re.compile(r"^Beschreibung\b", re.IGNORECASE)

# Bank-assigned category tags (from the "Business Mastercard • X" line) map
# loosely onto our own categories — used only as a fallback hint when
# merchant/keyword matching can't place a transaction on its own.
BANK_CATEGORY_HINTS = {
    "lebensmittel": "Groceries",
    "transport": "Transportation",
    "auto": "Transportation",
    "gesundheit & drogerien": "Healthcare",
    "bars & restaurants": "Restaurants",
    "shopping": "Shopping",
    "wohnen & energie": "Shopping",
}


@dataclass
class ParsedTransaction:
    txn_date: date
    description: str
    amount: float
    category_hint: str | None = None


def parse_statement_text(text: str, statement_year_hint: int | None = None) -> list[ParsedTransaction]:
    trailing = _parse_trailing_date_amount_format(text)
    if trailing:
        return trailing
    return _parse_leading_date_format(text)


def _parse_trailing_date_amount_format(text: str) -> list[ParsedTransaction]:
    lines = [ln.strip() for ln in text.splitlines()]
    transactions: list[ParsedTransaction] = []
    block: list[str] = []
    in_boilerplate = False

    for line in lines:
        if not line:
            continue

        if in_boilerplate:
            if BOILERPLATE_END.match(line):
                in_boilerplate = False
            continue

        if BOILERPLATE_START.match(line):
            block = []  # whatever was accumulating (name/address) was boilerplate too
            in_boilerplate = True
            continue

        trailer = TRAILER_LINE.match(line)
        if trailer:
            date_str = line.split()[0]
            txn_date = parse_german_date(date_str)
            amount = parse_german_amount(trailer.group(1))
            if txn_date is not None and amount is not None:
                transactions.append(_build_transaction(txn_date, amount, block))
            block = []
            continue

        if VALUE_DATE_LINE.match(line) or IBAN_BIC_LINE.match(line):
            continue

        block.append(line)

    return transactions


def _build_transaction(txn_date: date, amount: float, block_lines: list[str]) -> ParsedTransaction:
    category_hint = None
    for line in block_lines:
        m = BANK_CATEGORY_TAG.search(line)
        if m:
            category_hint = BANK_CATEGORY_HINTS.get(m.group(1).strip().lower())
    description = " ".join(block_lines).strip() or "(no description)"
    return ParsedTransaction(txn_date=txn_date, description=description, amount=amount, category_hint=category_hint)


def _parse_leading_date_format(text: str) -> list[ParsedTransaction]:
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
