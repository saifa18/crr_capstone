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
crr_type_choice = st.radio("CRR Type", ["OBLIGATION", "OPTION"], horizontal=True)

pair_records = analytics.filter_records(
    tracked_records,
    source=src,
    sink=snk,
    crr_type=crr_type_choice,
    time_of_use=None if tou_choice == "ALL" else tou_choice,
)

series = analytics.monthly_price_series(pair_records)
metrics = analytics.basic_metrics(pair_records)

st.subheader(f"{src} → {snk} ({crr_type_choice}, {tou_choice})")
if series:
    st.line_chart({s["auction_month"]: s["avg_clearing_price"] for s in series})
else:
    st.info("No records for this pair/filter combination.")

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

if series:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["auction_month", "avg_clearing_price"])
    for row in series:
        writer.writerow([row["auction_month"], row["avg_clearing_price"]])
    st.download_button("Download CSV", buf.getvalue(), file_name=f"{src}_{snk}_series.csv")
