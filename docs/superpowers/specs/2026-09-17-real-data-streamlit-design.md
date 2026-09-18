# Real ERCOT Data + Market Intelligence + Streamlit Rebuild — Design

**Date:** 2026-09-17
**Driven by:** Reggie Wade's review call (`transcript.docx`) + the original capstone
assignment brief + follow-up direction from Saif.

## 1. Why

The v1.3 prototype works but leans on synthetic auction/participant data and a
React+FastAPI two-process architecture that's awkward to hand someone as a
link. Reggie's review surfaced concrete, checkable asks: use the *real* ERCOT
CRR auction files (a year's worth), map real participant IDs to real company
names, look at settlement prices (not just LMPs), map weather to load
zones/hubs with an actual seasonality view, and answer trader questions like
"who's doing what" and "what are the hot paths." Separately, Saif wants the
shippable artifact to be a single portable Streamlit app instead of a
two-process React/FastAPI setup.

Investigation during this session overturned one of the project's own prior
conclusions: ERCOT's legacy MIS servlet endpoints
(`ercot.com/misapp/servlets/IceDocListJsonWS` +
`ercot.com/misdownload/servlets/mirDownload`) are reachable, unauthenticated,
and serve the real CRR Monthly Auction Results and the real Market
Participant list as plain zip/CSV/xlsx — no browser session needed. This was
verified by actually downloading and parsing real files during this session,
not assumed. The finer-grained settlement-price feeds (NP6-787/788/905) were
also checked and found *not* practical to backfill a year of history (5–7 day
retention, one tiny file per interval) — the project's existing
`api.ercot.com` live client remains the right tool for price data.

## 2. Scope

**In scope:**
1. Fetch and commit real CRR auction data (13 months) + real participant
   registry into the repo.
2. Fix real bugs in `ingestion.py`'s column mapping found while parsing the
   real files (HedgeType vs. CRRType confusion, missing auction-month
   derivation, TimeOfUse string normalization, unsigned MW netting).
3. Data-driven tracked-pairs discovery (replaces the static 14-pair list) +
   two new analytics: Hot Paths and Participant Strategy.
4. Real ERCOT weather-zone mapping (8 official zones) + trailing-12-month
   seasonality time series (Open-Meteo historical archive API).
5. A new Streamlit app that is the primary, shareable web application —
   reads bundled real data directly (no HTTP hop, no second process),
   works when the whole project folder is zipped and moved elsewhere.
6. Docs: requirements, triple-check review, lessons-learned, prompt journal,
   README, and a note on updating the presentation deck.

**Out of scope (explicitly, not silently dropped):**
- Bulk historical settlement-point price backfill (NP6-787/788/905) — not
  practical per the retention-window finding above; live per-pair API stays
  as-is.
- KML network map — Reggie called it "nice to have," and it requires a
  digital certificate he'd need to send separately.
- Actually clicking "Deploy" on Streamlit Community Cloud — Saif will do
  this himself; this project makes the repo deploy-ready and documents the
  exact steps.
- Rewriting/updating the React frontend — kept as an untouched reference,
  per Saif's choice.
- Removing FastAPI — kept as-is, per Saif's choice.

## 3. Real data acquisition

New script: `backend/scripts/fetch_real_ercot_data.py`.

- Calls `IceDocListJsonWS?reportTypeId=11201` (Monthly CRR Auction Results)
  and `reportTypeId=21129` (Market Participants List), lists available docs,
  downloads each via `mirDownload?doclookupId=...`.
- From each auction zip, extracts only `Common_MarketResults_*.csv` (the
  awarded-results file — not `AuctionBidsAndOffers`, which is the full bid
  stack) and discards the rest to keep repo size sane.
- From the participant zip, extracts the `.xlsx` and pulls just the `CRRAH`
  sheet (name, short name, DUNS) to a small `data/reference/participants.csv`.
- Writes results to `data/raw/crr_auction/<MONTH>_MarketResults.csv` — plain
  CSVs, committed to the repo, so `ingestion.py`'s existing
  CSV-in-`data/raw`-wins-over-synthetic tier picks them up with zero
  additional wiring.
- Idempotent / re-runnable: skips a month's file if already present, so
  running it again next month (after the next auction posts) only pulls the
  new one. This is a manual/occasional script, not called at server startup
  (matches the existing `export_snapshot.py` pattern).

This session: run it once now, for real, and commit the ~13 months of real
CSVs + the participant reference file into the repo, so the project is
self-contained the moment it's unzipped elsewhere — no fetch step required
to see real data, though the script remains there to refresh it later.

## 4. Ingestion fixes (`backend/app/ingestion.py`)

Concrete bugs found by parsing a real file, fixed here:

| Real column | Current (wrong) behavior | Fix |
|---|---|---|
| `HedgeType` (OBL/OPT) | Not aliased at all; `crr_type` alias pointed at `CRRType`, which actually holds `PREAWARD`/`STANDARD` | Alias `crr_type` to `HedgeType`; keep `CRRType`'s real meaning as a new `award_type` field (`PREAWARD` vs `STANDARD`) |
| `TimeOfUse` values `PeakWD`/`PeakWE`/`Off-peak` | Enum expects `PEAK_WD`/`PEAK_WE`/`OFF_PEAK` | Normalize casing/punctuation on ingest |
| `StartDate` (MM/DD/YYYY) | No `auction_month` column exists in the real file; alias list has nothing to fall back to | Derive `auction_month` (`YYYY-MM`) from `StartDate` when no explicit month column matches |
| `BidType` (BUY/SELL) | Not handled; every row would be summed as a positive award | Sign `awarded_mw`: positive for BUY, negative for SELL, at ingestion time. Every existing sum-based aggregation (dashboard MW, participant notional, opportunity score liquidity factor) then nets correctly with no changes to those functions. Price fields (`clearing_price`) are never signed — the shadow price is a property of the auction result for that path/TOU, not of which side you're on. |
| `AccountHolder` short code (e.g. `XSARAC`) | Used directly as the participant name | Join against `data/reference/participants.csv` (short name → real full name); store the real name as `participant`, keep the short code as `participant_short_code` for search (traders search by short code, per Reggie's "type in HAR" example) |

Synthetic fallback is untouched — it has no SELL rows, no real short codes,
so none of the above branches fire for synthetic data, and the existing
`is_synthetic: true` tagging/banner behavior is unchanged.

## 5. Data-driven tracked pairs + market intelligence (`backend/app/analytics.py`)

Two new pure functions:

- **`discover_top_pairs(records, n=30)`** — replaces the static
  `domain.CRR_PAIRS` as the "which pairs does the app track" answer *when
  real data is active*. Ranks all distinct Source/Sink pairs by total
  notional (Σ|awarded_mw| × |clearing_price|), returns the top N along with
  participant count and a `recurring_months` count (how many of the trailing
  12 months had a same-sign average price as the pair's all-time average —
  reusing the existing consistency logic already in `scoring.py`, just
  exposed per-pair here). Synthetic mode keeps using `domain.CRR_PAIRS`
  as-is (it needs a fixed universe since the generator writes to exactly
  those pairs).
- **`top_paths(records, months_back=12)`** — thin wrapper for the "Hot
  Paths" dashboard panel: the same ranked list, trimmed to what the Overview
  tab shows (top 10), each with a one-line reason (e.g. "congested in 9 of
  the last 12 months, 14 active participants").
- **`participant_strategy(participant_name, records)`** — per-participant
  breakdown: certificate count, Option vs. Obligation %, net Buy/Sell MW,
  Pre-award vs. Standard-auction %, top 5 corridors by notional. This is
  what answers Reggie's "who's doing what" / "what's their strategy."

`domain.py` gains the real weather-zone reference table (see below) but its
existing `SettlementPoint`/hub/load-zone/enum definitions are untouched —
those codes (`HB_WEST`, `LZ_HOUSTON`, etc.) are already real and already
appear in the real auction file, so they need no change.

## 6. Weather-zone mapping (`backend/app/weather_zones.py`, new)

Static reference table for ERCOT's 8 official weather zones (Coast, East,
Far West, North, North Central, South, South Central, West — the same
names Reggie read directly off the real ERCOT map on the call), each with:
- One representative city + lat/lon for the Open-Meteo query (e.g. Coast →
  Houston, Far West → Midland/Odessa, West → San Angelo, North Central →
  Dallas–Fort Worth).
- The hub(s)/load zone(s) it's associated with (e.g. Coast → `HB_HOUSTON`,
  `LZ_HOUSTON`).

Documented explicitly, in-repo, as a best-effort mapping: ERCOT weather-zone
and load-zone boundaries are not congruent, so a couple of zones (East,
North vs. North Central) have a labeled "closest hub" rather than a clean
1:1 — same honesty pattern the project already uses for synthetic data and
live-integration limits.

Weather module changes:
- Current-conditions panel now iterates the 8 zones (was 4 ad hoc regions).
- New: trailing-12-month monthly-average-temperature series per zone, from
  Open-Meteo's free `archive-api.open-meteo.com` endpoint (verified working,
  no key, during this session) — rendered as a small seasonality line/strip
  per zone, answering Reggie's "take an average across each zone and maybe
  even make a time series... you'll see some of the seasonality."

