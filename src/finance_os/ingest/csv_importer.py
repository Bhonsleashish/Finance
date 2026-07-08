"""Import transactions from CSV exports (any bank). Auto-detects common
German/English column names; callers can pass an explicit `column_map` to
override detection for a bank whose headers don't match.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from finance_os.utils.dates import parse_german_amount, parse_german_date

DATE_COLUMN_CANDIDATES = ["date", "datum", "buchungstag", "buchungsdatum", "wertstellung", "valuta"]
DESC_COLUMN_CANDIDATES = [
    "description", "beschreibung", "verwendungszweck", "buchungstext", "empfänger",
    "empfaenger", "auftraggeber/empfänger", "zahlungsempfänger", "text",
]
AMOUNT_COLUMN_CANDIDATES = ["amount", "betrag", "umsatz", "value"]
DEBIT_COLUMN_CANDIDATES = ["debit", "soll", "belastung"]
CREDIT_COLUMN_CANDIDATES = ["credit", "haben", "gutschrift"]


@dataclass
class ParsedTransaction:
    txn_date: date
    description: str
    amount: float
    category_hint: str | None = None


def _find_column(columns: list[str], candidates: list[str]) -> str | None:
    lower_map = {c.lower().strip(): c for c in columns}
    for cand in candidates:
        if cand in lower_map:
            return lower_map[cand]
    for lower, original in lower_map.items():
        for cand in candidates:
            if cand in lower:
                return original
    return None


def _parse_date_cell(value) -> date | None:
    if pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.date()
    text = str(value).strip()
    parsed = parse_german_date(text)
    if parsed:
        return parsed
    try:
        return pd.to_datetime(text, dayfirst=True).date()
    except Exception:  # noqa: BLE001
        return None


def _parse_amount_cell(value) -> float | None:
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return parse_german_amount(str(value))


def parse_csv(path: Path, column_map: dict[str, str] | None = None, delimiter: str | None = None) -> list[ParsedTransaction]:
    df = pd.read_csv(path, sep=delimiter, engine="python", dtype=str)
    columns = list(df.columns)

    column_map = column_map or {}
    date_col = column_map.get("date") or _find_column(columns, DATE_COLUMN_CANDIDATES)
    desc_col = column_map.get("description") or _find_column(columns, DESC_COLUMN_CANDIDATES)
    amount_col = column_map.get("amount") or _find_column(columns, AMOUNT_COLUMN_CANDIDATES)
    debit_col = column_map.get("debit") or _find_column(columns, DEBIT_COLUMN_CANDIDATES)
    credit_col = column_map.get("credit") or _find_column(columns, CREDIT_COLUMN_CANDIDATES)

    if date_col is None:
        raise ValueError(f"Could not detect a date column in {path.name}; pass column_map={{'date': ...}}")
    if desc_col is None:
        desc_col = columns[1] if len(columns) > 1 else columns[0]

    transactions: list[ParsedTransaction] = []
    for _, row in df.iterrows():
        txn_date = _parse_date_cell(row.get(date_col))
        if txn_date is None:
            continue
        description = str(row.get(desc_col, "")).strip() or "(no description)"

        amount: float | None = None
        if amount_col:
            amount = _parse_amount_cell(row.get(amount_col))
        elif debit_col or credit_col:
            debit = _parse_amount_cell(row.get(debit_col)) if debit_col else None
            credit = _parse_amount_cell(row.get(credit_col)) if credit_col else None
            if credit:
                amount = abs(credit)
            elif debit:
                amount = -abs(debit)
        if amount is None:
            continue
        transactions.append(ParsedTransaction(txn_date=txn_date, description=description, amount=amount))
    return transactions
