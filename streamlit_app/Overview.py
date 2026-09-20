"""ERCOT CRR Market Analytics -- Overview (Streamlit entry point).

Run with: `streamlit run streamlit_app/Overview.py` from the project root.
"""

from __future__ import annotations

import streamlit as st
import plotly.express as px

from lib import data_loader
from lib.theme import configure_page, render_data_source_banner, COLORS

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

prior_month = months[-2] if len(months) >= 2 else None
prior_records = [r for r in records if r["auction_month"] == prior_month] if prior_month else []
latest_mw = sum(r["awarded_mw"] for r in latest_records)
prior_mw = sum(r["awarded_mw"] for r in prior_records) if prior_records else None
mw_delta = f"{latest_mw - prior_mw:,.0f} vs prior month" if prior_mw is not None else None

with st.container(border=True):
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Latest Auction Month", latest_month)
    col2.metric("Active Participants", len({r["participant"] for r in records}))
    col3.metric("Tracked Pairs", len(top_pairs))
    col4.metric("Latest Month MW Awarded", f"{latest_mw:,.0f}", mw_delta)

st.divider()

with st.container(border=True):
    st.subheader("Corridor Map")
    st.caption("Tracked hubs and load zones, sized by how many of the top-30 corridors touch that point.")
    map_points = data_loader.get_corridor_map_points()
    if map_points:
        import plotly.express as px_map
        fig_map = px_map.scatter_geo(
            map_points,
            lat="lat",
            lon="lon",
            size="pair_count",
            hover_name="name",
            hover_data={"code": True, "pair_count": True, "lat": False, "lon": False},
            scope="usa",
            color_discrete_sequence=[COLORS["tier_high"]],
        )
        fig_map.update_geos(center={"lat": 31.0, "lon": -99.0}, projection_scale=4, showland=True, landcolor="#1a1f26")
        fig_map.update_layout(
            margin=dict(l=0, r=0, t=0, b=0),
            height=350,
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_map, width="stretch")
    else:
        st.info("No tracked corridors have a known map location yet.")

st.divider()

left, right = st.columns([3, 2])

with left:
    with st.container(border=True):
        st.subheader("Hot Paths")
        st.caption("The most active Source/Sink corridors, ranked by gross notional activity.")
        for p in hot_paths:
            st.markdown(f"**{p['source']} → {p['sink']}** — {p['reason']}")

with right:
    with st.container(border=True):
        st.subheader("Opportunity Tier Distribution")
        tier_counts = {"High": 0, "Medium": 0, "Low": 0}
        for s in scores:
            tier_counts[s["tier"]] = tier_counts.get(s["tier"], 0) + 1
        fig = px.bar(
            x=list(tier_counts.keys()),
            y=list(tier_counts.values()),
            color=list(tier_counts.keys()),
            color_discrete_map={
                "High": COLORS["tier_high"],
                "Medium": COLORS["tier_medium"],
                "Low": COLORS["tier_low"],
            },
            labels={"x": "Tier", "y": "Pair Count"},
        )
        fig.update_layout(
            showlegend=False,
            height=300,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig, width="stretch")

st.divider()
with st.container(border=True):
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
with st.container(border=True):
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
