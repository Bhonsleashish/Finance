from __future__ import annotations

import datetime as dt

import streamlit as st

from finance_os.analysis.goals import all_goals_progress, create_or_update_goal, record_contribution
from finance_os.dashboard._shared import eur, get_conn, page_setup, pct
from finance_os.dashboard.theme import STATUS, status_badge
from finance_os.db import repository as repo

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
            st.rerun()

goals = all_goals_progress(conn)
if not goals:
    st.info("No goals yet — add one above (Emergency Fund is a good place to start).")
    st.stop()

raw_goals = repo.list_goals(conn)  # carries the `id` column, needed for contribute/delete

for g in goals:
    goal_row = raw_goals[raw_goals["name"] == g.name].iloc[0]
    goal_id = int(goal_row["id"])

    badge = ""
    if g.user_target_date:
        badge = status_badge("On track", "good") if g.on_track else status_badge("Behind schedule", "critical")
    elif g.progress_pct >= 1.0:
        badge = status_badge("Complete", "good")
    st.markdown(f"### {g.name}  {badge}", unsafe_allow_html=True)
    progress_color = STATUS["good"] if g.progress_pct >= 0.66 else STATUS["warning"] if g.progress_pct >= 0.33 else STATUS["critical"]
    st.markdown(
        f'<div style="background:#e1e0d9;border-radius:6px;height:10px;overflow:hidden;margin-bottom:8px;">'
        f'<div style="width:{min(g.progress_pct, 1.0) * 100:.1f}%;background:{progress_color};height:100%;"></div></div>',
        unsafe_allow_html=True,
    )
    cols = st.columns(4)
    cols[0].metric("Progress", pct(g.progress_pct))
    cols[1].metric("Current / Target", f"{eur(g.current_amount)} / {eur(g.target_amount)}")
    cols[2].metric("Monthly contribution", eur(g.monthly_contribution))
    cols[3].metric("Est. completion", g.estimated_completion_date.isoformat() if g.estimated_completion_date else "n/a")
    if g.user_target_date:
        status = "on track" if g.on_track else "behind schedule"
        st.caption(f"Target date: {g.user_target_date} — {status}")

    action_cols = st.columns([2, 1])
    with action_cols[0].popover("Add contribution"):
        with st.form(f"contribute_{goal_id}"):
            amount = st.number_input("Amount (EUR)", min_value=0.0, step=25.0, key=f"amt_{goal_id}")
            contributed_on = st.date_input("Date", value=dt.date.today(), key=f"date_{goal_id}")
            do_contribute = st.form_submit_button("Add")
            if do_contribute and amount > 0:
                record_contribution(conn, g.name, amount, contributed_on.isoformat())
                conn.commit()
                st.success(f"Added {eur(amount)} to '{g.name}'.")
                st.rerun()

    with action_cols[1]:
        if st.button("Delete goal", key=f"delete_{goal_id}"):
            repo.deactivate_goal(conn, goal_id)
            conn.commit()
            st.success(f"Deleted '{g.name}'.")
            st.rerun()

    st.divider()
