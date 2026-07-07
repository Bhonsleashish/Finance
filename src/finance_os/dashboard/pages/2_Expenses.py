from __future__ import annotations

import plotly.express as px
import streamlit as st

from finance_os.categorize.categorizer import Categorizer
from finance_os.config import load_categories
from finance_os.dashboard._shared import eur, get_conn, page_setup
from finance_os.db import repository as repo

page_setup("Expense Tracking")

conn = get_conn()
df = repo.get_transactions_df(conn)

if df.empty:
    st.info("No transactions yet. Run `finance ingest <folder>` to import bank statements, CSVs or receipts.")
    st.stop()

st.subheader("All transactions")
categories = ["All"] + sorted(df["category"].dropna().unique().tolist())
selected_cat = st.selectbox("Filter by category", categories)
filtered = df if selected_cat == "All" else df[df["category"] == selected_cat]
st.dataframe(
    filtered[["id", "txn_date", "description_raw", "merchant", "category", "amount", "account"]],
    use_container_width=True,
)

st.subheader("Spending trend by category")
expenses = df[df["direction"] == "expense"].copy()
expenses["category"] = expenses["category"].fillna("Uncategorized")
trend = expenses.groupby(["period_month", "category"])["amount"].sum().abs().reset_index()
fig = px.bar(trend, x="period_month", y="amount", color="category")
st.plotly_chart(fig, use_container_width=True)

st.subheader("Correct a category (the system learns from this)")
uncategorized = repo.uncategorized_transactions(conn)
with st.form("correction_form"):
    txn_id = st.number_input("Transaction ID", min_value=1, step=1)
    all_categories = sorted(load_categories().keys())
    new_category = st.selectbox("Correct category", all_categories)
    submitted = st.form_submit_button("Apply correction")
    if submitted:
        row = conn.execute("SELECT description_raw FROM transactions WHERE id = ?", (int(txn_id),)).fetchone()
        if row is None:
            st.error(f"No transaction with id {txn_id}")
        else:
            categorizer = Categorizer(conn)
            categorizer.learn_correction(int(txn_id), row["description_raw"], new_category)
            conn.commit()
            st.success(f"Transaction {txn_id} recategorized as '{new_category}'. Future charges from this merchant will use it automatically.")
            st.cache_resource.clear()

if not uncategorized.empty:
    st.subheader(f"Needs review ({len(uncategorized)} uncategorized)")
    st.dataframe(uncategorized, use_container_width=True)
