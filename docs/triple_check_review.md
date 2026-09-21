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

## Deliverables checklist

| Deliverable | Status | Where |
|---|---|---|
| AI prompt journal showing prompt evolution and validation | ✅ | `docs/prompt_journal.md` |
| Requirements document generated and refined with AI | ✅ | `docs/requirements.md`, v1.4, 22 FRs traced to tests |
| Working prototype web application | ✅ | `streamlit_app/` (primary, shareable) backed by `backend/` (136 tests) |
| 60-minute presentation | ⚠️ | `presentation/ERCOT_CRR_Capstone_Presentation.pptx` -- still reflects an earlier feature set, needs updating before delivery (see lessons-learned) |
