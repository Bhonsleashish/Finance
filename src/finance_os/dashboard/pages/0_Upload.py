from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from finance_os.categorize.categorizer import Categorizer
from finance_os.config import load_settings
from finance_os.dashboard._shared import get_conn, page_setup
from finance_os.ingest.ingest_pipeline import DOC_TYPE_BY_FOLDER, ingest_file

page_setup("Upload a Document")

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

st.write(
    "Upload a file and tell me what it is — a payslip, a bank statement, a receipt, an investment "
    "purchase, etc. — and it'll be parsed accordingly and saved under `data/` for your records."
)

uploaded = st.file_uploader("Choose a file", type=["pdf", "csv", "png", "jpg", "jpeg"])
is_csv = uploaded is not None and uploaded.name.lower().endswith(".csv")

if is_csv:
    st.caption("CSV files are always parsed as a transaction export (this is a bank statement/CSV, so no need to pick a type).")
    doc_type = "csv_export"
else:
    label = st.selectbox("What is this document?", list(DOC_TYPE_LABELS.values()))
    doc_type = next(k for k, v in DOC_TYPE_LABELS.items() if v == label)
    if uploaded is not None and uploaded.name.lower().endswith((".png", ".jpg", ".jpeg")) and doc_type in ("payslip", "bank_statement"):
        st.caption("Photos/screenshots go through OCR first — works, but a clean PDF export from your bank/employer parses more reliably.")

if st.button("Upload and process", disabled=uploaded is None, type="primary"):
    dest_folder = FOLDER_BY_DOC_TYPE.get(doc_type, "inbox")
    dest_dir = settings.data_dir / dest_folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{datetime.now():%Y%m%d_%H%M%S}_{uploaded.name}"
    dest_path = dest_dir / filename
    dest_path.write_bytes(uploaded.getvalue())

    categorizer = Categorizer(conn)
    result = ingest_file(conn, dest_path, categorizer, doc_type=doc_type)
    conn.commit()

    alert = getattr(st, STATUS_TO_ALERT[result.status])
    alert(f"**{result.status.replace('_', ' ').title()}**: {result.message or 'Processed.'}")
    if result.transactions_added:
        st.write(f"{result.transactions_added} transaction(s) added.")
    st.caption(f"Saved to `data/{dest_folder}/{filename}`")

    if result.status == "needs_review":
        st.info(
            "Flagged for review — the extraction wasn't fully confident. Check the Salary/Expenses/"
            "Investments page to confirm or correct the details, or use `finance uncategorized`."
        )

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
