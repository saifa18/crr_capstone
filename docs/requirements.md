# Requirements Document
## ERCOT CRR Market Analytics — Capstone Prototype

**Version:** 1.3
**Status:** Revised (v1.3) — added a real SQL Server data-source layer (environment-variable configured, the database may live on a different machine than the backend), with graceful degradation and a documented handoff prompt for connecting it (`docs/copilot_sql_connection_prompt.md`); see `prompt_journal.md` Entry 8
**Author:** Saif, ETRM Implementation Consultant, Veritas (an Oliver Wyman business)

---

## 1. Purpose

Build a prototype web application that analyzes ERCOT Congestion Revenue
Rights (CRR) markets: who the major participants are, how Source/Sink
pricing relationships have historically behaved, and an explainable signal
for which Source/Sink pairs may warrant further investigation for bidding.
This is a **market intelligence and analytics** tool. It is explicitly
**not** a trading system, not a predictive/ML price forecaster, and not
investment advice.

## 2. Background (why this matters)

In ERCOT's nodal market, transmission constraints cause the price of energy
to differ by location (Locational Marginal Price, or LMP). CRRs are
financial instruments that let a holder hedge — or speculate on — the
difference in LMP between two settlement points (a **Source** and a
**Sink**). ERCOT auctions CRRs monthly and annually; market participants bid
based on their expectation of future congestion between two points.
Understanding **which paths have historically been congested, how
consistently, and who is trading them** is the core market-intelligence
problem this tool addresses.

## 3. Scope

### 3.1 In scope
- Ingesting CRR auction result data (Source, Sink, CRR type, time-of-use,
  clearing price, awarded MW, winning participant) at monthly granularity.
- Descriptive analytics per Source/Sink pair: average, min, max, volatility
  (standard deviation), and trend (linear slope + year-over-year change).
- Participant-level analysis: total MW awarded, total notional value,
  number of distinct pairs traded, and historical monthly activity.
- An **explainable, rule-based** Opportunity Score (Low / Medium / High)
  per Source/Sink pair, with a visible breakdown of the factors that
  produced it.
- A dashboard summarizing recent auction activity, active participants, and
  the highest-scoring Source/Sink pairs.
- A Source/Sink explorer with historical price charts and metrics.

### 3.2 Out of scope (explicitly)
- Real-time/streaming LMP or DAM/RTM price feeds.
- Predictive machine learning models (e.g., forecasting next month's
  clearing price). The opportunity score is a **descriptive composite of
  historical statistics**, not a forecast.
- Actual bid submission, portfolio/credit management, or any connection to
  ERCOT's live market systems.
- Guaranteed accuracy of real ERCOT historical figures — see Section 6,
  Data Sourcing.

## 4. Users & Use Cases

| User | Use case |
|---|---|
| ETRM/market analyst | "Which Source/Sink pairs have been consistently and meaningfully congested, and who is actively trading them?" |
| New trader / analyst training | "Help me build intuition for how ERCOT congestion patterns look across hubs and load zones." |
| Risk/portfolio reviewer | "Show me a participant's historical CRR footprint — which pairs, how much MW, how consistently." |

## 5. Functional Requirements

**FR-1 Dashboard**
The system shall display: the most recent completed auction month, MW
awarded and distinct participants in that month, the count of tracked
Source/Sink pairs, the top 5–6 Opportunity Score pairs, and the top 5–6
participants by total notional value.

**FR-2 Participant Analysis**
The system shall list all participants with total awarded MW, total
notional, number of distinct pairs traded, and auction line-item count; and
shall show, per participant, a time series of monthly MW awarded and the
list of Source/Sink pairs traded.

**FR-3 Source/Sink Explorer**
The system shall let a user select any tracked Source/Sink pair and view
its historical clearing-price time series (separately for Obligation and
Option CRRs), alongside its descriptive metrics (FR-4).

**FR-4 Basic Analytics**
For any selected Source/Sink pair (or filtered slice), the system shall
compute: average clearing price, minimum, maximum, volatility (population
standard deviation of the monthly series), and trend (linear regression
slope plus a recent-12-months-vs-prior-12-months percent change, when 24+
months of history exist).

**FR-5 Explainable Opportunity Score**
For every tracked Source/Sink pair, the system shall compute a composite
0–100 score from four named, weighted factors — value level, trend,
directional consistency, and market liquidity/participation — and bucket it
into Low (<40) / Medium (40–69) / High (≥70). The system shall display each
factor's sub-score and a plain-language explanation alongside the bucket,
so a user can see *why* a pair scored the way it did.

**FR-6 Data Ingestion**
The system shall be able to load real ERCOT CRR Auction Results CSVs (the
public NP7-802-M / NP7-803-M report layout) when present, and shall
otherwise fall back to a clearly-labeled synthetic dataset so the
application is always runnable without requiring MIS credentials.

