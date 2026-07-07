from __future__ import annotations

import datetime as dt

import plotly.express as px
import streamlit as st

from finance_os.categorize.categorizer import Categorizer
from finance_os.config import load_categories
from finance_os.dashboard._shared import eur, get_conn, page_setup
from finance_os.db import repository as repo

page_setup("Expense Tracking")

conn = get_conn()
all_categories = sorted(load_categories().keys())

with st.expander("Add a manual transaction"):
    with st.form("add_transaction_form"):
        c1, c2 = st.columns(2)
        txn_date = c1.date_input("Date", value=dt.date.today())
        amount = c2.number_input("Amount (EUR) — negative for an expense, positive for income", value=-10.0, step=1.0)
        description = st.text_input("Description", placeholder="e.g. REWE weekly groceries")
        category_choice = st.selectbox("Category (leave as Auto-detect to categorize automatically)", ["Auto-detect", *all_categories])
        account = st.text_input("Account", value="manual")
        submitted = st.form_submit_button("Add transaction")
        if submitted:
            if not description.strip():
                st.error("Description is required.")
            else:
                categorizer = Categorizer(conn)
                if category_choice == "Auto-detect":
                    result = categorizer.categorize(description)
                    category_id, merchant_id = result.category_id, result.merchant_id
                else:
                    category_id = repo.get_or_create_category(conn, category_choice)
                    merchant_id = None
                account_id = repo.get_or_create_account(conn, account)
                direction = "income" if amount > 0 else "expense"
                txn_id = repo.insert_transaction(
                    conn, txn_date=txn_date.isoformat(), description_raw=description, amount=amount,
                    direction=direction, account_id=account_id, category_id=category_id,
                    merchant_id=merchant_id, is_manual_entry=True, account_name=account,
                )
                conn.commit()
                if txn_id is None:
                    st.warning("Skipped — an identical transaction already exists (same date/amount/description/account).")
                else:
                    st.success(f"Added transaction {txn_id}.")
                    st.cache_resource.clear()
                    st.rerun()

df = repo.get_transactions_df(conn)

if df.empty:
    st.info("No transactions yet. Add one above, or run `finance ingest <folder>` to import bank statements, CSVs or receipts.")
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

col_correct, col_delete = st.columns(2)

with col_correct:
    st.subheader("Correct a category")
    st.caption("The system learns from this — future charges from the same merchant will use it automatically.")
    with st.form("correction_form"):
        txn_id = st.number_input("Transaction ID", min_value=1, step=1, key="correct_id")
        new_category = st.selectbox("Correct category", all_categories, key="correct_cat")
        submitted = st.form_submit_button("Apply correction")
        if submitted:
            row = conn.execute("SELECT description_raw FROM transactions WHERE id = ?", (int(txn_id),)).fetchone()
            if row is None:
                st.error(f"No transaction with id {txn_id}")
            else:
                categorizer = Categorizer(conn)
                categorizer.learn_correction(int(txn_id), row["description_raw"], new_category)
                conn.commit()
                st.success(f"Transaction {txn_id} recategorized as '{new_category}'.")
                st.cache_resource.clear()
                st.rerun()

with col_delete:
    st.subheader("Delete a transaction")
    st.caption("Use this to remove a duplicate or mis-imported entry.")
    with st.form("delete_form"):
        delete_id = st.number_input("Transaction ID", min_value=1, step=1, key="delete_id")
        confirm = st.checkbox("I'm sure I want to delete this.")
        submitted_delete = st.form_submit_button("Delete transaction")
        if submitted_delete:
            if not confirm:
                st.error("Check the confirmation box to delete.")
            elif repo.delete_transaction(conn, int(delete_id)):
                conn.commit()
                st.success(f"Deleted transaction {delete_id}.")
                st.cache_resource.clear()
                st.rerun()
            else:
                st.error(f"No transaction with id {delete_id}")

uncategorized = repo.uncategorized_transactions(conn)
if not uncategorized.empty:
    st.subheader(f"Needs review ({len(uncategorized)} uncategorized)")
    st.dataframe(uncategorized, use_container_width=True)
