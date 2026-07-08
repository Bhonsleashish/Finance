from __future__ import annotations

import datetime as dt

import plotly.express as px
import streamlit as st

from finance_os.analysis.investments import allocation_by_holding, holdings_df, portfolio_summary
from finance_os.dashboard._shared import eur, get_conn, page_setup
from finance_os.db import repository as repo

page_setup("Investments")

conn = get_conn()

st.caption(
    "This app never calls a live market-data API (no external calls, anywhere). "
    "'Current value' is whatever you last told it — update it any time below. "
    "Until then, a holding is valued at what you paid for it."
)

with st.expander("Add a purchase"):
    with st.form("add_investment_form"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Name (ticker/fund/asset)", placeholder="e.g. VWCE, Bitcoin, Apple Inc.")
        asset_type = c2.selectbox("Type", ["etf", "stock", "crypto", "fund", "bond", "other"])
        c3, c4 = st.columns(2)
        amount = c3.number_input("Amount invested (EUR)", min_value=0.0, step=50.0)
        purchase_date = c4.date_input("Purchase date", value=dt.date.today())
        c5, c6 = st.columns(2)
        quantity = c5.number_input("Quantity (optional)", min_value=0.0, step=0.01, value=0.0)
        broker = c6.text_input("Broker (optional)", placeholder="e.g. Trade Republic")
        submitted = st.form_submit_button("Add investment")
        if submitted:
            if not name.strip() or amount <= 0:
                st.error("Name and a positive amount are required.")
            else:
                inv_id = repo.add_investment(
                    conn, name.strip(), purchase_date.isoformat(), amount, asset_type=asset_type,
                    broker=broker or None, quantity=quantity or None,
                )
                conn.commit()
                st.success(f"Recorded investment {inv_id}: {name} — {eur(amount)}.")
                st.rerun()

df = holdings_df(conn)
if df.empty:
    st.info("No investments recorded yet — add one above, or tell me about a purchase in chat and I'll log it for you.")
    st.stop()

summary = portfolio_summary(conn)
c1, c2, c3 = st.columns(3)
c1.metric("Total invested", eur(summary.total_invested))
c2.metric("Current value", eur(summary.total_current_value))
gain_label = f"{summary.unrealized_gain_pct:+.1%}" if summary.unrealized_gain_pct is not None else None
c3.metric("Unrealized gain/loss", eur(summary.unrealized_gain), delta=gain_label)
if summary.stale_value_count:
    st.caption(f"{summary.stale_value_count} of {summary.holdings_count} holding(s) still valued at cost — update below for an accurate total.")

st.subheader("Allocation")
alloc = allocation_by_holding(conn)
fig = px.pie(alloc, names="name", values="value", hole=0.4)
st.plotly_chart(fig, use_container_width=True)

st.subheader("Holdings")
display = df.copy()
display["value_is_estimated"] = display["value_is_estimated"].map({True: "at cost", False: "updated"})
st.dataframe(
    display[["id", "name", "asset_type", "broker", "purchase_date", "quantity", "amount_invested",
             "effective_value", "unrealized_gain", "unrealized_gain_pct", "value_is_estimated"]],
    use_container_width=True,
)

col_update, col_delete = st.columns(2)

with col_update:
    st.subheader("Update current value")
    with st.form("update_value_form"):
        update_id = st.number_input("Investment ID", min_value=1, step=1)
        new_value = st.number_input("Current value (EUR)", min_value=0.0, step=10.0)
        do_update = st.form_submit_button("Update")
        if do_update:
            if repo.update_investment_value(conn, int(update_id), new_value):
                conn.commit()
                st.success(f"Updated investment {update_id} to {eur(new_value)}.")
                st.rerun()
            else:
                st.error(f"No investment with id {update_id}")

with col_delete:
    st.subheader("Delete a holding")
    with st.form("delete_investment_form"):
        delete_id = st.number_input("Investment ID", min_value=1, step=1, key="del_inv_id")
        confirm = st.checkbox("I'm sure I want to delete this.")
        do_delete = st.form_submit_button("Delete")
        if do_delete:
            if not confirm:
                st.error("Check the confirmation box to delete.")
            elif repo.delete_investment(conn, int(delete_id)):
                conn.commit()
                st.success(f"Deleted investment {delete_id}.")
                st.rerun()
            else:
                st.error(f"No investment with id {delete_id}")