**FR-7 Live ERCOT Data Integration**
The system shall be able to compute real, current Source/Sink congestion
value directly from ERCOT's live Public Data API (`api.ercot.com`) when
free API credentials are configured, using the real Day-Ahead Market price
spread between the two settlement points as the value signal, run through
the same tested analytics as the rest of the system. The system shall also
surface the real, named binding transmission constraint(s) behind that
congestion via the same live API, rather than only a statistical inference.
When live credentials are not configured, the relevant endpoints shall
return a clear, actionable explanation (not a silent fallback or an
unhelpful error) rather than exposing raw exceptions.

**FR-8 Downside-Risk Disclosure**
For any selected Source/Sink pair, the system shall report the percentage
of historical months in which realized value was negative, alongside the
existing average/min/max/volatility/trend metrics (FR-4) — so a reviewer
can see downside frequency directly rather than inferring it from
volatility alone.

**FR-9 Data Export**
The system shall let a user download the underlying monthly price series
for any Source/Sink pair as a CSV file, both from the API directly
(`?format=csv`) and from the UI (one-click download), so the data can be
taken into the user's own spreadsheet or model.

**FR-10 Connectable Web Application Architecture**
The frontend shall be written against a single data-provider interface
implemented twice — once reading the embedded demo dataset, once calling a
real backend over HTTP — so every view (Dashboard, Explorer, Participants,
Signals) behaves identically regardless of which is active. The UI shall
expose a way to point itself at a running backend URL and switch between
the two without a code change or reload, and shall fail open (fall back to
the demo dataset with a clear message) if the connection attempt fails.

**FR-11 Time-of-Use and CRR-Type Filtering in the Explorer**
The Source/Sink Explorer shall let a user filter the displayed price
series and metrics by time-of-use bucket (All Hours / Peak Weekday / Peak
Weekend / Off-Peak) and shall show Obligation and Option series
simultaneously, since the two can differ materially and averaging them
away by default would hide the number a user is actually evaluating.

**FR-12 Pair Comparison**
The Explorer shall let a user overlay up to two additional Source/Sink
pairs' Obligation series on the same chart as the currently selected pair
(three total), so relative value across candidate corridors can be judged
without switching screens.

**FR-13 Seasonality and Recency Context**
For any selected pair, the system shall show (a) the trailing 12-month
average alongside the all-time average, since an all-time figure over
several years is of limited use for a forward decision, and (b) a
calendar-month seasonality view (average value by month-of-year across all
tracked years), so a user can see which months a path actually congests in
independent of which years happened to be sampled.

**FR-14 Dashboard Completeness**
The Dashboard shall summarize, at minimum: the latest auction month and MW
awarded, active participant counts, tracked pair count, the distribution
of all tracked pairs across Low/Medium/High opportunity tiers (not only
the top 5), and a trailing 12-month total-MW-awarded trend — so a user can
assess overall market activity and health at a glance, not only a
snapshot of the single most recent month.

**FR-15 Physical Market Context (Weather)**
The Dashboard shall display real, live current weather conditions (via a
free, unauthenticated, CORS-enabled public API — see
`docs/lessons_learned_and_future_work.md` for why Open-Meteo specifically)
for the geographic regions behind the tracked corridors' Source/Sink
points, since wind output (West Texas, Panhandle) and temperature-driven
load (Houston, DFW) are the physical drivers of the congestion the rest of
the app measures. This is presented explicitly as context, not a forecast
or input to the opportunity score, and the panel shall fail open with a
clear message (never a blank or broken-looking panel) if the live fetch is
unreachable from the environment it's running in.

**FR-16 Real SQL Server Data Source**
The system shall be able to read the full auction/participant dataset from
a real SQL Server database, configured entirely through environment
variables (connection string, or host/database/credentials separately;
both SQL authentication and Windows trusted-connection authentication
shall be supported), and the database is not required to be on the same
machine as the backend. SQL Server shall be the highest-priority real data
source, ahead of CSV files, itself ahead of the synthetic demo generator.
A SQL Server that is configured but unreachable, misconfigured, or missing
the expected table shall not crash the application or hang a request
indefinitely (an explicit, short connect timeout applies) — it shall fall
back to the next tier and surface a clear, human-readable warning via the
API (`data_source_warning` on `/api/meta`, `/api/dashboard`, and
`/api/system/status`) and the UI, rather than silently serving different
data while looking identical.

## 6. Data Sourcing & a Known Limitation (read this)

ERCOT does publish real historical CRR Auction Results (Long-Term:
NP7-802-M; Monthly: NP7-803-M) on the MIS Public Area, including Source,
Sink, CRR type, clearing price, and CRR Account Holder (participant). That
download center is a JavaScript-driven, session-based file browser with no
stable unauthenticated direct-download URL, so it could not be scripted
from this project's offline development environment.

