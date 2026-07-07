"""Date helpers shared across ingestion, analysis and reporting."""

from __future__ import annotations

from datetime import date, datetime, timedelta

GERMAN_MONTHS = {
    "januar": 1, "jan": 1,
    "februar": 2, "feb": 2,
    "märz": 3, "maerz": 3, "mär": 3, "mrz": 3,
    "april": 4, "apr": 4,
    "mai": 5,
    "juni": 6, "jun": 6,
    "juli": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "okt": 10,
    "november": 11, "nov": 11,
    "dezember": 12, "dez": 12,
}


def period_month(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_range(start_month: str, end_month: str) -> list[str]:
    """Inclusive list of 'YYYY-MM' strings from start_month to end_month."""
    start = datetime.strptime(start_month, "%Y-%m")
    end = datetime.strptime(end_month, "%Y-%m")
    months = []
    cur = start
    while cur <= end:
        months.append(cur.strftime("%Y-%m"))
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)
    return months


def current_period_month() -> str:
    return period_month(date.today())


def iso_week_bounds(d: date | None = None) -> tuple[date, date, str]:
    """Return (monday, sunday, 'YYYY-Www') for the ISO week containing d."""
    d = d or date.today()
    monday = d - timedelta(days=d.isoweekday() - 1)
    sunday = monday + timedelta(days=6)
    iso_year, iso_week, _ = d.isocalendar()
    key = f"{iso_year:04d}-W{iso_week:02d}"
    return monday, sunday, key


def parse_german_date(text: str) -> date | None:
    """Parse common German date formats: 31.12.2026, 31. Dezember 2026, 2026-12-31."""
    text = text.strip()
    fmts = ["%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"]
    for fmt in fmts:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # "31. Dezember 2026" style
    import re

    m = re.match(r"(\d{1,2})\.?\s+([A-Za-zäöüÄÖÜ]+)\s+(\d{4})", text)
    if m:
        day, month_name, year = m.groups()
        month_num = GERMAN_MONTHS.get(month_name.lower())
        if month_num:
            return date(int(year), month_num, int(day))
    return None


def parse_german_amount(text: str) -> float | None:
    """Parse German-formatted numbers like '1.234,56' or '-45,00' or '1234.56'."""
    import re

    text = text.strip().replace(" ", "").replace(" ", "")
    if not text:
        return None
    negative = text.startswith("-") or text.endswith("-")
    text = text.lstrip("-").rstrip("-")
    text = text.replace("+", "")
    if not re.match(r"^[\d.,]+$", text):
        return None
    if "," in text and "." in text:
        # German: '.' thousands, ',' decimal
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if negative else value
