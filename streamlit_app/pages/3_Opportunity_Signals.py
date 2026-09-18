"""Explainable Low/Medium/High opportunity score for every tracked
Source/Sink pair -- a transparent composite of historical descriptive
statistics, not a prediction or a bidding recommendation."""

from __future__ import annotations

import streamlit as st

from lib import data_loader
from lib.theme import configure_page, render_data_source_banner

configure_page("Opportunity Signals")
st.title("Opportunity Signals")
st.caption(
    "Market intelligence, not trading advice — every score below is a "
    "transparent composite of four named, weighted historical factors."
)

records, source, warning = data_loader.get_dataset()
render_data_source_banner(source, warning)

scores = data_loader.get_scores()

tier_filter = st.radio("Tier", ["All", "High", "Medium", "Low"], horizontal=True)
search = st.text_input("Search by hub/zone name or code")

filtered = scores
if tier_filter != "All":
    filtered = [s for s in filtered if s["tier"] == tier_filter]
if search:
    q = search.lower()
    filtered = [
        s for s in filtered
        if q in s["source"].lower() or q in s["sink"].lower()
        or q in s["source_name"].lower() or q in s["sink_name"].lower()
    ]

st.write(f"{len(filtered)} of {len(scores)} tracked pairs")

for s in filtered:
    with st.expander(f"{s['source']} → {s['sink']}  —  {s['tier']} ({s['score']})"):
        f1, f2, f3, f4 = st.columns(4)
        f1.metric("Value", s["factors"]["value"]["score"])
        f2.metric("Trend", s["factors"]["trend"]["score"])
        f3.metric("Consistency", s["factors"]["consistency"]["score"])
        f4.metric("Liquidity", s["factors"]["liquidity"]["score"])
        for line in s["explanation"]:
            st.write(f"- {line}")
