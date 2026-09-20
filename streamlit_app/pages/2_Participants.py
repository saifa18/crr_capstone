"""Participant analysis: activity ranking plus a per-participant strategy
breakdown (Option/Obligation mix, net Buy/Sell position, top corridors)."""

from __future__ import annotations

import streamlit as st

from lib import data_loader
from lib.theme import configure_page, render_data_source_banner

configure_page("Participants")
st.title("Participants")

records, source, warning = data_loader.get_dataset()
render_data_source_banner(source, warning)

participants = data_loader.get_participants()

with st.container(border=True):
    st.subheader("All Tracked-Pair Participants")
    search = st.text_input("Search by name")
    filtered = [p for p in participants if search.lower() in p["participant"].lower()] if search else participants
    st.dataframe(
        [
            {
                "Participant": p["participant"],
                "Net MW": p["total_awarded_mw"],
                "Notional ($)": p["total_notional"],
                "Distinct Pairs": p["distinct_pairs"],
                "Certificates": p["auction_count"],
            }
            for p in filtered
        ],
        hide_index=True,
        use_container_width=True,
    )

st.divider()
with st.container(border=True):
    st.subheader("Participant Strategy")
    names = [p["participant"] for p in participants]
    if names:
        selected_name = st.selectbox("Participant", names)
        strategy = data_loader.get_participant_strategy(selected_name)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Certificates", strategy["certificate_count"])
        c2.metric("Option / Obligation", f"{strategy['option_pct']}% / {strategy['obligation_pct']}%")
        c3.metric("Net MW Position", strategy["net_mw"])
        c4.metric("Pre-Award Share", f"{strategy['preaward_pct']}%")

        st.caption(
            "Pre-Award share is the portion of this participant's certificates "
            "that were already-held rights carried into this auction rather than "
            "freshly won bids — a high share suggests a buy-and-hold strategy, "
            "a low share suggests active monthly re-bidding."
        )

        st.markdown("**Top Corridors by Notional**")
        st.dataframe(
            [
                {"Source": p["source"], "Sink": p["sink"], "Notional ($)": p["notional"]}
                for p in strategy["top_pairs"]
            ],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No participants in the tracked-pair universe yet.")
