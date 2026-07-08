from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from finance_os.analysis.subscriptions import detect_subscriptions, persist_subscriptions, total_monthly_subscription_cost
from finance_os.dashboard._shared import eur, get_conn, page_setup
from finance_os.dashboard.theme import CATEGORICAL, STATUS

page_setup("Subscription Tracker")

conn = get_conn()
detected = detect_subscriptions(conn)
persist_subscriptions(conn, detected)
conn.commit()

if not detected:
    st.info("No recurring subscriptions detected yet — need at least two similarly-timed, similarly-sized charges from the same merchant.")
    st.stop()

total = total_monthly_subscription_cost(detected)
col1, col2, col3 = st.columns(3)
col1.metric("Active subscriptions", len([s for s in detected if not s.is_stale]))
col2.metric("Total monthly cost", eur(total))
col3.metric("Annualized", eur(total * 12))

df = pd.DataFrame([{
    "Label": s.label, "Category": s.category, "Monthly cost": s.monthly_cost,
    "Interval (days)": s.interval_days, "Last charged": s.last_seen, "Occurrences": s.occurrences,
    "Status": "stale" if s.is_stale else "active", "Recommend cancel": s.recommend_cancel, "Reason": s.reason,
} for s in detected])

st.subheader("Detected subscriptions")
styled = df.style.map(
    lambda v: f"color: {STATUS['critical']}; font-weight: 600" if v == "stale" else f"color: {STATUS['good']}; font-weight: 600" if v == "active" else "",
    subset=["Status"],
)
st.dataframe(styled, use_container_width=True)

sorted_df = df.sort_values("Monthly cost", ascending=True)
bar_colors = [STATUS["critical"] if s else CATEGORICAL[0] for s in sorted_df["Recommend cancel"]]
fig = px.bar(sorted_df, x="Monthly cost", y="Label", orientation="h")
fig.update_traces(marker_color=bar_colors)
fig.update_layout(height=max(300, 40 * len(sorted_df)))
st.plotly_chart(fig, use_container_width=True)
st.caption("🔴 flagged for cancellation · 🔵 active and in regular use")

recommend = [s for s in detected if s.recommend_cancel]
if recommend:
    st.subheader("Recommended for cancellation")
    for s in recommend:
        st.warning(f"🟠 **{s.label}** ({eur(s.monthly_cost)}/mo) — {s.reason}")
