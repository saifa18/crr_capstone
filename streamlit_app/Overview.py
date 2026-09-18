"""ERCOT CRR Market Analytics -- Overview (Streamlit entry point).

Run with: `streamlit run streamlit_app/Overview.py` from the project root.
"""

from __future__ import annotations

import streamlit as st

from lib import data_loader
from lib.theme import configure_page, render_data_source_banner

configure_page("Overview")

st.title("ERCOT CRR Market Analytics")
st.caption(
    "Market intelligence for ERCOT Congestion Revenue Rights — participant "
    "activity, Source/Sink pricing history, and an explainable opportunity "
    "signal. This is analytics tooling, not trading advice."
)

records, source, warning = data_loader.get_dataset()
render_data_source_banner(source, warning)

tracked_records, top_pairs = data_loader.get_tracked_records()
scores = data_loader.get_scores()
participants = data_loader.get_participants()
hot_paths = data_loader.get_hot_paths()

months = sorted({r["auction_month"] for r in records})
latest_month = months[-1] if months else "n/a"
latest_records = [r for r in records if r["auction_month"] == latest_month]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Latest Auction Month", latest_month)
col2.metric("Active Participants", len({r["participant"] for r in records}))
col3.metric("Tracked Pairs", len(top_pairs))
col4.metric("Latest Month MW Awarded", f"{sum(r['awarded_mw'] for r in latest_records):,.0f}")

st.divider()

left, right = st.columns([3, 2])

with left:
    st.subheader("Hot Paths")
    st.caption("The most active Source/Sink corridors, ranked by gross notional activity.")
    for p in hot_paths:
        st.markdown(f"**{p['source']} → {p['sink']}** — {p['reason']}")

with right:
    st.subheader("Opportunity Tier Distribution")
    tier_counts = {"High": 0, "Medium": 0, "Low": 0}
    for s in scores:
        tier_counts[s["tier"]] = tier_counts.get(s["tier"], 0) + 1
    st.bar_chart(tier_counts)

st.divider()
st.subheader("Top Participants by Notional")
st.dataframe(
    [
        {
            "Participant": p["participant"],
            "Net MW": p["total_awarded_mw"],
            "Notional ($)": p["total_notional"],
            "Distinct Pairs": p["distinct_pairs"],
            "Certificates": p["auction_count"],
        }
        for p in participants[:10]
    ],
    hide_index=True,
    width="stretch",
)

st.divider()
st.subheader("Weather Context by ERCOT Zone")
st.caption(
    "Wind at West Texas/Panhandle and temperature-driven load at Coast/North "
    "are physical drivers of the congestion these corridors measure — shown "
    "as context, not a forecast of CRR value or a scoring input."
)
weather = data_loader.get_weather_zone_snapshot()
cols = st.columns(4)
for i, entry in enumerate(weather):
    with cols[i % 4]:
        if entry["error"]:
            st.error(f"{entry['zone']}: couldn't reach Open-Meteo")
        else:
            st.metric(
                f"{entry['zone']} ({entry['city']})",
                f"{entry['temperature_f']:.0f}°F",
                f"wind {entry['wind_mph']:.0f} mph",
            )