**Consequence:** this prototype ships with a *synthetic* dataset generator,
seeded for full reproducibility, that uses ERCOT's real hub and load-zone
names (`HB_NORTH`, `HB_WEST`, `HB_HOUSTON`, `LZ_AEN`, etc.) and models
congestion with realistic seasonal shape (summer/winter premiums) and a
handful of illustrative stress-event spikes. Every synthetic record is
tagged `is_synthetic: true`, and the UI displays a persistent banner saying
so. The ingestion layer (`backend/app/ingestion.py`) is written against
ERCOT's actual published column layout, so a user with MIS access can drop
real CSVs into `data/raw/` and the exact same analytics/scoring code runs
against real data with zero changes. This is documented as a **required
follow-up** before any real-world use of the scores.

**Update (v1.1):** a separate, genuinely live data path is now also
integrated (FR-7). ERCOT's Public Data API (`api.ercot.com`) — distinct
from the MIS file browser above — is a real, free-to-register REST API
that does not expose CRR auction awards, but does expose live Day-Ahead
Market settlement point prices and binding-constraint shadow prices. Since
a PTP Obligation CRR's payoff is defined by ERCOT protocol as exactly the
Sink-minus-Source DAM price spread, this live feed is a legitimate, current
proxy for realized congestion value — see `README.md`'s "Live ERCOT data"
section for registration steps and `docs/prompt_journal.md` Entry 5 for how
this was found and validated. It remains a *separate, additive* capability
from the auction/synthetic dataset (FR-1 through FR-6): it supplies no
participant or MW-awarded data (the live API has no such endpoint), so the
Dashboard and Participants views are unaffected by whether it's configured.

**Update (v1.3):** a real SQL Server data source (FR-16) is now the
highest-priority tier for the auction/participant dataset. Until it (or
real CSVs) is connected, **every participant name shown anywhere in this
application is fictional** — placeholder company names from
`data_generator.py`, not real ERCOT CRR Account Holders. There is no
legitimate way to obtain real participant-level data short of a real
database load or real CSVs; ERCOT's live Public API (previous paragraph)
does not expose it. See `README.md`'s "Connecting to a real SQL Server
database" section for setup, and `docs/copilot_sql_connection_prompt.md`
for a ready-to-use handoff prompt for an engineer or AI assistant
connecting a real database on a different machine.

## 7. Non-Functional Requirements

- **Explainability over prediction.** No black-box scoring; every score
  must show its inputs (Section FR-5).
- **Determinism.** Given the same input data, all analytics and scores must
  be reproducible byte-for-byte (enables testing).
- **Testability.** Core analytics and scoring logic must be pure functions
  (no I/O), unit-testable in isolation from the web framework.
- **Separation of concerns.** Data ingestion, analytics, scoring, and API
  presentation are independent modules; the UI never computes analytics
  itself, only renders precomputed results.
- **Honesty about the demo.** Any screen that shows data must make clear
  whether that data is real or synthetic.

## 8. Acceptance Criteria (traced to FRs)

