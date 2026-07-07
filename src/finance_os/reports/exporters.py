"""Export data to CSV, Excel and PDF. Every export writes to
data/exports/ (or a caller-supplied path) — never anywhere off-disk.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
from fpdf import FPDF
from fpdf.enums import XPos, YPos

from finance_os.db import repository as repo


def export_transactions_csv(conn: sqlite3.Connection, path: Path, start_month: str | None = None, end_month: str | None = None) -> Path:
    df = repo.get_transactions_df(conn, start_month, end_month)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


def export_transactions_excel(conn: sqlite3.Connection, path: Path, start_month: str | None = None, end_month: str | None = None) -> Path:
    df = repo.get_transactions_df(conn, start_month, end_month)
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Transactions", index=False)
        if not df.empty:
            by_cat = df[df["direction"] == "expense"].groupby("category")["amount"].sum().abs().reset_index()
            by_cat.columns = ["Category", "Total"]
            by_cat.to_excel(writer, sheet_name="By Category", index=False)
            by_month = df.groupby(["period_month", "direction"])["amount"].sum().unstack(fill_value=0).reset_index()
            by_month.to_excel(writer, sheet_name="By Month", index=False)
    return path


def export_salary_history_csv(conn: sqlite3.Connection, path: Path) -> Path:
    df = repo.get_salary_slips_df(conn)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


class _ReportPDF(FPDF):
    def header(self) -> None:
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 10, self.title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(100)
        self.cell(0, 6, "Generated locally by Finance OS - no data leaves this machine", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_text_color(0)
        self.ln(2)


_UNICODE_REPLACEMENTS = {
    "€": "EUR", "—": "-", "–": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "…": "...",
}


def _s(text: str) -> str:
    """Sanitize text for the core Helvetica (latin-1) font: fpdf2's base
    fonts don't support the full unicode range (no '€', em-dash, smart
    quotes, ...), so swap common ones for ASCII and drop anything else
    rather than crashing the export."""
    result = str(text)
    for char, replacement in _UNICODE_REPLACEMENTS.items():
        result = result.replace(char, replacement)
    return result.encode("latin-1", errors="replace").decode("latin-1")


def _line(pdf: FPDF, text: str) -> None:
    """Write one full-width line and reliably return the cursor to the left
    margin on the next line (fpdf2's multi_cell defaults to leaving x at the
    right edge of the cell, which starves the next call of width)."""
    pdf.multi_cell(0, 6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _add_section(pdf: FPDF, heading: str) -> None:
    pdf.set_font("Helvetica", "B", 12)
    pdf.ln(3)
    pdf.cell(0, 8, heading, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 10)


def export_monthly_review_pdf(payload: dict, path: Path) -> Path:
    pdf = _ReportPDF()
    pdf.title = f"Monthly Financial Review - {payload['period_month']}"
    pdf.add_page()

    _add_section(pdf, "Summary")
    _line(pdf, (
        f"Income: EUR {payload['income']:,.2f}\n"
        f"Expenses: EUR {payload['expenses']:,.2f}\n"
        f"Net cash flow: EUR {payload['net_cashflow']:,.2f}\n"
        f"Savings rate: {payload['savings_rate']:.1%}\n"
        f"Net worth: {('EUR %.2f' % payload['net_worth']) if payload['net_worth'] is not None else 'n/a'}\n"
        f"Debt paid this month: EUR {payload['debt_paid_this_month']:,.2f}\n"
        f"Invested this month: EUR {payload['invested_this_month']:,.2f}\n"
        f"Financial health score: {payload['financial_health_score']['total']}/100"
    ))

    _add_section(pdf, "Top Spending Categories")
    for row in payload["spending_by_category"][:10]:
        _line(pdf, _s(f"- {row['category']}: EUR {row['total']:,.2f}"))

    _add_section(pdf, "Largest Purchases")
    for row in payload["largest_purchases"][:10]:
        _line(pdf, _s(f"- {row['txn_date']}  {row['description_raw'][:45]}  EUR {abs(row['amount']):,.2f}"))

    _add_section(pdf, "Recommendations")
    for rec in payload["recommendations"]:
        _line(pdf, _s(f"- {rec}"))

    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return path


def export_weekly_review_pdf(payload: dict, path: Path) -> Path:
    pdf = _ReportPDF()
    pdf.title = f"Weekly Financial Review - {payload['week']}"
    pdf.add_page()

    _add_section(pdf, "Summary")
    _line(pdf, (
        f"Period: {payload['start_date']} to {payload['end_date']}\n"
        f"Income: EUR {payload['total_income']:,.2f}\n"
        f"Spent: EUR {payload['total_spent']:,.2f}\n"
        f"Net: EUR {payload['net']:,.2f}\n"
        f"Financial health score: {payload['financial_health_score']['total']}/100"
    ))

    _add_section(pdf, "Wins")
    for w in payload["wins"]:
        _line(pdf, _s(f"+ {w}"))

    _add_section(pdf, "Mistakes")
    for m in payload["mistakes"]:
        _line(pdf, _s(f"- {m}"))

    _add_section(pdf, "Top Recommendations")
    for r in payload["top_recommendations"]:
        _line(pdf, _s(f"- {r}"))

    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(path))
    return path
