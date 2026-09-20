# Visual Polish + Binding Constraints Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Streamlit's built-in charts with Plotly across the app for real legends and multi-series overlays (Obligation + Option on one chart), add a consistent color system and card-style layout, add an ERCOT corridor map, and add a new Binding Constraints tab powered by ERCOT's live Public API — capped, cached, and fail-open exactly like the existing weather panel.

**Architecture:** Pure frontend/UI-layer work plus one new `data_loader.py` function. No backend Python module (`analytics.py`, `scoring.py`, `ingestion.py`) changes at all — this plan only touches `streamlit_app/` and reuses `backend/app/ercot_live.py`/`live_congestion.py`, both already built and tested from the earlier round.

**Tech Stack:** Plotly (`plotly.express`, `plotly.graph_objects`) via `st.plotly_chart`, added to `streamlit_app/requirements.txt`.

## Global Constraints

- No changes to any `backend/app/*.py` file's logic in this plan — only `streamlit_app/` files change, plus `docs/triple_check_review.md` for the final persona-review round.
- Obligation is always color `#2ecc71` (green) and Option is always `#f39c12` (amber), everywhere either appears, sourced from one shared `streamlit_app/lib/theme.py` constant — never a hardcoded color literal duplicated in a page file.
- Tier colors: High `#2ecc71`, Medium `#f39c12`, Low `#7f8c8d` — same rule, one shared source.
- The Binding Constraints tab must default to a 7-day trailing window, allow the user to widen it, but cap the widest allowed window at 30 days.
- The Binding Constraints tab must fail open: "not configured" and "API error" states render a clear message and the rest of the page still works — never a crash, never a blank page. This mirrors the existing weather panel's pattern in `streamlit_app/Overview.py`.
- The Binding Constraints tab's live data must be clearly time-stamped as a separate, more-recent window than the MIS auction data shown elsewhere in the app — never implied to be the same timeline.
- Every existing backend test (136 as of the last commit on this branch) must keep passing unmodified — nothing in this plan touches files those tests cover.

---

### Task 1: Shared color palette + `plotly` dependency

**Files:**
- Modify: `streamlit_app/lib/theme.py` (append a new module-level constant)
- Modify: `streamlit_app/requirements.txt` (add `plotly`)

**Interfaces:**
- Consumes: nothing new
- Produces: `theme.COLORS: dict[str, str]` with keys `obligation`, `option`, `tier_high`, `tier_medium`, `tier_low` — every later task in this plan imports and uses this, never a hardcoded hex color.

- [ ] **Step 1: Add the color palette to `theme.py`**

Append to `streamlit_app/lib/theme.py` (after the existing `PAGE_ICON = "⚡"` line, before `_CSS`):

```python
# Fixed color-to-meaning mapping used everywhere a chart or badge needs
# one of these concepts -- Obligation is always this exact green, Option
# is always this exact amber, tiers are always these three colors, on
# every page. Never hardcode these hex values anywhere else.
COLORS = {
    "obligation": "#2ecc71",
    "option": "#f39c12",
    "tier_high": "#2ecc71",
    "tier_medium": "#f39c12",
    "tier_low": "#7f8c8d",
}
```

- [ ] **Step 2: Add `plotly` to the Streamlit app's requirements**

In `streamlit_app/requirements.txt`, add a new line:

```
plotly==5.24.1
```

Full expected file content after this change:
```
streamlit==1.38.0
requests==2.32.3
plotly==5.24.1
```

- [ ] **Step 3: Install and verify**

