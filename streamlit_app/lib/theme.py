"""Shared page chrome for every Streamlit page: page config, a consistent
dark trading-terminal look, and the data-source banner every page shows so
nobody mistakes which tier (real bulk data / SQL / dropped CSV /
synthetic) is currently on screen."""

from __future__ import annotations

import streamlit as st

PAGE_ICON = "⚡"

_CSS = """
<style>
.crr-banner {
    padding: 0.6rem 1rem;
    border-radius: 6px;
    margin-bottom: 1rem;
    font-size: 0.9rem;
}
.crr-banner-real { background-color: #113322; border: 1px solid #1f6f43; color: #b7f0cf; }
.crr-banner-synthetic { background-color: #332a11; border: 1px solid #8a6d1f; color: #f0dfae; }
.crr-banner-warning { background-color: #3a1414; border: 1px solid #8a2f2f; color: #f5b8b8; }
</style>
"""


def configure_page(title: str) -> None:
    st.set_page_config(page_title=f"{title} | ERCOT CRR Analytics", page_icon=PAGE_ICON, layout="wide")
    st.markdown(_CSS, unsafe_allow_html=True)


def render_data_source_banner(source: str, warning: str | None) -> None:
    if warning:
        st.markdown(f'<div class="crr-banner crr-banner-warning">⚠ {warning}</div>', unsafe_allow_html=True)
    if source == "synthetic_demo":
        st.markdown(
            '<div class="crr-banner crr-banner-synthetic">'
            "Showing <b>synthetic demo data</b> — no real ERCOT auction files were found. "
            "Run <code>python backend/scripts/fetch_real_ercot_data.py</code> to pull real data."
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="crr-banner crr-banner-real">'
            f"Showing <b>real ERCOT data</b> (source: <code>{source}</code>)."
            "</div>",
            unsafe_allow_html=True,
        )
