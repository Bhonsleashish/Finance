from __future__ import annotations

import plotly.express as px
import streamlit as st

from finance_os.analysis.forecasting import (
    forecast_debt_payoff,
    forecast_emergency_fund_completion,
    forecast_savings,
    full_trajectory_report,
)
from finance_os.dashboard._shared import eur, get_conn, page_setup

page_setup("Forecasting")

conn = get_conn()

col1, col2 = st.columns(2)
current_balance = col1.number_input("Current bank balance (EUR)", min_value=0.0, value=0.0, step=100.0)
current_savings = col2.number_input("Current savings/investments (EUR)", min_value=0.0, value=0.0, step=100.0)

report = full_trajectory_report(conn, current_balance)
st.caption(f"Based on average monthly cash flow of {eur(report['avg_monthly_cashflow'])} "
           f"(trend: {report['trend_slope_per_month']:+.2f}/mo).")

st.subheader("Balance projection")
proj = report["balance_projection"]
fig = px.bar(x=list(proj.keys()), y=list(proj.values()), labels={"x": "Horizon", "y": "Projected balance (EUR)"})
st.plotly_chart(fig, use_container_width=True)

st.subheader("Savings projection")
savings_proj = forecast_savings(conn, current_savings)
fig2 = px.bar(x=list(savings_proj.keys()), y=list(savings_proj.values()), labels={"x": "Horizon", "y": "Projected savings (EUR)"})
st.plotly_chart(fig2, use_container_width=True)

st.subheader("Debt payoff estimator")
c1, c2 = st.columns(2)
current_debt = c1.number_input("Current debt balance (EUR)", min_value=0.0, value=0.0, step=100.0)
monthly_payment = c2.number_input("Monthly debt payment (EUR)", min_value=0.0, value=0.0, step=25.0)
if current_debt > 0:
    payoff = forecast_debt_payoff(current_debt, monthly_payment)
    if payoff["months_remaining"] is not None:
        st.write(f"Debt-free in **{payoff['months_remaining']} months** (around **{payoff['payoff_date']}**).")
    else:
        st.write("Set a monthly payment above zero to estimate a payoff date.")

st.subheader("Emergency fund completion estimator")
c3, c4, c5 = st.columns(3)
ef_current = c3.number_input("Emergency fund - current (EUR)", min_value=0.0, value=0.0, step=100.0)
ef_target = c4.number_input("Emergency fund - target (EUR)", min_value=0.0, value=0.0, step=100.0)
ef_contribution = c5.number_input("Monthly contribution (EUR)", min_value=0.0, value=0.0, step=25.0)
if ef_target > 0:
    ef = forecast_emergency_fund_completion(ef_current, ef_target, ef_contribution)
    if ef["completion_date"]:
        st.write(f"Emergency fund fully funded by **{ef['completion_date']}** ({ef['months_remaining']} months).")
    else:
        st.write("Set a monthly contribution above zero to estimate a completion date.")
