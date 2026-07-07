from __future__ import annotations

import streamlit as st

from finance_os.analysis.advisor import evaluate_purchase
from finance_os.dashboard._shared import eur, get_conn, page_setup

page_setup("Spending Advisor")

conn = get_conn()

st.write("Tell me what you want to buy, and I'll evaluate it against your budget, emergency fund and goals.")

with st.form("advisor_form"):
    item = st.text_input("What do you want to buy?")
    cost = st.number_input("Cost (EUR)", min_value=0.0, step=10.0)
    submitted = st.form_submit_button("Evaluate")

if submitted and item and cost > 0:
    evaluation = evaluate_purchase(conn, item, cost)
    color = {"Buy now": "green", "Wait": "orange", "Avoid": "red"}[evaluation.recommendation]
    st.markdown(f"### :{color}[{evaluation.recommendation}]: {item} ({eur(cost)})")
    for reason in evaluation.reasons:
        st.write(f"- {reason}")
    if evaluation.cheaper_alternative_hint:
        st.info(evaluation.cheaper_alternative_hint)

    st.subheader("Opportunity cost if invested instead")
    cols = st.columns(3)
    for col, (horizon, value) in zip(cols, evaluation.opportunity_cost.items()):
        col.metric(horizon.replace("_", " "), eur(value))
