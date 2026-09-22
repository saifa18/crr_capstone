# Triple-Check Review — v1.2

Three passes over the same codebase, each asking a different question.
This review exists because "does it run" and "is it actually good" are
different bars, and the capstone brief's own minimum-features list is the
one we're graded against — so that list is the checklist below, verbatim.

---

## Pass 1 — Head of Software Engineering

**Question: is this architecturally sound, or does it just demo well?**

| Check | Verdict | Evidence |
|---|---|---|
| Backend logic is pure/testable, not tangled with the web framework | ✅ | `analytics.py`/`scoring.py` are dict-in-dict-out pure functions; `main.py` only wires them to routes |
| Frontend is a real client of the backend, not a frozen fixture | ✅ (v1.2 fix) | `demoProvider`/`liveProvider` implement one interface; verified against a real running `uvicorn` server with `curl` — exact URL/param/response-shape match, CORS headers present |
| Test suite actually catches regressions, not just "it imported" | ✅ | 75 backend tests including behavior tests (e.g. `test_score_all_pairs_ranks_strong_pair_above_weak_pair` constructs a deliberately-wrong scoring engine scenario and checks it's caught) |
| Data pipeline is reproducible, not a one-off script | ✅ | `backend/scripts/export_snapshot.py` regenerates `data/snapshot.json` deterministically (seeded generator) |
| External integrations degrade honestly, not silently | ✅ | ERCOT live client: 501 when unconfigured, 502 with a real message on failure, never a blank/broken response. Weather panel: same pattern (loading → live data or a visible error, never blank) |
| No unverified claims presented as fact | ✅ | README explicitly states what was and wasn't verified for both the ERCOT and weather live integrations, including sandbox-specific network limitations discovered while building this |

**Open items (not blocking, tracked in `lessons_learned_and_future_work.md`):** no CI pipeline; no typed response models (raw dicts, not Pydantic) on API endpoints; `lru_cache`d dataset means a running server needs a restart to pick up new CSVs.

---

## Pass 2 — Senior Power Trader

**Question: would I actually open this instead of my own spreadsheet?**

| Check | Verdict | Evidence |
|---|---|---|
| Time-of-use matters and I can see it | ✅ (v1.2 fix) | Explorer has All/Peak-WD/Peak-WE/Off-Peak filter, previously backend-only |
| I care about recent months more than a 7-year average | ✅ (v1.2 fix) | Trailing-12-month average shown alongside all-time, both on the metric grid |
| I trade relative value, not one corridor in isolation | ✅ (v1.2 fix) | Explorer compare mode, up to 3 pairs overlaid |
| I want to know who else is active on a path | ✅ (v1.2 fix) | "Active Participants on This Pair" panel in the Explorer |
| I want to know which months actually congest | ✅ (v1.2 fix) | Seasonality strip, calendar-month average |
| I want the whole market's health at a glance, not just the top 5 | ✅ (v1.2 fix) | Dashboard tier-distribution bar (all pairs, not just top 5) and a 12-month MW trend |
| I want physical context for *why* a path congests | ✅ (v1.2 add) | Live weather panel: West/Panhandle wind (renewable output driver), Houston/DFW temperature (load driver), explicitly framed as context, not a signal input |
| I want the raw numbers in my own tools | ✅ | CSV export, both API-level and one-click in the UI |
| I don't want to be told what to bid | ✅ | Every score screen repeats "market intelligence... not trading advice"; weather panel explicitly says "context, not a forecast of CRR value" |

**Open items:** no next-auction calendar (would need live ERCOT calendar data this project doesn't have — flagged, not fabricated); no credit/collateral modeling; no saved watchlist/alerting (all in `lessons_learned_and_future_work.md`, not silently dropped).

---

## Pass 3 — Head of Frontend

**Question: does the UI hold together, or is it a pile of features?**

| Check | Verdict | Evidence |
|---|---|---|
| One visual language throughout | ✅ | Dark trading-terminal palette held consistently across all new widgets (tier bar, trend chart, weather panel match existing card/border/font tokens) |
| New features don't break existing ones | ✅ | Full smoke-test re-run after every change: all 4 tabs, TOU filters, compare mode, tier filter, search, CSV download, weather panel — all pass together, not in isolation |
| Failure states are designed, not accidental | ✅ | Weather panel has an explicit loading state and a distinct, honest error state (not a spinner forever, not a blank box) |
| Nothing is dead/unreachable capability | ✅ (v1.2 fix) | TOU and CRR-type filters were backend-only in v1.1; now surfaced. Pair-level participant data existed in the snapshot but had no UI; now surfaced |
| Search/filter affordances exist where lists get long | ✅ (v1.2 fix) | Signals tab: tier filter + text search |

**Open items:** no mobile/responsive layout (reasonable for a desktop trading-terminal use case, not attempted); no accessibility audit (aria labels, keyboard nav) — flagged, not addressed.

---

## Direct answers to the three questions raised this round

**"Why is the API not in there / why isn't there any actual data running through?"**
Two different integrations, two different answers:
- *ERCOT live data*: the client and endpoints are real and tested (27 mocked tests + a verified-against-a-real-running-server check), but they need *your* backend reachable from your browser. This chat sandbox cannot host a server that persists for your browser to call — that's a platform constraint, not an unfinished feature. Run `uvicorn` locally and use the Connect bar; it works, verified with `curl` against the real server.
- *Weather*: added this round. Open-Meteo needs no key and is CORS-open, so it has a real shot at working live even inside a sandboxed preview — but this specific build sandbox also blocks its domain (confirmed directly: `Host not in allowlist: api.open-meteo.com`). The panel is coded correctly and fails open with a clear message either way; it's expected to actually resolve real data when this app runs as a normal deployed page, which I can't fully verify from inside this sandbox and am not claiming to have verified.

**"Why isn't the home screen missing some data points?"** (points that were, in fact, missing)
Fixed: added tier distribution across *all* tracked pairs (not just the top 5), a trailing-12-month market-wide MW trend, and the weather context panel. All three came from an honest gap review, not from padding — the dashboard's own stated job ("summarizing recent auctions, active participants, and key Source/Sink pairs") wasn't fully met by a single-month snapshot alone.

## Minimum Features checklist (verbatim from the project outline)

| Minimum feature | Status | Where |
|---|---|---|
| Dashboard summarizing recent auctions, active participants, and key Source/Sink pairs | ✅ | Overview tab — now includes tier distribution and 12-month trend, not just latest-month figures |
| Participant analysis with historical activity | ✅ | Participants tab + per-pair participant cross-reference in Explorer |
| Source/Sink explorer with historical pricing and congestion trends | ✅ | Explorer tab — TOU filtering, comparison, seasonality |
| Basic analytics (average, min/max, volatility, trend) | ✅ | `analytics.basic_metrics` — also adds trailing-12mo average and % months negative beyond the minimum |
| Explainable opportunity score (Low/Medium/High) | ✅ | `scoring.score_all_pairs` — four named, weighted, inspectable factors |

---

## v1.4 pass (2026-09) -- real data, market intelligence, Streamlit

### Pass 1 -- Head of Software Engineering

| Check | Verdict | Evidence |
|---|---|---|
| Real-data ingestion doesn't disturb the existing tested FastAPI path | Yes | Bulk real data lives in `data/raw/crr_auction/`, a directory `ingestion.load_records()`'s flat-`data/raw` tier never reads -- all 93+ pre-existing tests pass unmodified |
| SQL dependency is no longer load-bearing for non-SQL use | Yes | `db.py`'s SQLAlchemy imports are now lazy, so `app.ingestion` (and the Streamlit app) import cleanly with zero SQL dependencies installed |
| New analytics are pure, tested functions | Yes | `discover_top_pairs`/`top_paths`/`participant_strategy` are dict-in/dict-out, covered by unit tests including the BUY/SELL netting edge case |
| Real-data parsing bugs were caught before shipping, not assumed away | Yes | Downloaded and parsed real ERCOT files during design; found and fixed (1) the Market Participants List is a zip wrapping the xlsx, not raw xlsx bytes (`extract_xlsx_from_zip`), and (2) the CRRAH sheet has a trailing footer row that leaked into the participant CSV until the filter required both NAME and SHORT_NAME present |

### Pass 2 -- Senior Power Trader

| Check | Verdict | Evidence |
|---|---|---|
| Real participant names, not fictional placeholders | Yes | 1,120,889 real CRR records from Oct 2025–Oct 2026; 377 real Market Participants joined against the real NP12-215-ER CRRAH registry; 521 total companies in the reference data |
| "Who's doing what" is answerable without paging through raw rows | Yes | Participant Strategy view: certificate count, Option/Obligation split, net position, Pre-Award share, top corridors |
| "What are the hot paths" is answerable at a glance | Yes | Overview's Hot Paths panel, ranked by real notional activity with a plain-language reason per path |
| Tracked-pair universe reflects real market activity, not a stale hand-picked list | Yes | ~95,000 distinct Source/Sink pairs in the real dataset; `discover_top_pairs` derives the top 30 from what's actually loaded |
| Weather is mapped to the zones ERCOT itself uses, with seasonality | Yes | 8 official ERCOT weather zones, trailing-12-month average-temperature series per zone |

### Pass 3 -- Head of Frontend

| Check | Verdict | Evidence |
|---|---|---|
| One shareable app, not a two-process setup to boot locally | Yes | Streamlit app imports backend modules directly; `streamlit run streamlit_app/Overview.py` is the only thing to run |
| Consistent visual language across all four Streamlit pages/tabs | Yes | Shared `lib/theme.py` page config + banner + CSS used by every page |
| Data-source truth is visible on every page, not just Overview | Yes | `render_data_source_banner` called at the top of every page |
| Verified live, not just read | Yes | Live QA pass clicked through all four pages, filters, search, and CSV export with real bundled data before this was called done |

**Open items (not blocking, tracked in `lessons_learned_and_future_work.md`):**
no automated Streamlit UI tests (matches this project's existing pattern of
smoke-testing the UI layer live rather than unit-testing it); presentation
deck still not updated for this round.

---

## v1.5 pass (2026-09) -- visual polish, Obligation/Option overlay, Binding Constraints

Requested explicitly as a final-approval gate: Senior Software Engineer,
Senior Power Trader, and Senior UX/UI Streamlit Designer, each reviewing
the same diff (Plotly charts replacing Streamlit's built-ins, a shared
color system, bordered card layout, an ERCOT corridor map, the
Obligation/Option overlay chart, and the new live Binding Constraints
tab) live against the real bundled dataset (1,120,889 records) and the
real, authenticated ERCOT Public API.

### Pass 1 -- Senior Software Engineer

| Check | Verdict | Evidence |
|---|---|---|
| No backend (`backend/app/*.py`) logic touched by this round | Yes | Entire round is scoped to `streamlit_app/`; all 136 backend tests pass unmodified throughout |
| One color meaning, one source of truth | Yes | `theme.COLORS` (Obligation green, Option amber, High/Medium/Low tier colors) imported everywhere a chart or badge needs one of these, never a duplicated hex literal |
| A real, reproducible crash was found and fixed before shipping, not papered over | Yes | `st.dataframe`/`st.plotly_chart`'s `width="stretch"` was found live (via a real Streamlit exception, not a code-review guess) to crash on the pinned Streamlit 1.38.0; fixed to `use_container_width=True` across every page and verified live afterward |
| The new live-API tab degrades honestly | Yes | `get_binding_constraints` returns one of three explicit states (not configured / API error / real data), matching the existing weather panel's fail-open pattern; capped at 15 pages and a 30-day UI window so a wide date range degrades to fast-but-truncated rather than slow |
| The Streamlit app loads its own credentials rather than depending on FastAPI having done so first | Yes (fixed this pass) | `streamlit_app/lib/data_loader.py` now calls `load_dotenv('backend/.env', override=False)` itself -- found missing during this pass's own review, confirmed live afterward that a completely standalone `streamlit run` correctly picks up real ERCOT API credentials with no other process involved |

**Open items (not blocking):** no automated tests for the Streamlit page files themselves (matches this project's established pattern of live smoke-testing the UI layer rather than unit-testing it).

### Pass 2 -- Senior Power Trader

| Check | Verdict | Evidence |
|---|---|---|
| Obligation and Option are genuinely comparable now, not toggled | Yes | Source/Sink Explorer plots both as separate colored lines on one chart with a shared legend and unified hover, replacing the old CRR-Type radio toggle |
| The corridor map adds real information, not decoration | Yes | Points are the actual tracked hubs/load zones (real lat/lon borrowed from their weather zone), sized by how many of the top-30 corridors touch that point -- not a generic stock map |
| Binding Constraints answers "why," not just "what" | Yes | Real, live ERCOT DAM shadow-price data: named constraint, contingency, shadow price, from/to station -- the physical grid element behind current congestion, verified live at 9,320 real constraints in a 7-day window |
| The two data clocks (settled auction history vs. live constraints) are kept honestly separate | Yes | Binding Constraints page explicitly states both windows side by side ("Live ERCOT data: 2026-09-13 to 2026-09-20... auction data on the other tabs is separate and as of 2026-10") rather than implying one timeline |
| Score/trend math itself is unchanged by this round | Yes (deliberate) | Live API data was explicitly kept out of the opportunity score and trend/consistency factors this round -- discussed and decided against, since splicing a multi-year price proxy across a changed grid topology into a score whose entire value proposition is "every number is auditable" would be an unvalidated bolt-on, the same category of decision this project already made once before for weather |

**Open items (not blocking):** no next-auction calendar; no credit/collateral modeling; no saved watchlist -- all pre-existing gaps, unchanged by this round.

### Pass 3 -- Senior UX/UI Streamlit Designer

| Check | Verdict | Evidence |
|---|---|---|
| Real charts, not placeholder built-ins | Yes | Every chart across all 5 pages is now Plotly (`st.plotly_chart`), with real legends, hover tooltips, and consistent theming -- no more bare `st.line_chart`/`st.bar_chart` |
| Visual hierarchy, not one long scroll | Yes | Every logical section on every page is wrapped in `st.container(border=True)`, verified live as visually distinct cards, not just a code-level wrapper |
| Color carries consistent meaning across pages | Yes | Obligation/Option and tier colors are pixel-identical wherever they appear (Overview's tier chart, Explorer's overlay, Opportunity Signals' tier dots) because all three pull from the same `theme.COLORS` dict |
| Nothing looks like a bare prototype anymore | Yes | Corridor map, KPI deltas, and the fifth (Binding Constraints) tab all read as considered product surfaces, not a "we ran out of time" gap |

**Open items (not blocking):** no mobile/responsive layout (reasonable for a desktop trading terminal, unchanged from prior rounds); no accessibility/keyboard-nav audit.

---

## v1.6 pass (2026-09-21) -- real settlement-price signals, participant P&L

Triggered by direct stakeholder feedback (Reginald Wade, feedback call
2026-09-21): the Opportunity Signals tab was showing CRR auction bid
prices and calling them a settlement signal, and the Participants tab had
no way to see who actually won or lost money holding a corridor. Both are
now driven by real ERCOT Day-Ahead Market settlement point prices (SPP).

### Pass 1 -- Senior Software Engineer

| Check | Verdict | Evidence |
|---|---|---|
| A real, currently-broken bug was found and fixed, not assumed away | Yes | Live-credentialed testing of `live_congestion.fetch_settlement_point_hourly_prices` during scoping raised `ValueError: could not convert string to float: '01:00'` -- ERCOT's real API now returns `hourEnding` as an `"HH:00"` string, not the bare integer the client and its mocked tests assumed. Fixed with `_parse_hour_ending`, regression-tested against the real string shape, and re-verified live afterward (real rows returned, no traceback) |
| New analytics are pure, tested functions | Yes | `aggregate_to_daily_series`/`aggregate_to_period_settlement_value` are dict-in/dict-out, unit tested including the Option-floor and sum-vs-average distinction |
| New live endpoints follow the existing degrade-honestly pattern | Yes | `/settlement-history` and `/settlement-leaderboard` reuse the exact `_require_live_api`/`is_live_api_eligible`/501/422/502/404 shape every other live endpoint already uses -- no new failure mode invented |
| Verified against the real, live, authenticated ERCOT API, not just mocks | Yes | Both new endpoints called live end-to-end during this round: `settlement-history` returned real daily Obligation/Option prices for HB_WEST/HB_HOUSTON; `settlement-leaderboard` returned real, ranked, named participants (e.g. Luminant, DC Energy Texas) with real computed realized-$ figures for HB_WEST/LZ_WEST, 2026-08 |
| All pre-existing tests still pass | Yes | 158 backend tests pass (136 pre-existing + 22 new), zero modifications to `scoring.py`'s auction-clearing-price math |

### Pass 2 -- Senior Power Trader

| Check | Verdict | Evidence |
|---|---|---|
| The bid-price/settlement-price distinction is now taught by the UI itself, not just known by the builder | Yes | Opportunity Signals' subline and per-card copy now explicitly say the tier score is built from auction *bid* prices while the expandable chart is the real *settlement* price -- directly answering the correction Reginald gave live ("those are only your bid prices... those aren't your settlement prices") |
| Settlement value is computed exactly the way a trader would by hand | Yes | Obligation payoff = sink SPP − source SPP (can be negative, you owe ERCOT); Option payoff = max(that, 0) (never owe) -- literally the math walked through live in the feedback call, not a new invented formula |
| "Who owns this path and what did they make" is answerable without a spreadsheet | Yes | Participants' new Winners & Losers panel: pick a corridor + month, see every participant's real realized $ for that exact period, ranked, MW and CRR type shown alongside |
| Real settlement history goes back far enough to be useful, not just a snapshot | Yes | `/settlement-history` defaults to January 1st of the current year through today per Reginald's explicit "just go back to January 1st" guidance, capped at 400 days |
| Illustrative synthetic corridors are never silently given fake settlement numbers | Yes | `live_eligible` (from `domain.is_live_api_eligible`) gates both new UI features; a `*_RN` synthetic-node corridor shows an explicit "not available for this corridor" message instead of a chart or leaderboard row |

### Pass 3 -- Head of Frontend

| Check | Verdict | Evidence |
|---|---|---|
| New features match the existing visual language | Yes | Settlement chart reuses `Explorer.jsx`'s exact recharts/`LineChart`/color-token pattern (green Obligation, amber Option); leaderboard reuses the existing `panel`/`field-row`/`table` classes, no new CSS |
| Nothing was removed that was already working | Yes | The Low/Medium/High tier cards, their factor bars, and explanations are unchanged -- the real-settlement chart is additive (an expand/collapse per card), not a replacement |
| Loading/empty/error states are designed, not accidental | Yes | Both new panels have an explicit loading message, a distinct "not available for this corridor" state, and a distinct "no data for this window/month" state -- verified live in the browser preview for all three |
| Verified live in a real browser against the real backend, not just unit tests | Yes | Both reworked pages driven end-to-end in a live preview: Signals' chart expanded and rendered real West Hub/West Load Zone daily prices; Participants' corridor filter and Winners & Losers leaderboard both loaded real, ranked, named-participant data for 2026-09 |

**Open items (not blocking):** the Participants page's corridor filter and the new leaderboard don't yet have an "All time" or multi-month view (Reginald's guidance was explicitly per-month, given data volume -- a wider view is future work, not a silent gap); no automated frontend tests for the new chart/leaderboard components (matches this project's established pattern of live browser smoke-testing the React layer rather than unit-testing it).

---

## v1.7 pass (2026-09-21, same day) -- Path Settlements is now the primary signal, not a score

A follow-up round, same day as v1.6, driven by a more detailed written spec:
promote real settlement history to the primary experience (rename
"Opportunity Signals" to "Path Settlements" in the UI; demote, don't
delete, the Low/Medium/High auction-based score), make the settlement math
itself reusable/tested pure functions, defend against missing/null SPP
data, and fix a real efficiency problem in the prior round's design
(fetching every corridor's settlement data independently would have
redundantly re-fetched shared hub nodes).

| Check | Verdict | Evidence |
|---|---|---|
| Settlement formulas are standalone, reusable, tested functions | Yes | `compute_obligation_settlement`/`compute_option_settlement` in `live_congestion.py`, covered by the exact (40,50)/(50,40)/(40,40) cases plus explicit missing-price ValueError tests |
| Missing SPP is never silently treated as $0 | Yes | `fetch_settlement_point_hourly_prices` now skips a null-price row instead of crashing or defaulting; `compute_obligation_settlement`/`compute_option_settlement` raise `ValueError` on `None` rather than coercing |
| No redundant ERCOT calls when many corridors share a node | Yes (fixed this pass) | `_cached_node_hourly_prices` (15-min `_ttl_cache`) is the single fetch path for every settlement endpoint; a live test with two corridors sharing `HB_WEST` confirms exactly one real fetch for that node, verified by both a unit test (mocked call-count) and a live run (13.7s cold, 0.02s warm, for all 13 real corridors) |
| The primary UX answers "how did this path settle," not "what score did we assign it" | Yes | Path Settlements (still routed at `/signals`) leads with an always-visible per-corridor sparkline (from the new bulk `/api/pairs/settlement-summary`) and a click-through detail view with the full YTD chart, latest/avg/min/max, and a Path-Settlement/Source-vs-Sink toggle; the old tier score is one demoted, clearly-labeled line in that detail view, not deleted (`scoring.py` and `/api/opportunity-scores` are untouched, still tested) |
| Wording never implies "profit" where the data doesn't support it | Yes | Renamed `realized_value` → `settlement_value` end to end (backend field, frontend column, panel copy): "Path Settlement Value," with an explicit note that acquisition cost/fees aren't in this dataset |
| Verified live against the real, credentialed ERCOT API | Yes | `/api/pairs/settlement-summary`, the enriched `/settlement-history` (with `source_daily`/`sink_daily`/`summary`), and the `crr_type` participant filter were all exercised live in a running browser preview against the real backend; a real ERCOT `HTTP 429` was hit and surfaced as a clean, actionable error during this verification, not a crash -- confirming the existing retry/error-surfacing design holds up under actual rate-limiting |
| All previously-passing tests still pass | Yes | 172 backend tests pass (up from 158), `vite build` succeeds; no lint/typecheck tooling exists in this repo to run beyond that |

**Open items (not blocking):** the always-visible corridor list defaults to the current calendar month (not YTD) specifically because a YTD bulk fetch across ~20 distinct real nodes is slow on a cold cache (confirmed live, ~14s) -- the per-path detail view still offers the full YTD range on demand, where it's only 2 nodes; a "instrument type" field on the corridor list itself was intentionally not added, since a corridor isn't itself Obligation- or Option-typed -- both payoffs are shown together in the detail chart instead.

---

## v1.8 pass (2026-09-22) -- final demo polish: pagination, cleanup, and honest simplification

The pre-demo pass for a live audience of power traders. Three kinds of
change: (1) server-side pagination for every large real-data table that
was still fetching everything at once (Certificates, Path settlement
value, Binding Constraints -- 9,190+ real rows in a 7-day window), (2)
removing a classification that didn't hold up to scrutiny, and (3) a
documentation/repo pass so the project matches what actually ships.

| Check | Verdict | Evidence |
|---|---|---|
| Binding Constraints' severity tiers were arbitrary, not ERCOT-defined, and confusing in a live demo -- removed, not replaced | Yes | High/Medium/Low was an even tertile split of the currently-loaded window's own shadow prices (never a fixed ERCOT threshold) -- transparent, but still an invented classification on top of real data. Removed end to end: `_constraint_tier_thresholds`/`_constraint_tier` deleted from `main.py`, `tier` query param and `tier_thresholds` response field removed, `.tier-chip` CSS and the frontend severity filter/badges removed. The real Shadow price ($/MWh) column is what's left -- no replacement score invented |
| A real, previously-undiscovered ERCOT data-quality bug was found and fixed, not assumed away | Yes | Binding Constraints' raw `hourEnding` field is ERCOT's zero-padded "HH:00" string (confirmed live) -- the exact same shape already fixed once for the settlement-price endpoint, but never applied here, so the UI was showing a raw "24:00" string. Every string field (`constraintName`, `contingencyName`, `fromStation`, `toStation`) also comes back from ERCOT with leading whitespace baked in. Both now normalized once at the source in `_binding_constraints_cached` |
| Hour and Constraint are deliberately ONE combined field, per explicit product direction, not two columns | Yes (reversed from an earlier round) | An earlier pass split these into separate columns; this pass recombines them into one "HourEnding : Constraint" column with a readable `hour : constraint_name` separator (not the raw unseparated concatenation that originally prompted confusion) -- the underlying values are still the cleaned, parsed fields from the fix above, just displayed together |
| Tooltips actually render now, on every page, in every table position | Yes (fixed this pass) | Root cause: the Binding Constraints table's `overflow-x: auto` wrapper (needed for horizontal scroll) forces `overflow-y: auto` too per the CSS spec, which clipped every upward-opening absolutely-positioned tooltip bubble entirely out of view -- confirmed by measuring the bubble's rect landing above its scrolling ancestor's own top edge. `InfoTip.jsx` now renders via a React portal to `document.body`, positioned in viewport coordinates that auto-flip/clamp against any ancestor's clipping -- verified live on both edge columns |
| Server-side pagination is real, not a client-side slice | Yes | `/api/live/binding-constraints` and `/api/settlement-leaderboard` both apply every filter to the full dataset, sort, then paginate -- `total`/`total_pages` reflect the fully filtered set. The long-standing "Previous returns to a stale page" class of bug (root-caused earlier this project for the Certificates table: a `page === 1` special case in the fetch effect that assumed page 1 was always already loaded) was checked for and avoided in every new paginated section by computing the effective page synchronously within one fetch effect, never a separate "reset page" effect racing the fetch |
| Confirmed-dead output was found and removed, not left to rot | Yes | `/api/dashboard`'s `tier_distribution` and `top_opportunity_pairs` fields (and the `scoring.score_all_pairs` call producing them) were a Streamlit-era dashboard chart the React rebuild never ported over -- confirmed zero frontend references before removing. The opportunity score itself is untouched and still real: `/api/opportunity-scores` and `scoring.py` remain fully in place, still used as Path Settlements' demoted secondary signal |
| Nothing was deleted without checking references first | Yes | `weather_zones.py` and `/api/corridor-map`/`/api/weather` were found to have no current frontend consumer either, but were deliberately NOT removed this pass -- `weather_zones.py` is a shared module (corridor-map's zone/lat-lon reference data), and both endpoints are fully working, tested, and pose zero demo risk sitting unreached; a bigger, more permanent deletion than the confirmed-dead dashboard fields above, flagged for a future pass rather than acted on under uncertainty |
| No synthetic data can reach the live demo silently | Yes (confirmed, not assumed) | `/api/system/status` checked live: `active_data_source: "ercot_mis_real"`, `data_source_warning: null` -- the real bundled dataset (1,120,889 records) is what's actually serving every request right now. The synthetic generator (`data_generator.py`) remains as a last-resort, clearly-labeled fallback tier only, unreachable unless the real bundled data and SQL Server are both absent |
| All previously-passing tests still pass, minus the ones for deliberately-removed behavior | Yes | 192 backend tests pass (down from 194: one dedicated severity-tier test removed, two dashboard tests merged into one reflecting the removed fields; several new pagination/normalization tests added net of those removals), `vite build` succeeds |

**Open items (not blocking):** `presentation/ERCOT_CRR_Capstone_Presentation.pptx` was not regenerated this pass and still reflects an earlier feature set -- `docs/DEMO_WALKTHROUGH.md` is the primary live-demo aid for this round instead; `weather_zones.py`/`/api/corridor-map`/`/api/weather` are real, tested, working code with no current UI consumer -- a deliberate non-deletion under uncertainty, not an oversight (see above).

---

## Deliverables checklist

| Deliverable | Status | Where |
|---|---|---|
| AI prompt journal showing prompt evolution and validation | ✅ | `docs/prompt_journal.md` |
| Requirements document generated and refined with AI | ✅ | `docs/requirements.md`, v1.4, 22 FRs traced to tests |
| Working prototype web application | ✅ | `frontend/` (React/Vite console, the sole primary UI) backed by `backend/` (192 tests) -- the earlier `streamlit_app/` has been fully retired |
| Live demo walkthrough | ✅ | `docs/DEMO_WALKTHROUGH.md` |
| Glossary | ✅ | `docs/CRR_GLOSSARY.md` |
| 60-minute presentation | ⚠️ | `presentation/ERCOT_CRR_Capstone_Presentation.pptx` -- still reflects an earlier feature set, needs updating before delivery (see lessons-learned) |
