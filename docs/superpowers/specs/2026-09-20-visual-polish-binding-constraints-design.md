# Visual Polish + Binding Constraints Tab — Design

**Date:** 2026-09-20
**Driven by:** Follow-up conversation after the real-data + Streamlit rebuild —
Saif flagged the Streamlit app looks "bland," wants Obligation/Option on one
chart, an ERCOT-style map, and a new tab explaining *why* a corridor is
congesting (not just that it is). Confirmed live ERCOT Public API
credentials work end-to-end during this session (real auth + real data
pulled). Trader-hat and engineer-hat discussion concluded: do NOT blend the
live API's ~34-month DAM-spread history into the opportunity score (a stale
proxy across a changed grid topology risks manufacturing false confidence);
DO add it as a separate, clearly-time-stamped "why" panel, matching the
existing weather panel's honesty pattern.

## 1. Scope

**In scope:**
1. Replace Streamlit's built-in `st.line_chart`/`st.bar_chart` with Plotly
   (`st.plotly_chart`) across all four existing pages, for real legends,
   hover tooltips, and multi-series overlays.
2. Explorer page: Obligation and Option plotted as two colored lines on the
   *same* chart (the specific ask that started this round).
3. A consistent color system used everywhere: Obligation vs. Option get
   fixed colors; High/Medium/Low tiers get fixed colors; both reused
   identically across Overview, Explorer, and Opportunity Signals so a
   color always means the same thing.
4. Card-style layout: `st.container(border=True)` around each logical
   section, replacing bare `st.divider()` breaks.
5. An ERCOT corridor map on the Overview page: tracked hubs/load-zones
   plotted by real lat/lon (reuse `weather_zones.py`'s existing zone
   coordinates as anchors for the hubs/load-zones already mapped to them),
   sized/colored by tracked-pair activity.
6. Bigger KPI presentation on Overview using `st.metric`'s built-in delta
   support (e.g., latest-month MW vs. prior month).
7. New **Binding Constraints** page (`streamlit_app/pages/4_Binding_Constraints.py`):
   trailing-N-day (default 7, user-adjustable, capped at 30) table of real
   binding transmission constraints from ERCOT's live Public API
   (`backend/app/ercot_live.py`'s `get_dam_shadow_prices`, already built
   and tested) — constraint name, contingency, shadow price, from/to
   station, date/hour. Clearly labeled "as of [now], last N days" next to
   the auction data's own "as of [latest MIS month]" label elsewhere on
   the page, so the two different time windows are never conflated.
   Fails open exactly like the weather panel: not-configured and
   API-error states show a clear message, never a crash or blank page.
8. Final gate: three persona reviews (Senior Software Engineer, Senior
   Power Trader, Senior UX/UI Streamlit Designer) over the *whole* diff,
   modeled on this project's existing `docs/triple_check_review.md`
   pattern, appended as a new dated round in that same file.

**Out of scope (explicitly):**
- Blending live-API historical DAM spread into the opportunity score or
  trend/consistency factors — decided against this session, see above.
- Forcing the Binding Constraints window to align with the MIS auction
  month — they're deliberately different clocks, shown side by side, not
  merged.
- A full custom-drawn ERCOT transmission map (KML-based) — still flagged
  as a "nice to have" per the original Reggie call, not attempted here;
  the corridor map here is a simple lat/lon scatter over tracked
  points, not a literal grid diagram.

## 2. UI/UX changes, file by file

### `streamlit_app/lib/theme.py`
Add a shared color palette module-level dict, e.g.:
```python
COLORS = {
    "obligation": "#2ecc71",
    "option": "#f39c12",
    "tier_high": "#2ecc71",
    "tier_medium": "#f39c12",
    "tier_low": "#7f8c8d",
}
```
Every page imports this instead of picking ad hoc colors, so Obligation is
always green and Option is always amber everywhere it appears.

### `streamlit_app/pages/1_Source_Sink_Explorer.py`
Replace the current `st.line_chart({...})` (single series, whatever
CRR-type radio is selected) with a Plotly figure holding BOTH the
Obligation and Option monthly series as separate traces, using
`theme.COLORS`, with a legend and hover showing exact `$/MWh` + month. The
CRR-type radio button is removed (no longer needed — both series always
show); the Time-of-Use filter stays, applied to both series identically.

