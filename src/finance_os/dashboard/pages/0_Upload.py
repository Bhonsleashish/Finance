from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from finance_os.categorize.categorizer import Categorizer
from finance_os.config import load_settings
from finance_os.dashboard._shared import get_conn, page_setup
from finance_os.ingest.ingest_pipeline import DOC_TYPE_BY_FOLDER, ingest_file

page_setup("Upload Documents")

conn = get_conn()
settings = load_settings()

DOC_TYPE_LABELS = {
    "payslip": "Payslip (Gehaltsabrechnung)",
    "bank_statement": "Bank statement",
    "receipt": "Receipt",
    "invoice": "Invoice",
    "insurance": "Insurance document",
    "tax": "Tax document",
    "investment": "Investment purchase (broker screenshot/confirmation)",
    "screenshot": "Something else / not sure (best-effort auto-detect)",
}

FOLDER_BY_DOC_TYPE = {v: k for k, v in DOC_TYPE_BY_FOLDER.items() if v}
FOLDER_BY_DOC_TYPE["csv_export"] = "bank_statements"
FOLDER_BY_DOC_TYPE["screenshot"] = "inbox"

STATUS_TO_ALERT = {"imported": "success", "duplicate": "warning", "needs_review": "warning", "failed": "error"}
STATUS_COLOR = {"imported": "#1a7f37", "duplicate": "#9a6700", "needs_review": "#9a6700", "failed": "#cf222e"}

st.write(
    "Upload one or more files and tell me what they are — payslips, bank statements, receipts, investment "
    "purchases, etc. — and each will be parsed accordingly and saved under `data/` for your records."
)

uploaded_files = st.file_uploader(
    "Choose file(s)", type=["pdf", "csv", "png", "jpg", "jpeg"], accept_multiple_files=True,
)

non_csv_files = [f for f in uploaded_files if not f.name.lower().endswith(".csv")]
csv_files = [f for f in uploaded_files if f.name.lower().endswith(".csv")]

if csv_files and not non_csv_files:
    st.caption("CSV files are always parsed as a transaction export — no need to pick a type.")
    doc_type = "csv_export"
elif csv_files and non_csv_files:
    label = st.selectbox("What are the non-CSV file(s) above?", list(DOC_TYPE_LABELS.values()))
    doc_type = next(k for k, v in DOC_TYPE_LABELS.items() if v == label)
    st.caption(f"Applies to the {len(non_csv_files)} non-CSV file(s); CSV file(s) are always parsed as a transaction export.")
else:
    label = st.selectbox(
        "What are these?" if len(uploaded_files) > 1 else "What is this document?",
        list(DOC_TYPE_LABELS.values()),
    )
    doc_type = next(k for k, v in DOC_TYPE_LABELS.items() if v == label)
    if uploaded_files and any(f.name.lower().endswith((".png", ".jpg", ".jpeg")) for f in uploaded_files) and doc_type in ("payslip", "bank_statement"):
        st.caption("Photos/screenshots go through OCR first — works, but a clean PDF export from your bank/employer parses more reliably.")

if st.button("Upload and process", disabled=not uploaded_files, type="primary"):
    categorizer = Categorizer(conn)
    processed = []  # (uploaded_file.name, dest_folder, filename, dest_path, IngestResult)

    for uploaded in uploaded_files:
        file_doc_type = "csv_export" if uploaded.name.lower().endswith(".csv") else doc_type
        dest_folder = FOLDER_BY_DOC_TYPE.get(file_doc_type, "inbox")
        dest_dir = settings.data_dir / dest_folder
        dest_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{datetime.now():%Y%m%d_%H%M%S_%f}_{uploaded.name}"
        dest_path = dest_dir / filename
        dest_path.write_bytes(uploaded.getvalue())

        result = ingest_file(conn, dest_path, categorizer, doc_type=file_doc_type)
        conn.commit()
        processed.append((uploaded.name, dest_folder, filename, dest_path, result))

    counts = pd.Series([r.status for *_, r in processed]).value_counts()
    summary_bits = [f"{count} {status.replace('_', ' ')}" for status, count in counts.items()]
    st.write(f"Processed {len(processed)} file(s): " + ", ".join(summary_bits) + ".")

    table_rows = [{
        "File": name,
        "Type": r.doc_type,
        "Status": r.status.replace("_", " "),
        "Transactions": r.transactions_added,
        "Message": r.message,
        "Saved to": f"data/{folder}/{filename}",
    } for name, folder, filename, _, r in processed]
    result_df = pd.DataFrame(table_rows)
    styled = result_df.style.map(
        lambda v: f"color: {STATUS_COLOR.get(v.replace(' ', '_'), '')}; font-weight: 600",
        subset=["Status"],
    )
    st.dataframe(styled, use_container_width=True)

    needs_attention = [(name, path, r) for name, _, _, path, r in processed if r.status in ("needs_review", "failed")]
    if needs_attention:
        st.subheader("Files flagged for review")
        st.write(
            "The extraction wasn't fully confident for these. Check the Salary/Expenses/Investments page to "
            "confirm or correct the details — or expand a file below to see exactly what text was extracted, "
            "which usually explains why (e.g. a bank statement layout the parser doesn't recognize yet)."
        )
        for name, path, r in needs_attention:
            with st.expander(f"{name} — {r.status.replace('_', ' ')}"):
                row = conn.execute("SELECT raw_text, extraction_method FROM documents WHERE source_path = ?", (str(path),)).fetchone()
                if row and row["raw_text"]:
                    st.caption(f"Extraction method: {row['extraction_method']}")
                    st.text_area("Extracted text", row["raw_text"][:4000], height=200, key=f"raw_{name}_{path}")
                else:
                    st.caption("No text could be extracted at all (empty result) — for a photo/screenshot this "
                               "usually means OCR (Tesseract) isn't installed; for a PDF it may be a scanned "
                               "image with no text layer and OCR unavailable.")

st.divider()
st.subheader("Recently uploaded")
docs = conn.execute(
    "SELECT id, doc_type, source_path, imported_at, status FROM documents ORDER BY imported_at DESC LIMIT 15"
).fetchall()
if docs:
    df = pd.DataFrame([dict(row) for row in docs])
    df["source_path"] = df["source_path"].apply(lambda p: p.split("/")[-1])
    st.dataframe(df, use_container_width=True)
else:
    st.caption("Nothing uploaded yet.")
