"""Finance OS dashboard — Overview page.

Run with: finance dashboard   (or: streamlit run src/finance_os/dashboard/app.py)
Everything renders from the local SQLite database; the app binds to
localhost only and makes no outbound network calls.
"""

from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from finance_os.analysis.alerts import evaluate_alerts
from finance_os.analysis.cashflow import monthly_summary, spending_by_category
from finance_os.analysis.health_score import compute_health_score
from finance_os.analysis.investments import portfolio_summary
from finance_os.analysis.networth import estimate_net_worth_from_cashflow, net_worth_trend
from finance_os.analysis.salary import estimate_month_income
from finance_os.dashboard._shared import eur, get_conn, page_setup, pct
from finance_os.dashboard.theme import CATEGORICAL, STATUS, category_color_map
from finance_os.utils.dates import current_period_month

page_setup("Overview")

conn = get_conn()
summary = monthly_summary(conn)

if summary.empty:
    st.info("No data yet. Run `finance ingest data/inbox` (or point it at a payslip/statement/CSV) to get started.")
    st.stop()

months = summary["period_month"].tolist()
default_month = current_period_month() if current_period_month() in months else months[-1]
selected_month = st.selectbox("Month", options=months[::-1], index=months[::-1].index(default_month) if default_month in months else 0)

row = summary[summary["period_month"] == selected_month].iloc[0]
month_idx = months.index(selected_month)
prev_row = summary.iloc[month_idx - 1] if month_idx > 0 else None


def _delta(key: str, fmt: str = "eur") -> str | None:
    if prev_row is None or prev_row[key] == 0:
        return None
    change = row[key] - prev_row[key]
    if fmt == "eur":
        return f"{change:+,.2f} EUR vs last month"
    return f"{change:+.1%} vs last month"


col1, col2, col3, col4 = st.columns(4)
col1.metric("Income", eur(row["income"]), delta=_delta("income"))
col2.metric("Expenses", eur(row["expenses"]), delta=_delta("expenses"), delta_color="inverse")
col3.metric("Net cash flow", eur(row["net_cashflow"]), delta=_delta("net_cashflow"))
col4.metric("Savings rate", pct(row["savings_rate"]), delta=_delta("savings_rate", fmt="pct"))

if selected_month == current_period_month():
    income_est = estimate_month_income(conn, selected_month)
    ic1, ic2, ic3 = st.columns(3)
    ic1.metric("Received so far this month", eur(income_est.received_so_far))
    ic2.metric("Remaining expected", eur(income_est.remaining_expected))
    ic3.metric("Estimated total income", eur(income_est.estimated_total))
    st.caption(f"Estimate basis: {income_est.basis.replace('_', ' ')}")

st.subheader("Cash flow trend")
fig = go.Figure()
fig.add_bar(x=summary["period_month"], y=summary["income"], name="Income", marker_color=CATEGORICAL[0])
fig.add_bar(x=summary["period_month"], y=-summary["expenses"], name="Expenses", marker_color=CATEGORICAL[5])
fig.add_scatter(x=summary["period_month"], y=summary["net_cashflow"], name="Net cash flow",
                 mode="lines+markers", line=dict(color="#0b0b0b", width=2), marker=dict(size=8))
fig.update_layout(barmode="relative", height=400, hovermode="x unified", legend=dict(orientation="h", y=1.12))
st.plotly_chart(fig, use_container_width=True)

col_a, col_b = st.columns(2)

with col_a:
    st.subheader(f"Spending by category — {selected_month}")
    cat_df = spending_by_category(conn, selected_month)
    if not cat_df.empty:
        colors = category_color_map(cat_df["category"].tolist())
        fig2 = px.pie(cat_df, names="category", values="total", hole=0.45,
                       color="category", color_discrete_map=colors)
        fig2.update_traces(textinfo="label+percent", textposition="outside")
        fig2.update_layout(showlegend=False, height=380)
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.write("No expenses recorded this month.")

with col_b:
    st.subheader("Net worth trend")
    nw = net_worth_trend(conn)
    if nw.empty:
        nw = estimate_net_worth_from_cashflow(conn)
        if not nw.empty:
            st.caption("No net-worth snapshots recorded — showing cumulative cash flow as an estimate.")
            fig3 = px.line(nw, x="period_month", y="estimated_net_worth")
            fig3.update_traces(line=dict(color=CATEGORICAL[0], width=3), fill="tozeroy",
                                fillcolor="rgba(42,120,214,0.08)")
            fig3.update_layout(height=380)
            st.plotly_chart(fig3, use_container_width=True)
    else:
        fig3 = px.line(nw, x="snapshot_date", y="net_worth")
        fig3.update_traces(line=dict(color=CATEGORICAL[0], width=3), fill="tozeroy",
                            fillcolor="rgba(42,120,214,0.08)")
        fig3.update_layout(height=380)
        st.plotly_chart(fig3, use_container_width=True)

portfolio = portfolio_summary(conn)
if portfolio.holdings_count:
    st.subheader("Investments")
    pc1, pc2, pc3 = st.columns(3)
    pc1.metric("Invested", eur(portfolio.total_invested))
    pc2.metric("Current value", eur(portfolio.total_current_value))
    gain_label = f"{portfolio.unrealized_gain_pct:+.1%}" if portfolio.unrealized_gain_pct is not None else None
    pc3.metric("Unrealized gain/loss", eur(portfolio.unrealized_gain), delta=gain_label)
    if portfolio.stale_value_count:
        st.caption(f"{portfolio.stale_value_count} holding(s) still valued at cost — update on the Investments page.")

st.subheader("Financial health score")
health = compute_health_score(conn, selected_month)
score_status = "good" if health.total >= 70 else "warning" if health.total >= 40 else "critical"
c1, c2 = st.columns([1, 2])
with c1:
    gauge = go.Figure(go.Indicator(
        mode="gauge+number", value=health.total,
        number={"suffix": " / 100", "font": {"color": STATUS[score_status]}},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": STATUS[score_status]},
            "steps": [
                {"range": [0, 40], "color": "#fbe3e0"},
                {"range": [40, 70], "color": "#fdeecb"},
                {"range": [70, 100], "color": "#d9f0d9"},
            ],
        },
    ))
    gauge.update_layout(height=260, margin=dict(l=20, r=20, t=30, b=10))
    st.plotly_chart(gauge, use_container_width=True)
with c2:
    for name, comp in health.components.items():
        comp_status = "good" if comp["score"] >= 70 else "warning" if comp["score"] >= 40 else "critical"
        st.markdown(
            f"**{name.replace('_', ' ').title()}** "
            f'<span style="color:{STATUS[comp_status]}; font-weight:700;">{comp["score"]:.0f}/100</span>',
            unsafe_allow_html=True,
        )
        st.progress(min(comp["score"] / 100, 1.0))
        st.caption(comp["detail"])

st.subheader("Smart alerts")
alerts = evaluate_alerts(conn, selected_month)
if not alerts:
    st.success("✅ No alerts for this month.")
else:
    icons = {"critical": "🔴", "warning": "🟠", "info": "🔵"}
    for alert in alerts:
        level = {"critical": st.error, "warning": st.warning, "info": st.info}.get(alert["severity"], st.info)
        level(f"{icons.get(alert['severity'], '🔵')} {alert['message']}")
