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

## Deliverables checklist

| Deliverable | Status | Where |
|---|---|---|
| AI prompt journal showing prompt evolution and validation | ✅ | `docs/prompt_journal.md`, 9 entries |
| Requirements document generated and refined with AI | ✅ | `docs/requirements.md`, v1.4, 22 FRs traced to tests |
| Working prototype web application | ✅ | `backend/` (93 tests) + `frontend/` (connectable to it) + `streamlit_app/` |
| 60-minute presentation | ✅ | `presentation/ERCOT_CRR_Capstone_Presentation.pptx` (not yet updated for v1.4 — see lessons-learned) |