### `streamlit_app/app.py` → `streamlit_app/Overview.py` (already the entry
point name)
- Tier-distribution bar chart becomes a Plotly bar using `theme.COLORS`'
  tier colors, replacing `st.bar_chart(tier_counts)`.
- KPI row uses `st.metric(..., delta=...)` where a prior-period comparison
  is available (e.g., latest month MW vs. the month before it).
- New "Corridor Map" section: a Plotly `scatter_geo` (or `st.map`) plotting
  every real hub/load-zone code that appears in `top_pairs`, using the
  lat/lon of the weather zone each is associated with in
  `weather_zones.WEATHER_ZONES` (build a `{settlement_point_code: (lat,
  lon)}` lookup once from the existing zone→hub/load-zone mapping), sized
  by how many tracked pairs touch that point.
- Every section (KPIs, Hot Paths, tiers, participants, weather, map)
  wrapped in `st.container(border=True)`.

### `streamlit_app/pages/2_Participants.py`, `3_Opportunity_Signals.py`
Wrap sections in bordered containers; Opportunity Signals' tier badges use
`theme.COLORS`' tier colors consistently with the Overview's tier chart.

### `streamlit_app/pages/4_Binding_Constraints.py` (new)
```
Title, banner (live-API-configured / not-configured state)
Date range picker: default last 7 days, max 30 days back (st.slider or two st.date_input, clamped)
Fetch (cached, ttl=900s -- 15 min, since this is near-real-time data) via a
  new data_loader.get_binding_constraints(date_from, date_to) function that
  wraps ercot_live.ErcotApiClient + live_congestion.parse_api_rows
Table: constraint name, contingency, shadow price, from station, to
  station, delivery date, hour -- sortable, searchable by constraint/station name
Caption: "Live ERCOT data, last refreshed <timestamp> -- separate from the
  auction data above (as of <latest MIS auction month>), shown for context
  on what's congesting right now."
Failure states (not configured / API error) rendered exactly like the
  weather panel: a clear st.warning/st.error, never a crash.
```

### `streamlit_app/lib/data_loader.py`
New function:
```python
def get_binding_constraints(days_back: int = 7) -> dict:
    """Returns {"configured": bool, "error": str|None, "constraints": list[dict]}.
    Never raises -- callers render whichever of these three states applies,
    matching the weather panel's fail-open pattern."""
```
Imports `ErcotApiClient`, `ErcotApiError` from `app.ercot_live` and
`fetch_live_pair_records`... actually uses `client.get_dam_shadow_prices`
directly (not the pair-specific spread helper) plus
`live_congestion.parse_api_rows` to shape the response into plain dicts.

## 3. Data question already resolved

No date-range reconciliation needed between MIS and the live API — they're
different clocks answering different questions (settled history vs. live
now), and the UI states both time windows explicitly rather than
pretending they're one timeline (see Binding Constraints page caption
above).

## 4. Testing

- `backend/app/ercot_live.py`/`live_congestion.py` already have 27+ tests
  from the original build — no changes needed there, this reuses them
  as-is.
- New `streamlit_app/lib/data_loader.get_binding_constraints` gets no
  pytest coverage (matches this project's established pattern: Streamlit
  glue code is verified live, not unit-tested) but IS verified in this
  session via a live, authenticated call before any UI code is written
  (already done — see conversation).
- Plotly chart correctness and the new page are verified live via browser
  preview (screenshot + accessibility snapshot), same method used for the
  original Streamlit build's QA pass.

## 5. Final review gate

After implementation, three persona reviews run over the whole diff,
appended to `docs/triple_check_review.md` as a new dated round:
- **Senior Software Engineer** — code quality, no regressions to the 136
  backend tests, Plotly/data_loader integration is clean.
- **Senior Power Trader** — is this actually more usable day-to-day; does
  the Binding Constraints tab answer real questions; is the map genuinely
  informative or decorative.
- **Senior UX/UI Streamlit Designer** — visual consistency, color meaning,
  information hierarchy, whether it now looks like a product a trader
  would trust, not a prototype.
