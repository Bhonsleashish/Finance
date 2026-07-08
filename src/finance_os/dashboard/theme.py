"""Shared visual theme for the dashboard: a validated, colorblind-safe
categorical palette, a sequential ramp, status colors, and a Plotly
template built from them. Imported once (via `_shared.page_setup`) so every
chart on every page gets the same colors instead of Plotly's default
positional cycling — the same category (e.g. "Groceries") is always the
same color no matter which page's chart you're looking at.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# Fixed-order categorical palette (never cycled/re-sorted) — 8 hues, CVD-safe
# at this adjacency order (validated: worst adjacent light-mode contrast
# ΔE 24.2, well clear of the ≥12 target).
CATEGORICAL = [
    "#2a78d6",  # blue
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#008300",  # green
    "#4a3aa7",  # violet
    "#e34948",  # red
    "#e87ba4",  # magenta
    "#eb6834",  # orange
]

# Sequential single-hue ramp (magnitude), light -> dark.
SEQUENTIAL_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#1c5cab", "#0d366b"]

# Diverging pair (polarity): blue (good/positive) <-> gray (neutral) <-> red (bad/negative).
DIVERGING_POSITIVE = "#2a78d6"
DIVERGING_NEUTRAL = "#f0efec"
DIVERGING_NEGATIVE = "#e34948"

# Status palette — reserved; never reused as a categorical slot.
STATUS = {
    "good": "#0ca30c",
    "warning": "#fab219",
    "serious": "#ec835a",
    "critical": "#d03b3b",
}

SURFACE = "#fcfcfb"
PAGE_PLANE = "#f9f9f7"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"

_FONT_FAMILY = "system-ui, -apple-system, 'Segoe UI', sans-serif"


def category_color_map(categories: list[str]) -> dict[str, str]:
    """Stable category -> hex mapping, sorted alphabetically so a given
    category name always lands on the same palette slot across pages,
    independent of row order or how many categories are present."""
    return {cat: CATEGORICAL[i % len(CATEGORICAL)] for i, cat in enumerate(sorted(categories))}


def status_for_ratio(ratio: float, good_max: float = 0.85, warning_max: float = 1.0) -> str:
    """Map a "how much of budget/target used" ratio to a status hex."""
    if ratio <= good_max:
        return STATUS["good"]
    if ratio <= warning_max:
        return STATUS["warning"]
    return STATUS["critical"]


@st.cache_resource(show_spinner=False)
def _apply_plotly_theme() -> None:
    template = go.layout.Template()
    template.layout.colorway = CATEGORICAL
    template.layout.font = dict(family=_FONT_FAMILY, color=INK_PRIMARY, size=13)
    template.layout.paper_bgcolor = SURFACE
    template.layout.plot_bgcolor = SURFACE
    template.layout.hoverlabel = dict(bgcolor="#ffffff", font_size=13, bordercolor=BASELINE)
    template.layout.legend = dict(bgcolor="rgba(0,0,0,0)")
    axis = dict(gridcolor=GRIDLINE, linecolor=BASELINE, zerolinecolor=BASELINE, tickfont=dict(color=INK_SECONDARY))
    template.layout.xaxis = axis
    template.layout.yaxis = axis
    template.layout.margin = dict(l=10, r=10, t=40, b=10)
    pio.templates["financeos"] = template
    pio.templates.default = "financeos"


def apply_theme() -> None:
    """Call once per page (from page_setup): sets the Plotly default
    template and injects card/metric CSS. Cheap to call repeatedly."""
    _apply_plotly_theme()
    st.markdown(
        f"""
        <style>
        [data-testid="stMetric"] {{
            background: {PAGE_PLANE};
            border: 1px solid rgba(11,11,11,0.08);
            border-radius: 10px;
            padding: 14px 16px 10px 16px;
            transition: transform 0.15s ease, box-shadow 0.15s ease;
        }}
        [data-testid="stMetric"]:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 14px rgba(11,11,11,0.08);
            border-color: rgba(42,120,214,0.35);
        }}
        [data-testid="stMetricLabel"] {{
            color: {INK_SECONDARY};
        }}
        div[data-testid="stExpander"] {{
            border-radius: 10px;
            border: 1px solid rgba(11,11,11,0.08);
        }}
        [data-testid="stSidebarNav"] li div a {{
            border-radius: 8px;
        }}
        .fin-card {{
            background: {PAGE_PLANE};
            border: 1px solid rgba(11,11,11,0.08);
            border-left: 4px solid {CATEGORICAL[0]};
            border-radius: 10px;
            padding: 14px 18px;
            margin-bottom: 10px;
        }}
        .fin-badge {{
            display: inline-block;
            padding: 2px 10px;
            border-radius: 999px;
            font-size: 0.8rem;
            font-weight: 600;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def status_badge(label: str, status: str) -> str:
    """Small colored pill, e.g. status_badge('On track', 'good')."""
    color = STATUS.get(status, INK_MUTED)
    return f'<span class="fin-badge" style="background:{color}1a;color:{color};">{label}</span>'