| Requirement | Acceptance test |
|---|---|
| FR-1 | `test_dashboard_endpoint_shape` asserts all dashboard fields present and top-5 lists correctly sized. |
| FR-2 | `test_participant_summary_aggregates_correctly`, `test_participant_detail_endpoint` |
| FR-3 | `test_pair_series_endpoint_valid_pair`, `test_pair_series_endpoint_filters_by_crr_type` |
| FR-4 | `test_basic_metrics_average_min_max_volatility`, `test_recent_vs_prior_year_requires_24_months`, `test_linear_trend_slope_rising_and_falling` |
| FR-5 | `test_score_all_pairs_ranks_strong_pair_above_weak_pair`, `test_every_score_has_explanation_and_valid_tier` |
| FR-6 | `ingestion._map_row` column-alias mapping (documented; exercise with a real CSV before production use) |
| FR-7 | `test_get_dam_settlement_point_prices_calls_correct_url_and_params`, `test_fetch_live_pair_records_end_to_end_with_mocked_client`, `test_live_lmp_spread_success_with_mocked_client`, `test_live_binding_constraints_success_with_mocked_client`, `test_live_lmp_spread_without_credentials_returns_501` (all mocked — no real network in CI; live credentials required for an end-to-end manual check) |
| FR-8 | `test_basic_metrics_pct_months_negative` |
| FR-9 | `test_pair_series_csv_export` |
| FR-10 | Verified against a real running `uvicorn` server (not just mocks): exact URL/param/response-shape compatibility and CORS headers confirmed by direct `curl`, documented in `docs/prompt_journal.md` Entry 7. `smoketest.js` (frontend, not part of the pytest suite) exercises the connection bar's demo-mode render. |
| FR-11 | `smoketest.js` exercises the TOU filter buttons and confirms a refetch occurs on click; `test_pair_series_endpoint_filters_by_crr_type` covers the underlying API parameter |
| FR-12 | `smoketest.js` exercises enabling compare mode, selecting a second pair via checkbox, and confirms no crash |
| FR-13 | `test_trailing_12mo_average_uses_last_12_months_only`, `test_trailing_12mo_average_uses_full_window_when_under_12_months`; seasonality strip verified via `smoketest.js` render check (pure client-side computation, no backend test needed) |
| FR-14 | `test_dashboard_tier_distribution_sums_to_pair_count`, `test_dashboard_monthly_mw_trend_shape` |
| FR-15 | `smoketest.js` confirms the panel renders and fails open (loading or clear-error state, never blank) when Open-Meteo is unreachable, which is the actual condition inside this project's build sandbox — see `docs/lessons_learned_and_future_work.md` for what could and couldn't be verified live |
| FR-16 | `test_load_records_from_sql_returns_correctly_shaped_dicts`, `test_load_records_from_sql_missing_table_raises_clear_error`, `test_get_engine_applies_connect_timeout_for_mssql` (all validated against real SQLite, proving the query/mapping logic without needing a live SQL Server or its ODBC driver); `test_system_status_reflects_sql_not_configured_by_default`; direct foreground check that a misconfigured SQL Server falls back to the synthetic demo in 0.08s with a clear warning, documented in `docs/prompt_journal.md` Entry 8 |

## v1.4 additions (2026-09) -- real data, market intelligence, Streamlit

Driven directly by Reggie Wade's review call (see `docs/prompt_journal.md`
for the prompt-evolution entry) and a re-investigation of ERCOT's MIS data
access (see `lessons_learned_and_future_work.md`).

- FR-17: Real CRR Auction Results (13 months, 1,120,889 records spanning
  Oct 2025 – Oct 2026) and a real participant registry (521 unique companies,
  377 appearing in the bundled auction data) are bundled in the repo
  (`data/raw/crr_auction/`, `data/reference/participants.csv`), fetched via
  `backend/scripts/fetch_real_ercot_data.py` from ERCOT's public,
  unauthenticated legacy MIS servlet endpoints.
- FR-18: Tracked Source/Sink pairs are data-driven (top 30 by notional,
  `analytics.discover_top_pairs`), derived from ~95,000 distinct pairs in
  the real dataset, not a fixed hand-curated list.
- FR-19: A "Hot Paths" panel (`analytics.top_paths`) surfaces the most
  active, most recurringly-congested corridors on the Overview page.
- FR-20: A per-participant "Strategy" view (`analytics.participant_strategy`)
  shows certificate count, Option/Obligation split, net Buy/Sell position,
  Pre-Award vs. Standard-auction share, and top corridors.
- FR-21: Real ERCOT weather-zone mapping (8 official zones) replaces the
  earlier 4 ad hoc regions, with a trailing-12-month seasonality time
  series per zone (`backend/app/weather_zones.py`).
- FR-22: The primary, shareable web application is a Streamlit app
  (`streamlit_app/Overview.py`) that imports the backend's analytics modules
  directly and reads the bundled real data with no second server process, so
  the whole project folder works standalone when zipped and moved elsewhere.
  FastAPI (`backend/app/main.py`) and the React frontend (`frontend/src/`)
  remain in the repo, unmodified, as the existing tested API contract and a
  reference UI respectively.

## 10. Future Enhancements (see also `docs/lessons_learned_and_future_work.md`)
- ~~Add DAM/RTM settlement point price feeds to cross-validate CRR value
  against realized congestion, rather than auction clearing price alone.~~
  **Done in v1.1** (FR-7) via the live ERCOT Public API.
- ~~**Live ERCOT MIS ingestion for the auction/participant data itself.**~~
  **Done (2026-09).** `backend/scripts/fetch_real_ercot_data.py` pulls real
  CRR Monthly Auction Results and the real Market Participants List
  directly from ERCOT's public legacy MIS servlet — no browser session,
  no authentication. See lesson 7 in `lessons_learned_and_future_work.md`.
- Wire the live-lmp-spread and binding-constraints endpoints (FR-7) into
  the interactive UI as an optional overlay when a backend is reachable —
  currently backend-only; see README's "why this isn't in the artifact."
- Portfolio-level view: a user's own CRR holdings scored in aggregate.
- Confidence intervals on the opportunity score based on sample size.
- Seasonality/time-of-use heatmap in the Explorer view (backend TOU
  filtering already supported via `?time_of_use=`, not yet surfaced in UI).
