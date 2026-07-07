from __future__ import annotations

import streamlit as st

from finance_os.analysis.goals import all_goals_progress, create_or_update_goal
from finance_os.dashboard._shared import eur, get_conn, page_setup, pct

page_setup("Goals")

conn = get_conn()

with st.expander("Add / update a goal"):
    with st.form("goal_form"):
        name = st.text_input("Name")
        goal_type = st.selectbox("Type", [
            "emergency_fund", "debt_payoff", "vacation", "car", "move_countries",
            "investment", "retirement", "custom",
        ])
        target_amount = st.number_input("Target amount (EUR)", min_value=0.0, step=100.0)
        current_amount = st.number_input("Current amount (EUR)", min_value=0.0, step=50.0)
        monthly_contribution = st.number_input("Planned monthly contribution (EUR)", min_value=0.0, step=25.0)
        target_date = st.date_input("Target date (optional)", value=None)
        submitted = st.form_submit_button("Save goal")
        if submitted and name:
            create_or_update_goal(
                conn, name, goal_type, target_amount, current_amount, monthly_contribution,
                target_date.isoformat() if target_date else None,
            )
            conn.commit()
            st.success(f"Goal '{name}' saved.")
            st.cache_resource.clear()

goals = all_goals_progress(conn)
if not goals:
    st.info("No goals yet — add one above (Emergency Fund is a good place to start).")
    st.stop()

for g in goals:
    st.subheader(g.name)
    st.progress(min(g.progress_pct, 1.0))
    cols = st.columns(4)
    cols[0].metric("Progress", pct(g.progress_pct))
    cols[1].metric("Current / Target", f"{eur(g.current_amount)} / {eur(g.target_amount)}")
    cols[2].metric("Monthly contribution", eur(g.monthly_contribution))
    cols[3].metric("Est. completion", g.estimated_completion_date.isoformat() if g.estimated_completion_date else "n/a")
    if g.user_target_date:
        status = "✅ on track" if g.on_track else "⚠️ behind schedule"
        st.caption(f"Target date: {g.user_target_date} — {status}")
    st.divider()