```bash
cd /Users/saif_ansari/Downloads/ercot-crr-analytics
pip install -r streamlit_app/requirements.txt
python3 -c "import plotly; from lib import theme" 2>&1 | tail -5
```
(Run the second command with `PYTHONPATH=streamlit_app` if it can't find `lib`, e.g. `cd streamlit_app && python3 -c "from lib import theme; print(theme.COLORS)"`.)
Expected: no import errors, and `theme.COLORS` prints the 5-key dict.

- [ ] **Step 4: Commit**

```bash
git add streamlit_app/lib/theme.py streamlit_app/requirements.txt
git commit -m "feat: add shared color palette and plotly dependency"
```

---

### Task 2: Overview page — KPI deltas, bordered sections, Plotly tier chart

**Files:**
- Modify: `streamlit_app/Overview.py` (full rewrite of the metrics/tier-chart section)

**Interfaces:**
- Consumes: `theme.COLORS` (Task 1), existing `data_loader.get_dataset/get_tracked_records/get_scores/get_participants/get_hot_paths/get_weather_zone_snapshot` (all pre-existing, unchanged)
- Produces: nothing new consumed by later tasks (Task 3 adds to this same file separately)

- [ ] **Step 1: Replace the KPI row and tier chart section**

In `streamlit_app/Overview.py`, replace everything from `col1, col2, col3, col4 = st.columns(4)` (line 34) through the end of the tier-distribution `with right:` block (line 55) with:

```python
from lib.theme import COLORS
import plotly.express as px

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
```

- [ ] **Step 2: Wrap the remaining sections (participants, weather) in bordered containers**

Replace the rest of the file (everything from `st.divider()` / `st.subheader("Top Participants by Notional")` onward, i.e. the current lines 57-93) with:

```python
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
```

- [ ] **Step 3: Verify the file parses and imports correctly**

```bash
cd /Users/saif_ansari/Downloads/ercot-crr-analytics
python3 -c "import ast; ast.parse(open('streamlit_app/Overview.py').read())" && echo "syntax OK"
```

- [ ] **Step 4: Commit**

```bash
git add streamlit_app/Overview.py
git commit -m "feat: KPI deltas, bordered sections, Plotly tier chart on Overview"
```

---

### Task 3: Overview page — ERCOT corridor map

**Files:**
- Modify: `streamlit_app/lib/data_loader.py` (add `_settlement_point_coordinates` and `get_corridor_map_points`)
- Modify: `streamlit_app/Overview.py` (add the map section)

**Interfaces:**
- Consumes: `weather_zones.WEATHER_ZONES` (each `WeatherZone` has `.latitude`, `.longitude`, `.hubs: tuple[str,...]`, `.load_zones: tuple[str,...]` — already built), `get_tracked_records()` (existing), `_settlement_point_name()` (existing private helper in `data_loader.py`)
- Produces: `data_loader.get_corridor_map_points() -> list[dict]`, each dict with keys `code`, `name`, `lat`, `lon`, `pair_count` — consumed only by `Overview.py` in this plan.

- [ ] **Step 1: Add the coordinate lookup and map-points function to `data_loader.py`**

Append to `streamlit_app/lib/data_loader.py` (after `get_weather_zone_seasonality`, at the end of the file):

```python
def _settlement_point_coordinates() -> dict[str, tuple[float, float]]:
    """Borrows each real hub/load-zone code's map location from the
    weather zone it's associated with in weather_zones.py -- there's no
    separate lat/lon table to maintain, and it stays consistent with
    whatever zone mapping that module already documents."""
    coords: dict[str, tuple[float, float]] = {}
    for zone in weather_zones.WEATHER_ZONES:
        for code in zone.hubs + zone.load_zones:
            coords.setdefault(code, (zone.latitude, zone.longitude))
    return coords


@st.cache_data(ttl=3600)
def get_corridor_map_points() -> list[dict]:
    """One row per real hub/load-zone code appearing in the tracked top
    pairs, with a map location and how many tracked pairs touch that
    point. Points with no known coordinate (e.g. a resource-node code with
    no weather-zone mapping) are omitted entirely rather than plotted at
    (0, 0), which would be misleading."""
    _, top_pairs = get_tracked_records()
    coords = _settlement_point_coordinates()
    counts: dict[str, int] = {}
    for p in top_pairs:
        for code in (p["source"], p["sink"]):
            counts[code] = counts.get(code, 0) + 1

    out = []
    for code, count in counts.items():
        if code not in coords:
            continue
        lat, lon = coords[code]
        out.append({
            "code": code,
            "name": _settlement_point_name(code),
            "lat": lat,
            "lon": lon,
            "pair_count": count,
        })
    return out
```

- [ ] **Step 2: Verify it returns real data**

```bash
cd /Users/saif_ansari/Downloads/ercot-crr-analytics
python3 -c "
import sys
sys.path.insert(0, 'streamlit_app')
from lib import data_loader
points = data_loader.get_corridor_map_points.__wrapped__()
print('map points:', len(points))
for p in points[:5]:
    print(p)
"
```
Expected: at least a few points (the tracked top-30 pairs are dominated by real hub/load-zone codes, which all have weather-zone coordinates), each with real `lat`/`lon` values and a `pair_count` >= 1.

- [ ] **Step 3: Add the map section to `Overview.py`**

In `streamlit_app/Overview.py`, add this new section right after the KPI row's `st.divider()` (i.e., between the KPI container from Task 2 Step 1 and the `left, right = st.columns([3, 2])` line):

```python
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
```

(This section's own `st.divider()` at the end replaces the one that used to precede `left, right = st.columns([3, 2])` — do not create two dividers in a row.)

- [ ] **Step 4: Verify the file parses**

```bash
python3 -c "import ast; ast.parse(open('streamlit_app/Overview.py').read())" && echo "syntax OK"
```

- [ ] **Step 5: Commit**

```bash
git add streamlit_app/lib/data_loader.py streamlit_app/Overview.py
git commit -m "feat: add ERCOT corridor map to Overview page"
```

---

### Task 4: Explorer page — combined Obligation/Option chart

**Files:**
- Modify: `streamlit_app/pages/1_Source_Sink_Explorer.py` (full rewrite of the chart/filter section)

**Interfaces:**
- Consumes: `theme.COLORS` (Task 1), existing `analytics.filter_records`, `analytics.monthly_price_series`, `analytics.basic_metrics`, `analytics.participant_summary` (all pre-existing, unchanged)
- Produces: nothing new consumed by later tasks

- [ ] **Step 1: Replace the CRR-type radio and single-series chart with a dual-series Plotly chart**

In `streamlit_app/pages/1_Source_Sink_Explorer.py`, replace lines 28-52 (from `tou_choice = st.radio(...)` through the `m4.metric(...)` line) with:

```python
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
    st.plotly_chart(fig, width="stretch")
else:
    st.info("No records for this pair/filter combination.")

st.caption("Metrics below are computed on Obligation records — the direct economic-value signal (see scoring.py).")
m1, m2, m3, m4 = st.columns(4)
m1.metric("Average", metrics["average"])
m2.metric("Trailing 12mo Avg", metrics["trailing_12mo_average"])
m3.metric("Volatility", metrics["volatility"])
m4.metric("% Months Negative", metrics["pct_months_negative"])
```

Note: this removes the `crr_type_choice = st.radio("CRR Type", ...)` line entirely (both series always show now) and the old `pair_records`/`series` variables (replaced by `obligation_records`/`option_records`/`obligation_series`/`option_series`).

- [ ] **Step 2: Fix the CSV download section, which referenced the now-removed `series` variable**

Replace the file's last block (originally lines 72-78, `if series: ... st.download_button(...)`) with:

```python
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
```

- [ ] **Step 3: Verify the file parses**

```bash
cd /Users/saif_ansari/Downloads/ercot-crr-analytics
python3 -c "import ast; ast.parse(open('streamlit_app/pages/1_Source_Sink_Explorer.py').read())" && echo "syntax OK"
```

- [ ] **Step 4: Verify against real data (no live Streamlit runtime needed)**

```bash
cd /Users/saif_ansari/Downloads/ercot-crr-analytics
python3 -c "
import sys
sys.path.insert(0, 'streamlit_app')
from lib import data_loader
sys.path.insert(0, 'backend')
from app import analytics

tracked_records, top_pairs = data_loader.get_tracked_records.__wrapped__()
p = top_pairs[0]
src, snk = p['source'], p['sink']
obligation_records = analytics.filter_records(tracked_records, source=src, sink=snk, crr_type='OBLIGATION')
option_records = analytics.filter_records(tracked_records, source=src, sink=snk, crr_type='OPTION')
print('obligation rows:', len(obligation_records), 'option rows:', len(option_records))
print('obligation series len:', len(analytics.monthly_price_series(obligation_records)))
print('option series len:', len(analytics.monthly_price_series(option_records)))
"
```
Expected: non-zero counts for at least one of the two series on a real top-30 pair (some pairs may have thin Option activity, that's fine and expected — the page's `st.info` fallback only fires if BOTH are empty).

- [ ] **Step 5: Commit**

```bash
git add streamlit_app/pages/1_Source_Sink_Explorer.py
git commit -m "feat: overlay Obligation and Option on one chart in the Explorer"
```

---

### Task 5: Participants and Opportunity Signals pages — bordered sections and tier color indicators

**Files:**
- Modify: `streamlit_app/pages/2_Participants.py`
- Modify: `streamlit_app/pages/3_Opportunity_Signals.py`

**Interfaces:**
- Consumes: `theme.COLORS` (Task 1)
- Produces: nothing new consumed by later tasks

- [ ] **Step 1: Wrap `2_Participants.py`'s two sections in bordered containers**

Replace the full body of `streamlit_app/pages/2_Participants.py` from `st.subheader("All Tracked-Pair Participants")` (line 19) to the end of the file with:

```python
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
        width="stretch",
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
            width="stretch",
        )
    else:
        st.info("No participants in the tracked-pair universe yet.")
```

- [ ] **Step 2: Add tier-color indicators to `3_Opportunity_Signals.py`**

In `streamlit_app/pages/3_Opportunity_Signals.py`, add this import near the top (after `from lib.theme import configure_page, render_data_source_banner`):

```python
from lib.theme import COLORS
```

Then replace the final `for s in filtered:` loop (lines 40-48) with:

```python
_TIER_DOT = {"High": "🟢", "Medium": "🟡", "Low": "⚪"}

with st.container(border=True):
    for s in filtered:
        dot = _TIER_DOT.get(s["tier"], "⚪")
        with st.expander(f"{dot} {s['source']} → {s['sink']}  —  {s['tier']} ({s['score']})"):
            f1, f2, f3, f4 = st.columns(4)
            f1.metric("Value", s["factors"]["value"]["score"])
            f2.metric("Trend", s["factors"]["trend"]["score"])
            f3.metric("Consistency", s["factors"]["consistency"]["score"])
            f4.metric("Liquidity", s["factors"]["liquidity"]["score"])
            for line in s["explanation"]:
                st.write(f"- {line}")
```

(`COLORS` is imported for consistency with the rest of the plan's stated rule even though this step uses the simpler emoji-dot approach rather than raw hex — the dots visually encode the same High/Medium/Low meaning as `COLORS["tier_high"/"tier_medium"/"tier_low"]` used elsewhere; Streamlit's `st.expander` label doesn't support arbitrary HTML/CSS coloring, so an emoji indicator is the correct mechanism here, not a limitation to work around.)

- [ ] **Step 3: Verify both files parse**

```bash
cd /Users/saif_ansari/Downloads/ercot-crr-analytics
python3 -c "import ast; ast.parse(open('streamlit_app/pages/2_Participants.py').read())" && echo "2_Participants OK"
python3 -c "import ast; ast.parse(open('streamlit_app/pages/3_Opportunity_Signals.py').read())" && echo "3_Opportunity_Signals OK"
```

- [ ] **Step 4: Commit**

```bash
git add streamlit_app/pages/2_Participants.py streamlit_app/pages/3_Opportunity_Signals.py
git commit -m "feat: bordered sections on Participants, tier color indicators on Opportunity Signals"
```

---

### Task 6: Binding Constraints tab

**Files:**
- Modify: `streamlit_app/lib/data_loader.py` (add `get_binding_constraints`, add `ercot_live`/`live_congestion` imports)
- Create: `streamlit_app/pages/4_Binding_Constraints.py`

**Interfaces:**
- Consumes: `app.ercot_live.ErcotApiClient`/`ErcotApiError` (existing, tested), `app.live_congestion.parse_api_rows`/`total_pages` (existing, tested)
- Produces: `data_loader.get_binding_constraints(days_back: int = 7) -> dict` with keys `configured: bool`, `error: str | None`, `constraints: list[dict]`, `truncated: bool` — each constraint dict has keys `delivery_date`, `hour_ending`, `constraint_name`, `contingency_name`, `shadow_price`, `from_station`, `to_station`. Consumed only by `4_Binding_Constraints.py`.

- [ ] **Step 1: Add the imports and the new function to `data_loader.py`**

In `streamlit_app/lib/data_loader.py`, change line 21 from:

```python
from app import analytics, domain, scoring, weather_zones  # noqa: E402
```

to:

```python
from app import analytics, domain, ercot_live, live_congestion, scoring, weather_zones  # noqa: E402
```

Then append this new function at the end of the file (after `get_corridor_map_points` from Task 3):

```python
@st.cache_data(ttl=900, show_spinner="Fetching live binding constraints...")
def get_binding_constraints(days_back: int = 7) -> dict:
    """Real, live ERCOT binding transmission constraints (DAM shadow
    prices) for the trailing `days_back` days -- answers "why is this
    congested right now" with the actual named grid element, not a
    statistical inference. Never raises: returns one of three states
    (not configured / API error / real data) so the caller renders
    exactly one, matching the weather panel's fail-open pattern. Capped
    at 15 pages (~15,000 rows) so a wide date range degrades to a
    truncated-but-fast result instead of a very slow one."""
    import datetime as _dt

    if not ercot_live.ErcotApiClient.is_configured():
        return {"configured": False, "error": None, "constraints": [], "truncated": False}

    date_to = _dt.date.today()
    date_from = date_to - _dt.timedelta(days=days_back)

    rows: list[dict] = []
    truncated = False
    try:
        client = ercot_live.ErcotApiClient()
        page = 1
        max_pages = 15
        while True:
            response = client.get_dam_shadow_prices(
                date_from.isoformat(), date_to.isoformat(), page=page, size=1000
            )
            rows.extend(live_congestion.parse_api_rows(response))
            pages = live_congestion.total_pages(response)
            if page >= pages or page >= max_pages:
                truncated = page < pages
                break
            page += 1
    except ercot_live.ErcotApiError as e:
        return {"configured": True, "error": str(e), "constraints": [], "truncated": False}

    constraints = [
        {
            "delivery_date": str(r.get("deliveryDate", ""))[:10],
            "hour_ending": r.get("hourEnding"),
            "constraint_name": r.get("constraintName"),
            "contingency_name": r.get("contingencyName"),
            "shadow_price": r.get("shadowPrice"),
            "from_station": r.get("fromStation"),
            "to_station": r.get("toStation"),
        }
        for r in rows
    ]
    constraints.sort(key=lambda c: (c["delivery_date"], c["hour_ending"] or 0), reverse=True)
    return {"configured": True, "error": None, "constraints": constraints, "truncated": truncated}
```

- [ ] **Step 2: Verify it against the real, live ERCOT API**

```bash
cd /Users/saif_ansari/Downloads/ercot-crr-analytics
python3 -c "
import sys
sys.path.insert(0, 'streamlit_app')
from dotenv import load_dotenv
load_dotenv('backend/.env')
from lib import data_loader
result = data_loader.get_binding_constraints.__wrapped__(days_back=7)
print('configured:', result['configured'])
print('error:', result['error'])
print('constraint count:', len(result['constraints']))
print('truncated:', result['truncated'])
if result['constraints']:
    print('sample:', result['constraints'][0])
"
```
Expected: `configured: True`, `error: None`, a non-zero `constraint count`, and a sample row with real values for `constraint_name`, `shadow_price`, `from_station`, `to_station` (not `None` for all of them — spot-check at least `constraint_name` and `shadow_price` are populated).

- [ ] **Step 3: Create the Binding Constraints page**

Create `streamlit_app/pages/4_Binding_Constraints.py`:

```python
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
```

**Note (added after Tasks 1-4 were built and live-tested):** this project's installed Streamlit version (1.38.0) does NOT support `width="stretch"` on `st.dataframe`/`st.plotly_chart` — its `width` parameter is typed `int | None` and passing the string `"stretch"` raises `TypeError: 'str' object cannot be interpreted as an integer` at render time (confirmed live, not just from reading the signature). Always use `use_container_width=True` for "stretch to container" sizing on this Streamlit version, on every dataframe and plotly_chart call in this plan and in the app generally — the code block above already reflects this fix.

- [ ] **Step 4: Verify syntax**

```bash
cd /Users/saif_ansari/Downloads/ercot-crr-analytics
python3 -c "import ast; ast.parse(open('streamlit_app/pages/4_Binding_Constraints.py').read())" && echo "syntax OK"
python3 -c "import ast; ast.parse(open('streamlit_app/lib/data_loader.py').read())" && echo "data_loader syntax OK"
```

- [ ] **Step 5: Commit**

```bash
git add streamlit_app/lib/data_loader.py streamlit_app/pages/4_Binding_Constraints.py
git commit -m "feat: add live Binding Constraints tab"
```

---

### Task 7: Live QA pass on the whole redesigned app

**Files:** none created/modified — verification only. If this task finds bugs, fix them in the relevant file from Tasks 1-6 and re-run this task's steps before committing the fix.

- [ ] **Step 1: Start the app**

Using your available preview/browser tooling (e.g. a `preview_start` tool backed by a `.claude/launch.json`-equivalent config, or directly):

```bash
cd /Users/saif_ansari/Downloads/ercot-crr-analytics
python3 -m streamlit run streamlit_app/Overview.py --server.headless true --server.port 8501
```

- [ ] **Step 2: Verify the Overview page**

Load the app. Confirm: the KPI row shows a delta on "Latest Month MW Awarded", the Corridor Map renders with visible points over Texas (not a blank/error area), the tier-distribution chart is a colored Plotly bar (hover shows exact counts), and every section is visually a distinct bordered card.

- [ ] **Step 3: Verify the Explorer page**

Select a corridor. Confirm the chart shows Obligation (green) and Option (amber) as two separate lines with a legend, hovering shows both values at once ("hovermode x unified"), and there's no leftover "CRR Type" radio button. Toggle Time of Use and confirm both lines update together.

- [ ] **Step 4: Verify Participants and Opportunity Signals**

Confirm both pages' sections render inside visible bordered cards. On Opportunity Signals, confirm each expander title has a colored dot (🟢/🟡/⚪) matching its tier.

- [ ] **Step 5: Verify the new Binding Constraints page**

Confirm the nav sidebar shows "Binding Constraints" as a fourth page option. Load it, confirm it shows real data (not the "not configured" warning, since credentials are set), confirm the caption states both the live-data window and the separate MIS auction month, and confirm the search box filters the table. Move the days-back slider and confirm the table updates.

- [ ] **Step 6: Check for errors**

Check the running server's stdout/stderr and the browser console for any exception or Python traceback surfaced as a Streamlit error box. Fix any found before proceeding.

- [ ] **Step 7: Stop the server**

Stop the Streamlit process once verification is complete.

- [ ] **Step 8: Commit any fixes made during this task**

If Step 6 required fixes:

```bash
git add streamlit_app
git commit -m "fix: resolve issues found during live QA of visual polish + Binding Constraints"
```

If no fixes were needed, skip this step.

---

### Task 8: Final three-persona review round

**Files:**
- Modify: `docs/triple_check_review.md` (append a new dated round)

**Interfaces:** None — this is a review/documentation task, not code.

This task is executed differently from Tasks 1-7: dispatch three separate review passes (Senior Software Engineer, Senior Power Trader, Senior UX/UI Streamlit Designer) over the whole diff from this plan (Tasks 1-7 combined), each producing a pass/fail verdict with specifics, the same way this project's existing `docs/triple_check_review.md` already documents two earlier rounds. This is the explicit final sign-off Saif asked for.

- [ ] **Step 1: Senior Software Engineer pass**

Review the full diff (all commits from Task 1 through Task 7) for: no backend logic touched (only `streamlit_app/` and this doc), no hardcoded color literals outside `theme.COLORS`, the new `get_binding_constraints` function's error handling matches the fail-open pattern used elsewhere, no dead code left over from the removed CRR-type radio button in the Explorer page.

- [ ] **Step 2: Senior Power Trader pass**

Using the live, running app (repeat Task 7's live QA steps from this persona's perspective): is the Obligation/Option overlay actually clearer than the old toggle-between-two-views design? Does the Corridor Map add real information or is it decorative? Does the Binding Constraints tab's 7-day default window and the "these are two different clocks" framing actually make sense to someone deciding whether a corridor is worth investigating?

- [ ] **Step 3: Senior UX/UI Streamlit Designer pass**

Using the live, running app: is the color system actually consistent (Obligation/Option/tier colors mean the same thing everywhere they appear)? Do the bordered containers create real visual hierarchy or just add boxes? Is there anything on any of the 5 pages that still looks like a bare prototype rather than a considered product?

- [ ] **Step 4: Append the round to `docs/triple_check_review.md`**

Append a new section to `docs/triple_check_review.md` (after the existing "v1.4 pass" section), following the exact heading structure the file already uses for its prior two rounds (`## v1.5 pass (2026-09) -- visual polish, Obligation/Option overlay, Binding Constraints`, with `### Pass 1 -- ...`, `### Pass 2 -- ...`, `### Pass 3 -- ...` subsections, each a markdown table of Check/Verdict/Evidence rows, matching the existing file's exact table format), with the three passes' real findings from Steps 1-3 above -- verdicts and evidence, not placeholders. Include an "Open items" line under each pass for anything found but not blocking, exactly as the existing rounds do.

- [ ] **Step 5: Commit**

```bash
cd /Users/saif_ansari/Downloads/ercot-crr-analytics
git add docs/triple_check_review.md
git commit -m "docs: add v1.5 triple-check review round (visual polish + Binding Constraints)"
```
