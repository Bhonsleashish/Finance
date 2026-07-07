from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from finance_os.analysis.subscriptions import detect_subscriptions, persist_subscriptions, total_monthly_subscription_cost
from finance_os.dashboard._shared import eur, get_conn, page_setup

page_setup("Subscription Tracker")

conn = get_conn()
detected = detect_subscriptions(conn)
persist_subscriptions(conn, detected)
conn.commit()

if not detected:
    st.info("No recurring subscriptions detected yet — need at least two similarly-timed, similarly-sized charges from the same merchant.")
    st.stop()

total = total_monthly_subscription_cost(detected)
col1, col2 = st.columns(2)
col1.metric("Active subscriptions", len([s for s in detected if not s.is_stale]))
col2.metric("Total monthly cost", eur(total))
st.caption(f"Annualized: {eur(total * 12)}")

df = pd.DataFrame([{
    "Label": s.label, "Category": s.category, "Monthly cost": s.monthly_cost,
    "Interval (days)": s.interval_days, "Last charged": s.last_seen, "Occurrences": s.occurrences,
    "Status": "stale" if s.is_stale else "active", "Recommend cancel": s.recommend_cancel, "Reason": s.reason,
} for s in detected])

st.subheader("Detected subscriptions")
st.dataframe(df, use_container_width=True)

fig = px.bar(df.sort_values("Monthly cost", ascending=True), x="Monthly cost", y="Label", orientation="h")
st.plotly_chart(fig, use_container_width=True)

recommend = [s for s in detected if s.recommend_cancel]
if recommend:
    st.subheader("Recommended for cancellation")
    for s in recommend:
        st.warning(f"**{s.label}** ({eur(s.monthly_cost)}/mo) — {s.reason}")
