from __future__ import annotations

import plotly.express as px
import streamlit as st

from finance_os.analysis.salary import get_salary_history, highlight_changes
from finance_os.dashboard._shared import eur, get_conn, page_setup

page_setup("Salary Analysis")

conn = get_conn()
df = get_salary_history(conn)

if df.empty:
    st.info("No payslips ingested yet. Run `finance ingest data/salary_slips`.")
    st.stop()

st.subheader("Gross vs. net salary over time")
fig = px.line(df, x="period_month", y=["gross_salary", "net_salary"], markers=True)
st.plotly_chart(fig, use_container_width=True)

st.subheader("Deductions breakdown (latest month)")
latest = df.sort_values("period_month").iloc[-1]
deduction_fields = [
    "income_tax", "solidarity_surcharge", "church_tax", "health_insurance",
    "pension_insurance", "unemployment_insurance", "nursing_care_insurance",
]
deductions = {f.replace("_", " ").title(): latest[f] for f in deduction_fields if latest.get(f)}
if deductions:
    fig2 = px.bar(x=list(deductions.keys()), y=list(deductions.values()), labels={"x": "Deduction", "y": "EUR"})
    st.plotly_chart(fig2, use_container_width=True)

st.subheader("Highlighted month-over-month changes")
changes = highlight_changes(conn)
if not changes:
    st.write("No significant (>=2%) changes detected between consecutive months.")
else:
    for c in changes:
        direction = "up" if c.delta > 0 else "down"
        st.write(f"**{c.period_month}** — {c.field.replace('_', ' ').title()} went {direction} by "
                 f"{eur(abs(c.delta))} ({c.delta_pct:+.1%}) to {eur(c.current)}.")

st.subheader("Full salary history")
st.dataframe(df, use_container_width=True)
