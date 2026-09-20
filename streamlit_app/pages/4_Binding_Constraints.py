"""Real, live ERCOT binding transmission constraints -- the actual named
grid element driving congestion right now, not a statistical inference
from historical auction prices. Separate, more-recent timeline than the
MIS auction data shown on the other pages -- never implied to be the same
window."""

from __future__ import annotations

import datetime as dt

import streamlit as st

from lib import data_loader
from lib.theme import configure_page, render_data_source_banner

configure_page("Binding Constraints")
st.title("Binding Constraints")
st.caption(
    "The real, named transmission element(s) currently driving congestion, "
    "straight from ERCOT's live Day-Ahead Market shadow-price data -- this "
    "is the physical 'why' behind a congested path, not a statistical guess."
)

records, source, warning = data_loader.get_dataset()
render_data_source_banner(source, warning)

months = sorted({r["auction_month"] for r in records})
latest_month = months[-1] if months else "n/a"

days_back = st.slider("Trailing days", min_value=1, max_value=30, value=7)

result = data_loader.get_binding_constraints(days_back=days_back)

if not result["configured"]:
    st.warning(
        "Live ERCOT data is not configured on this machine. Register for free at "
        "https://apiexplorer.ercot.com/, subscribe to \"Public API\" for a "
        "subscription key, then set ERCOT_API_USERNAME, ERCOT_API_PASSWORD, and "
        "ERCOT_API_SUBSCRIPTION_KEY in backend/.env -- see README for the full steps."
    )
elif result["error"]:
    st.error(f"Couldn't reach ERCOT's live API: {result['error']}")
else:
    today = dt.date.today()
    window_start = today - dt.timedelta(days=days_back)
    st.caption(
        f"Live ERCOT data: {window_start.isoformat()} to {today.isoformat()}. "
        f"The auction data on the other tabs is separate and as of {latest_month} -- "
        "these are two different clocks, shown side by side on purpose."
    )
    if result["truncated"]:
        st.info("This window has more results than fit in one fetch -- showing the first page's worth.")

    constraints = result["constraints"]
    with st.container(border=True):
        search = st.text_input("Search by constraint or station name")
        filtered = constraints
        if search:
            q = search.lower()
            filtered = [
                c for c in constraints
                if q in (c["constraint_name"] or "").lower()
                or q in (c["from_station"] or "").lower()
                or q in (c["to_station"] or "").lower()
            ]
        st.write(f"{len(filtered)} of {len(constraints)} binding constraints in this window")
        st.dataframe(
            [
                {
                    "Date": c["delivery_date"],
                    "Hour Ending": c["hour_ending"],
                    "Constraint": c["constraint_name"],
                    "Contingency": c["contingency_name"],
                    "Shadow Price ($/MW)": c["shadow_price"],
                    "From": c["from_station"],
                    "To": c["to_station"],
                }
                for c in filtered
            ],
            hide_index=True,
            use_container_width=True,
        )
