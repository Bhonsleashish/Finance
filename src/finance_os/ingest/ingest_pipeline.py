"""Ingestion orchestrator: point it at a file (or a folder of files) and it
figures out the document type, extracts text (native/OCR), parses it,
categorizes any transactions, and writes everything to the local database —
with content-hash dedup so re-running ingestion on the same folder is safe.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from finance_os.categorize.categorizer import Categorizer
from finance_os.db import repository as repo
from finance_os.ingest.bank_statement_parser import parse_statement_text
from finance_os.ingest.csv_importer import parse_csv
from finance_os.ingest.payslip_parser import parse_payslip_text
from finance_os.ingest.pdf_extractor import extract_image, extract_pdf
from finance_os.ingest.receipt_parser import parse_receipt_text
from finance_os.utils.logging import get_logger

logger = get_logger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".bmp"}

DOC_TYPE_BY_FOLDER = {
    "salary_slips": "payslip",
    "bank_statements": "bank_statement",
    "receipts": "receipt",
    "invoices": "invoice",
    "insurance": "insurance",
    "tax": "tax",
    "inbox": None,  # auto-detect
}


@dataclass
class IngestResult:
    file: Path
    doc_type: str
    status: str  # 'imported' | 'duplicate' | 'needs_review' | 'failed'
    transactions_added: int = 0
    message: str = ""


def guess_doc_type(path: Path) -> str:
    if path.suffix.lower() == ".csv":
        return "csv_export"
    parent = path.parent.name.lower()
    mapped = DOC_TYPE_BY_FOLDER.get(parent)
    if mapped:
        return mapped
    name = path.name.lower()
    if any(k in name for k in ("gehalt", "lohn", "payslip", "verdienst", "abrechnung")):
        return "payslip"
    if any(k in name for k in ("kontoauszug", "statement", "umsatz")):
        return "bank_statement"
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        return "screenshot"
    return "receipt"


def ingest_file(conn: sqlite3.Connection, path: Path, categorizer: Categorizer, doc_type: str | None = None) -> IngestResult:
    doc_type = doc_type or guess_doc_type(path)
    data = path.read_bytes()
    content_hash = repo.hash_bytes(data)

    if repo.find_document_by_hash(conn, content_hash):
        return IngestResult(file=path, doc_type=doc_type, status="duplicate", message="Already imported")

    try:
        if doc_type == "csv_export":
            return _ingest_csv(conn, path, content_hash, categorizer)
        if path.suffix.lower() == ".pdf":
            return _ingest_pdf(conn, path, content_hash, doc_type, categorizer)
        if path.suffix.lower() in IMAGE_EXTENSIONS:
            return _ingest_image(conn, path, content_hash, doc_type, categorizer)
        return IngestResult(file=path, doc_type=doc_type, status="failed", message="Unsupported file type")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to ingest %s", path)
        repo.insert_document(conn, doc_type, str(path), content_hash, status="failed", notes=str(exc))
        return IngestResult(file=path, doc_type=doc_type, status="failed", message=str(exc))


def _ingest_pdf(conn: sqlite3.Connection, path: Path, content_hash: str, doc_type: str, categorizer: Categorizer) -> IngestResult:
    extracted = extract_pdf(path)
    text = extracted.text

    if doc_type == "payslip":
        parsed = parse_payslip_text(text)
        document_id = repo.insert_document(
            conn, doc_type, str(path), content_hash, parsed.period_month, extracted.method, text,
            status="needs_review" if parsed.needs_review else "processed",
        )
        if parsed.period_month:
            repo.upsert_salary_slip(conn, parsed.period_month, document_id=document_id, employer=parsed.employer, **parsed.as_db_fields())
        status = "needs_review" if parsed.needs_review else "imported"
        return IngestResult(file=path, doc_type=doc_type, status=status,
                             message=f"Matched {parsed.matched_field_count} fields for {parsed.period_month or 'unknown period'}")

    if doc_type == "bank_statement":
        txns = parse_statement_text(text)
        document_id = repo.insert_document(conn, doc_type, str(path), content_hash,
                                            txns[0].txn_date.strftime("%Y-%m") if txns else None,
                                            extracted.method, text)
        added = _store_transactions(conn, document_id, path.stem, txns, categorizer)
        status = "imported" if txns else "needs_review"
        return IngestResult(file=path, doc_type=doc_type, status=status, transactions_added=added,
                             message=f"{added} transactions imported")

    # receipt / invoice / insurance / tax: extract merchant/date/total, store as one transaction
    receipt = parse_receipt_text(text)
    document_id = repo.insert_document(
        conn, doc_type, str(path), content_hash,
        receipt.txn_date.strftime("%Y-%m") if receipt.txn_date else None, extracted.method, text,
        status="needs_review" if not (receipt.txn_date and receipt.amount) else "processed",
    )
    added = 0
    if receipt.txn_date and receipt.amount:
        cat = categorizer.categorize(receipt.merchant_guess or path.stem)
        txn_id = repo.insert_transaction(
            conn,
            txn_date=receipt.txn_date.isoformat(),
            description_raw=receipt.merchant_guess or path.stem,
            amount=-abs(receipt.amount),
            direction="expense",
            document_id=document_id,
            merchant_id=cat.merchant_id,
            category_id=cat.category_id,
            account_name="",
        )
        added = 1 if txn_id else 0
    status = "imported" if added else "needs_review"
    return IngestResult(file=path, doc_type=doc_type, status=status, transactions_added=added)


def _ingest_image(conn: sqlite3.Connection, path: Path, content_hash: str, doc_type: str, categorizer: Categorizer) -> IngestResult:
    extracted = extract_image(path)
    receipt = parse_receipt_text(extracted.text)
    document_id = repo.insert_document(
        conn, doc_type, str(path), content_hash,
        receipt.txn_date.strftime("%Y-%m") if receipt.txn_date else None, "ocr", extracted.text,
        status="needs_review" if not (receipt.txn_date and receipt.amount) else "processed",
    )
    added = 0
    if receipt.txn_date and receipt.amount:
        cat = categorizer.categorize(receipt.merchant_guess or path.stem)
        txn_id = repo.insert_transaction(
            conn,
            txn_date=receipt.txn_date.isoformat(),
            description_raw=receipt.merchant_guess or path.stem,
            amount=-abs(receipt.amount),
            direction="expense",
            document_id=document_id,
            merchant_id=cat.merchant_id,
            category_id=cat.category_id,
        )
        added = 1 if txn_id else 0
    status = "imported" if added else "needs_review"
    return IngestResult(file=path, doc_type=doc_type, status=status, transactions_added=added)


def _ingest_csv(conn: sqlite3.Connection, path: Path, content_hash: str, categorizer: Categorizer) -> IngestResult:
    txns = parse_csv(path)
    period = txns[0].txn_date.strftime("%Y-%m") if txns else None
    document_id = repo.insert_document(conn, "csv_export", str(path), content_hash, period, "csv", None)
    added = _store_transactions(conn, document_id, path.stem, txns, categorizer)
    status = "imported" if txns else "needs_review"
    return IngestResult(file=path, doc_type="csv_export", status=status, transactions_added=added,
                         message=f"{added} transactions imported")


def _store_transactions(conn: sqlite3.Connection, document_id: int, account_name: str, txns, categorizer: Categorizer) -> int:
    account_id = repo.get_or_create_account(conn, account_name)
    added = 0
    for txn in txns:
        cat = categorizer.categorize(txn.description)
        direction = "income" if txn.amount > 0 else "expense"
        txn_id = repo.insert_transaction(
            conn,
            txn_date=txn.txn_date.isoformat(),
            description_raw=txn.description,
            amount=txn.amount,
            direction=direction,
            document_id=document_id,
            account_id=account_id,
            merchant_id=cat.merchant_id,
            category_id=cat.category_id,
            account_name=account_name,
        )
        if txn_id:
            added += 1
    return added


def ingest_path(conn: sqlite3.Connection, path: Path, categorizer: Categorizer | None = None) -> list[IngestResult]:
    """Ingest a single file or every supported file in a directory tree."""
    categorizer = categorizer or Categorizer(conn)
    results: list[IngestResult] = []
    if path.is_file():
        results.append(ingest_file(conn, path, categorizer))
    else:
        supported = {".pdf", ".csv", *IMAGE_EXTENSIONS}
        for file_path in sorted(path.rglob("*")):
            if file_path.is_file() and file_path.suffix.lower() in supported and not file_path.name.startswith("."):
                results.append(ingest_file(conn, file_path, categorizer))
    conn.commit()
    return results
