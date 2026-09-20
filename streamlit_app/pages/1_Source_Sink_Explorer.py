"""Source/Sink Explorer -- historical pricing, congestion trends, and
active participants for one tracked CRR corridor at a time."""

from __future__ import annotations

import csv
import io

import streamlit as st

from lib import data_loader
from lib.theme import configure_page, render_data_source_banner

configure_page("Source/Sink Explorer")
st.title("Source/Sink Explorer")

records, source, warning = data_loader.get_dataset()
render_data_source_banner(source, warning)

from app import analytics  # noqa: E402  (backend path already on sys.path via data_loader import)

tracked_records, top_pairs = data_loader.get_tracked_records()
pair_labels = [f"{p['source']} → {p['sink']}" for p in top_pairs]
choice = st.selectbox("Corridor", pair_labels)
selected = top_pairs[pair_labels.index(choice)]
src, snk = selected["source"], selected["sink"]

tou_choice = st.radio("Time of Use", ["ALL", "PEAK_WD", "PEAK_WE", "OFF_PEAK"], horizontal=True)
tou_filter = None if tou_choice == "ALL" else tou_choice

obligation_records = analytics.filter_records(
    tracked_records, source=src, sink=snk, crr_type="OBLIGATION", time_of_use=tou_filter
)
option_records = analytics.filter_records(
    tracked_records, source=src, sink=snk, crr_type="OPTION", time_of_use=tou_filter
)
obligation_series = analytics.monthly_price_series(obligation_records)
option_series = analytics.monthly_price_series(option_records)
metrics = analytics.basic_metrics(obligation_records)

st.subheader(f"{src} → {snk} ({tou_choice})")

if obligation_series or option_series:
    from lib.theme import COLORS
    import plotly.graph_objects as go

    fig = go.Figure()
    if obligation_series:
        fig.add_trace(go.Scatter(
            x=[s["auction_month"] for s in obligation_series],
            y=[s["avg_clearing_price"] for s in obligation_series],
            mode="lines+markers",
            name="Obligation",
            line=dict(color=COLORS["obligation"], width=2),
        ))
    if option_series:
        fig.add_trace(go.Scatter(
            x=[s["auction_month"] for s in option_series],
            y=[s["avg_clearing_price"] for s in option_series],
            mode="lines+markers",
            name="Option",
            line=dict(color=COLORS["option"], width=2),
        ))
    fig.update_layout(
        xaxis_title="Auction Month",
        yaxis_title="Avg Clearing Price ($/MWh)",
        height=400,
        hovermode="x unified",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No records for this pair/filter combination.")

st.caption("Metrics below are computed on Obligation records — the direct economic-value signal (see scoring.py).")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Average", metrics["average"])
m2.metric("Trailing 12mo Avg", metrics["trailing_12mo_average"])
m3.metric("Volatility", metrics["volatility"])
m4.metric("% Months Negative", metrics["pct_months_negative"])

st.divider()
st.subheader("Active Participants on This Pair")
pair_all_records = analytics.filter_records(tracked_records, source=src, sink=snk)
pair_participants = analytics.participant_summary(pair_all_records)
st.dataframe(
    [
        {
            "Participant": p["participant"],
            "Net MW": p["total_awarded_mw"],
            "Notional ($)": p["total_notional"],
            "Certificates": p["auction_count"],
        }
        for p in pair_participants[:15]
    ],
    hide_index=True,
    width="stretch",
)

if obligation_series:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["auction_month", "obligation_avg_clearing_price", "option_avg_clearing_price"])
    option_by_month = {s["auction_month"]: s["avg_clearing_price"] for s in option_series}
    for row in obligation_series:
        writer.writerow([
            row["auction_month"],
            row["avg_clearing_price"],
            option_by_month.get(row["auction_month"], ""),
        ])
    st.download_button("Download CSV", buf.getvalue(), file_name=f"{src}_{snk}_series.csv")