## 7. Streamlit app (new primary web app)

New top-level `streamlit_app/` (kept separate from `backend/` and
`frontend/` so it's obvious which is which):

```
streamlit_app/
├── app.py                 Entry point — page config, sidebar nav, data-source banner
├── pages/
│   ├── 1_Overview.py
│   ├── 2_Source_Sink_Explorer.py
│   ├── 3_Participants.py
│   └── 4_Opportunity_Signals.py
├── lib/
│   └── data_loader.py      Thin cached wrapper around backend.app ingestion/analytics/scoring
└── requirements.txt        streamlit, pandas, plotly (or reuse matplotlib) — no FastAPI/uvicorn needed to run this
```

- Imports `backend/app/{ingestion,analytics,scoring,domain,weather_zones}.py`
  directly as a Python package (`sys.path` shim or installing `backend` as a
  local package) — no HTTP call, no second process, so it's one `streamlit
  run streamlit_app/app.py` and everything works, including offline/zipped.
- Data source: same three-tier priority as today (SQL Server env vars → real
  CSVs in `data/raw` → synthetic), using `@st.cache_data` instead of
  `functools.lru_cache` for the loaded dataset, with a manual "Refresh data"
  button (Streamlit's cache doesn't auto-invalidate on file changes the way
  a dev-mode API server might).
- All four existing tabs plus the two new panels (Hot Paths on Overview,
  Strategy section on Participant detail) get rebuilt as Streamlit
  equivalents — same underlying data/metrics, new UI shell.
- Portability: because `data/raw/crr_auction/*.csv` and
  `data/reference/participants.csv` are committed files (not something
  fetched at runtime), zipping the whole `ercot-crr-analytics/` folder and
  running it anywhere with `pip install -r streamlit_app/requirements.txt &&
  streamlit run streamlit_app/app.py` reproduces the exact same app with the
  exact same real data — no network calls required except the optional live
  weather/ERCOT-API panels, which fail open with a visible message exactly
  as they do today.
- Deploy-ready for Streamlit Community Cloud: `git init` this project,
  correct `.gitignore` (exclude `backend/.env`, keep `data/raw` — real
  public ERCOT data, no secrets), single `requirements.txt` Streamlit Cloud
  can find. I'll hand Saif the exact 3-step click-through (create GitHub
  repo → push → connect on share.streamlit.io) rather than doing the
  account-bound steps myself.

## 8. Docs updates

- `docs/requirements.md` → v1.4: real-data ingestion, discovered tracked
  pairs, Hot Paths / Participant Strategy, weather-zone mapping, Streamlit
  as the primary app.
- `docs/triple_check_review.md` → new v1.4 pass, all three personas, over
  the new feature set (this is also where I do the trader/frontend critique
  Saif asked for directly).
- `docs/lessons_learned_and_future_work.md` → new entry: the MIS legacy
  servlet finding (an explicit instance of lesson #6 already written down —
  "an earlier no is worth re-checking" — proven true again).
- `docs/prompt_journal.md` → new entry for this round.
- `README.md` → rewritten real-data section (drop "requires a browser
  session" framing where it's now wrong), Streamlit quick-start as the
  primary way to run this, note on the FastAPI/React paths still existing
  for reference.
- Flag, don't silently do: `presentation/ERCOT_CRR_Capstone_Presentation.pptx`
  is now two versions further out of date. Given the capstone brief lists
  the 60-minute presentation as a required deliverable, I'll note exactly
  what needs updating in `lessons_learned_and_future_work.md` but won't
  rewrite the deck itself unless asked — slides are a judgment/narrative
  call, not a mechanical sync.

## 9. Testing

- New/updated pytest coverage for every ingestion fix in §4 (HedgeType
  mapping, BUY/SELL netting sign, TimeOfUse normalization, StartDate→month
  derivation, participant name join) using small real-shaped fixtures, not
  the full downloaded files.
- New tests for `discover_top_pairs`, `top_paths`, `participant_strategy`
  covering the ranking logic and the BUY/SELL netting edge case
  specifically (a pair where the same participant both buys and sells in
  the same month should net, not double-count).
- Streamlit app itself: no framework-level unit tests (matches how the
  React layer was tested — "smoke test all tabs together," not unit
  tests of JSX) but I will run it live via the preview tool and click
  through all tabs/filters before calling this done, per the project's own
  "verify end to end, don't just claim it" standard.

## 10. Error handling / fallback behavior (unchanged philosophy)

Same three-tier degrade-safely pattern as today: SQL → real CSV → synthetic,
each failure surfaced via a visible warning, never silent. Weather and live
ERCOT API panels keep their existing fail-open-with-a-message behavior. The
Streamlit rebuild doesn't change this contract — it's a new UI shell over
the same tested backend behavior, per lesson #4 already in this project
("keep the UI dumber than the backend").
