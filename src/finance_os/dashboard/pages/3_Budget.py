from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from finance_os.analysis.budgeting import budget_vs_actual, generate_budget, persist_budget
from finance_os.dashboard._shared import eur, get_conn, page_setup
from finance_os.utils.dates import current_period_month

page_setup("Adaptive Budget")

conn = get_conn()
month = st.text_input("Month (YYYY-MM)", value=current_period_month())

if st.button("Generate / refresh adaptive budget"):
    lines = generate_budget(conn, month)
    persist_budget(conn, month, lines)
    conn.commit()
    st.success(f"Budget generated for {month}.")

bva = budget_vs_actual(conn, month)
if bva.empty:
    st.info("No budget or transactions for this month yet. Click 'Generate' above.")
    st.stop()

st.subheader("Budget vs. actual")
fig = go.Figure()
fig.add_bar(x=bva["category"], y=bva["budgeted_amount"], name="Budgeted")
fig.add_bar(x=bva["category"], y=bva["actual"], name="Actual")
fig.update_layout(barmode="group", height=450)
st.plotly_chart(fig, use_container_width=True)

st.subheader("Detail")
display = bva.copy()
display["pct_used"] = display["pct_used"].apply(lambda v: f"{v:.0%}" if v is not None else "n/a")
st.dataframe(display, use_container_width=True)

over = bva[bva["pct_used"].fillna(0) > 1.0]
if not over.empty:
    st.warning("Over budget: " + ", ".join(over["category"].tolist()))
