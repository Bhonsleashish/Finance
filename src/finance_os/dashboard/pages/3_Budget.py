from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from finance_os.analysis.budgeting import budget_vs_actual, generate_budget, persist_budget
from finance_os.dashboard._shared import eur, get_conn, page_setup
from finance_os.dashboard.theme import CATEGORICAL, STATUS, status_for_ratio
from finance_os.utils.dates import current_period_month

page_setup("Adaptive Budget")

conn = get_conn()
month = st.text_input("Month (YYYY-MM)", value=current_period_month())

if st.button("Generate / refresh adaptive budget", type="primary"):
    lines = generate_budget(conn, month)
    persist_budget(conn, month, lines)
    conn.commit()
    st.success(f"Budget generated for {month}.")

bva = budget_vs_actual(conn, month)
if bva.empty:
    st.info("No budget or transactions for this month yet. Click 'Generate' above.")
    st.stop()

total_budgeted = bva["budgeted_amount"].sum()
total_actual = bva["actual"].sum()
overall_ratio = (total_actual / total_budgeted) if total_budgeted else 0
c1, c2, c3 = st.columns(3)
c1.metric("Budgeted", eur(total_budgeted))
c2.metric("Spent", eur(total_actual))
c3.metric("Overall used", f"{overall_ratio:.0%}")

st.subheader("Budget vs. actual")
actual_colors = [status_for_ratio(r) if pd.notna(r) else STATUS["good"] for r in bva["pct_used"]]
fig = go.Figure()
fig.add_bar(x=bva["category"], y=bva["budgeted_amount"], name="Budgeted", marker_color="#c3c2b7")
fig.add_bar(x=bva["category"], y=bva["actual"], name="Actual", marker_color=actual_colors)
fig.update_layout(barmode="group", height=450, hovermode="x unified", legend=dict(orientation="h", y=1.12))
st.plotly_chart(fig, use_container_width=True)

st.subheader("Detail")
display = bva.copy()
display["pct_used"] = display["pct_used"].apply(lambda v: f"{v:.0%}" if pd.notna(v) else "n/a")


def _highlight_over_budget(v: str) -> str:
    if not v.endswith("%") or v == "n/a":
        return ""
    return f"color: {STATUS['critical']}; font-weight: 600" if int(v[:-1]) > 100 else ""


styled = display.style.map(_highlight_over_budget, subset=["pct_used"])
st.dataframe(styled, use_container_width=True)

over = bva[bva["pct_used"].fillna(0) > 1.0]
if not over.empty:
    st.warning(f"🟠 Over budget: {', '.join(over['category'].tolist())}")
else:
    st.success("✅ Every category is within budget this month.")
