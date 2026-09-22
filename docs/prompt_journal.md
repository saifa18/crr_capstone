# AI Prompt Journal

This journal documents the actual AI-assisted workflow used to build this
prototype in a single Claude session, including the decision points,
verification steps, and one real course-correction. Use this as the spine
of your own journal — replace/extend it with the prompts *you* send Claude
as you iterate on the app for your own capstone submission (e.g., asking
for a new chart, a new metric, or a UI change), and keep this same
format: **prompt → what Claude did → how it was validated → what changed
as a result.**

---

## Entry 1 — Framing the requirements

**Prompt (paraphrased from the capstone brief):**
> Build a prototype web app that analyzes ERCOT CRR markets: identify major
> participants, analyze historical Source/Sink pricing, visualize trends,
> and generate an explainable opportunity signal for bidding investigation.

**What Claude did:** Rather than jumping straight to code, Claude first
searched ERCOT's public site to establish ground truth on (a) what CRR
auction data ERCOT actually publishes, and (b) whether it's programmatically
downloadable from this environment.

**Validation:** Confirmed via `ercot.com/mp/data-products` that ERCOT
publishes real historical CRR Auction Results (NP7-802-M long-term,
NP7-803-M monthly), including Source, Sink, CRR type, clearing price, and
CRR Account Holder — but the download center is a JS-driven, session-based
file browser with no stable unauthenticated URL, confirmed by a direct
`web_fetch` returning an empty (JS-rendered) file list.

**Result / course correction:** Rather than silently faking "real-looking"
numbers or blocking on data access, Claude made the limitation explicit in
`requirements.md` §6, built a clearly-labeled *synthetic* generator
calibrated to ERCOT's real hub/load-zone names and realistic congestion
seasonality, and wrote the ingestion layer against ERCOT's actual published
CSV column layout so real data can be substituted later with zero code
changes. This is the single most important "prompt evolution" in this
project: **the honest answer to "can we get real data?" changed the
architecture**, not just a caveat in the README.

---

## Entry 2 — Choosing what "explainable opportunity score" means

**Prompt (internal refinement, the kind you should send Claude if the first
answer feels like a black box):**
> The opportunity score needs to be explainable — a user should be able to
> see *why* a pair is High vs Low, and it should not be a predictive model
> (scope says "market intelligence... rather than predicting trading
> outcomes").

**What Claude did:** Rejected an ML/regression approach in favor of a
transparent, weighted rule-based composite over four named factors: value
level (35%), trend (20%), directional consistency (25%), and market
liquidity (20%) — each independently computed from `analytics.py` outputs,
each shown to the user with its own sub-score and a plain-language
sentence.

**Validation:** `test_every_score_has_explanation_and_valid_tier` asserts
every score carries all four factor sub-scores, weights summing to 1.0,
and at least 3 explanation sentences.
`test_score_all_pairs_ranks_strong_pair_above_weak_pair` constructs a
synthetic "obviously strong" pair (high, rising, consistent, liquid) and an
"obviously weak" one (low, flip-flopping sign, thin participation), and
asserts the scoring engine ranks them correctly — i.e., the score reacts to
the factors it claims to react to, not just to noise.

**Result:** Kept the rule-based design; documented explicitly in
`scoring.py`'s module docstring *why* ML was rejected, so a future
iteration doesn't accidentally reintroduce a black box.

---

## Entry 3 — Separating "real analytics" from "the demo you can click through right now"

**Prompt (implicit, from the deliverable list requiring a "working
prototype"):**
> The deliverable needs to actually run and be demoable in a 60-minute
> presentation, not just be a plan.

**What Claude did:** Built two things that share the exact same
analytics/scoring code: (1) a real FastAPI backend + pytest suite (30
tests, all passing) that can run against synthetic or real data, and (2) an
interactive React dashboard artifact, pre-loaded with a JSON snapshot
produced by that same backend code, so it's clickable in-chat immediately
without standing up a server.

**Validation:**
- `cd backend && python -m pytest -q` → **30 passed**.
- The React artifact's JSX was syntax-checked with a real Babel parse
  (`@babel/preset-react` + `@babel/preset-env`) before delivery.
- The compiled component was then smoke-tested with `react-test-renderer`:
  rendered all four tabs (Overview, Explorer, Participants, Signals),
  simulated clicking through pair selection, participant selection, and
  cross-tab navigation via `goToPair`, and confirmed no runtime errors —
  before ever being shown to the user.

**Result:** Both artifacts ship together, and the README explains exactly
how to swap the artifact's embedded snapshot for a live `fetch()` against
the FastAPI backend once the user wants to run it outside the chat.

---

## Entry 5 — Finding ERCOT's real API, and keeping it additive

**Prompt:**
> Find the best skills for this as a master developer, make sure this goes
> beyond what they were looking for in a reasonable manner, make sure a
> senior power trader would actually use this, and utilize an API to get
> real ERCOT information so it's as realistic and usable as possible.

**What Claude did, step by step:**
1. Tried the `npx skills` marketplace CLI and Anthropic's own
   `search_skills`/`search_plugins` catalog tools first, per instructions,
   rather than assuming none existed. Both came back empty/unreachable in
   this sandboxed environment (the marketplace registry isn't on the
   network allowlist here) — reported that plainly rather than pretending
   the search worked or silently skipping it.
2. Re-investigated ERCOT data access from scratch instead of assuming
   Entry 1's finding was the whole story. That earlier entry was correct
   about the CRR-auction-specific MIS file browser, but incomplete: ERCOT
   also runs a genuinely separate, free-to-register **Public Data API**
   (`api.ercot.com`) that Entry 1 didn't surface. Confirmed via ERCOT's own
   developer portal, its GitHub discussion forum (`ercot/api-specs`), and
   the open-source `gridstatus` client's source code — cross-checking three
   independent sources before committing to an implementation, since
   ERCOT's own docs describe this API as a "work in progress."
3. Verified *what* that API actually exposes before designing around it
   (same discipline as Entry 1): no CRR auction awards, but real, live
   Day-Ahead Market settlement point prices and shadow prices — confirmed
   the real query parameter names and response shape from actual working
   `curl` examples other developers posted in ERCOT's discussion forum,
   not just from documentation prose.
4. Recognized the DAM price spread between two settlement points is not
   an approximation of CRR value but ERCOT's literal Obligation-CRR
   settlement formula (Sink price − Source price), which made a live
   integration defensible rather than a stretch.
5. Kept the new live-data path (`ercot_live.py`, `live_congestion.py`) as
   an **additive, separate capability** rather than replacing or entangling
   it with the existing tested auction/synthetic path (`ingestion.py`,
   `analytics.py`, `scoring.py`). The live API has no participant/MW data,
   so it only ever feeds the Explorer's price series, never Participants
   or the opportunity score's liquidity factor — avoiding the mistake of
   quietly blending "no data available" with "no liquidity."
6. Added a downside-risk metric (% months negative) and CSV export,
   reasoning from "what would a senior power trader actually push back on"
   rather than just adding features for their own sake: an average alone
   hides how often a path would have cost money, and a trader will always
   want the raw series in their own spreadsheet, not just a chart.

**Validation:**
- 27 new tests (`test_ercot_live.py`, `test_live_congestion.py`), all
  mocked — no real network calls in the test suite, since real credentials
  aren't available in this environment, but every line of *this project's*
  logic (auth flow, retry/backoff, pagination, TOU classification, spread
  computation, monthly aggregation, error messages) is exercised.
- 10 new API-layer tests covering both the "not configured" (501) and
  "configured and working" (mocked client) paths for every new endpoint.
- Full suite: 68/68 passing, re-run from scratch after every change,
  including a fresh unzip-and-reinstall of the exact shipped deliverable.
- Beyond the mocked unit tests: booted the real `uvicorn` server (not just
  pytest's `TestClient`) and hit the new endpoints live. `/api/live/status`
  and the 501/422 guard paths behaved correctly. With placeholder
  credentials, confirmed the client makes a genuine outbound HTTPS request
  to ERCOT's real token URL and degrades cleanly (a `502`, not a crash) —
  in this build environment the request was actually rejected by the
  environment's own network allowlist rather than by ERCOT, so a true
  logged-in pull is still unverified and flagged as the first thing to
  check after registering (see README).
- The UI changes (new metric, CSV button, updated banner copy) were
  re-validated with the same Babel-parse + react-test-renderer smoke test
  used in Entry 3, extended to assert the new button and metric actually
  render, before being shown.

**Result:** kept all of it. The live-API path is real and tested but
correctly scoped as a backend capability (see README for why it isn't
wired into the in-chat artifact — that surface can't reach `api.ercot.com`
regardless of what this project does).

---

## Entry 6 — Three-persona critique, and rebuilding the frontend around one interface

**Prompt:**
> Become a power trader, senior software engineer, and frontend dev.
> Critique this application against the project criteria, focused on the
> web application portion. Make sure a power trader would actually use
> this, then give me the final version.

**What Claude did:** Wrote the critique first, in writing, before touching
code — three short lists of concrete gaps, not a vague "looks good."
The single biggest one: the interactive dashboard embedded one static JSON
blob and never actually talked to the backend it sat on top of, despite
the backend having a full REST surface with CORS enabled. Rather than
patch around that, rebuilt `component_body.jsx` around one `provider`
interface with two implementations (`demoProvider` reading the snapshot,
`liveProvider` calling a real backend over `fetch`), so every view —
filters, comparison, everything — works identically in both modes instead
of forking the UI in two. Also closed four specific trader-facing gaps
named in the critique: TOU/CRR-type filtering (backend already supported
it; UI never exposed it), a trailing-12-month average next to the all-time
one, a seasonality strip, and pair-to-pair comparison.

**Validation:**
- Backend: 73 tests passing (2 new: pair-level participant endpoint,
  health check).
- Frontend: full Babel parse, then an **async-aware** react-test-renderer
  smoke test — the previous smoke-test pattern only handled synchronous
  renders, and this rebuild introduced real `useEffect`+`fetch` async data
  flow, so the test harness itself had to be upgraded (explicit `flush()`
  helper awaiting multiple microtask ticks) to actually exercise it rather
  than false-passing on a still-loading tree.
- Beyond mocks: booted the real `uvicorn` server and hit the exact URLs/
  params the new `liveProvider` constructs with `curl`, confirming
  response shape and CORS headers match what the frontend expects — this
  is what "the live-connect code is correct" actually rests on, not just
  that it compiles.

**Result:** kept all of it. One thing surfaced mid-build and fixed
immediately: the tab-switching logic in the smoke test broke because the
new Connect button shifted button indices — a reminder that UI tests
keyed to position rather than semantics are fragile, fixed by querying a
style attribute unique to nav buttons instead.

---

## Entry 7 — "Why isn't there any actual data running through," and adding weather

**Prompt:**
> Why is the API not in there? Why isn't there no actually data running
> through? Why isn't there no weather data maybe from open-meteo.com —
> use your best judgment. Why is the home screen missing data points?
> Triple-check this against the project outline.

**What Claude did:** Answered the "why" plainly instead of just fixing
silently — the ERCOT live path needs a backend reachable from the user's
browser, which this chat sandbox cannot host persistently for someone
else's browser to call; that's a platform constraint, stated as such, not
glossed over. For weather, evaluated the suggestion on its merits before
building anything: wind at West Texas/Panhandle and temperature at
Houston/DFW are the actual physical drivers of the congestion this app
measures, so weather isn't decorative here — it's real context for the
numbers already on screen. Verified Open-Meteo needs no API key and is
CORS-open (confirmed via search results showing a working browser
`fetch()` example) before writing any code, then built a panel that
attempts a genuinely live fetch on every render and fails open with a
visible message rather than silently showing nothing. Separately, audited
the Dashboard against the capstone brief's own wording ("summarizing
recent auctions, active participants, and key Source/Sink pairs") and
found it only showed the single latest month — added a full tier
distribution (all pairs, not just the top 5) and a 12-month MW trend.

**Validation:**
- Backend: 2 new tests for the enriched `/api/dashboard` fields
  (`tier_distribution` sums to the pair count; `monthly_mw_trend` is
  chronological and matches the latest month) — 75 passing total.
- Frontend: smoke test extended to confirm the weather panel renders
  without crashing and lands in one of its two designed states (loading or
  a clear error), never blank.
- Directly tested whether Open-Meteo is reachable from *this specific*
  build sandbox (not assumed): it is not — `Host not in allowlist:
  api.open-meteo.com`, the same category of restriction as the ERCOT
  domain. Documented this honestly rather than claiming the weather panel
  was verified live, while still explaining why it's expected to work
  differently in a real deployed page (a different runtime with a
  different network policy than this build sandbox's tool access).
- Wrote `docs/triple_check_review.md`: a structured pass from each of the
  three requested personas against the capstone brief's own minimum-
  features list, verbatim, not a paraphrase — so gaps are checked against
  what was actually assigned, not against a vibe of "good enough."

**Result:** kept all of it. Explicitly did not claim the weather integration
was "verified working" when what was actually verified was the opposite —
that it fails open correctly when unreachable. The honest framing is worth
more here than a confident-sounding but unverifiable claim.

---

## Entry 8 — Connecting to a real SQL Server on a different machine

**Prompt:**
> Finish it all. Keep in mind the backend will be connected to a SQL
> server but it is not in this computer but in a different computer, so
> write it so I can tell the AI on the other computer to hook the backend
> up to the SQL server and it will work perfectly. Zip it for email, and
> write a prompt for GitHub Copilot to connect it and make sure no errors
> happen.

**What Claude did:** Built `db.py` as an environment-variable-configured
SQLAlchemy layer rather than hardcoding any connection details, precisely
because the database's location is unknown at build time (a different
machine, not yet specified). Supported both a single `DATABASE_URL` and
separate host/credential variables (including Windows trusted-connection
auth, common in enterprise SQL Server environments) since it wasn't
possible to know in advance which auth style the real target uses. Wrote
the table schema as a literal T-SQL script, not just Python migrations, so
a DBA who prefers running SQL directly — or who wants to point a VIEW at
an existing differently-shaped table instead of moving data — has an exact
contract to match. Wired SQL in as the *highest-priority* real data
source, ahead of the existing CSV path, with each tier degrading
independently and explaining itself via a new `data_source_warning` field
rather than silently substituting different data.

**Validation:** Before treating any of this as done, actually tried to
break it inside this build environment: confirmed `pyodbc` (needed for
real SQL Server access) can't even import here because the underlying
system ODBC driver isn't installed — the exact situation many real
deployments will hit before they've installed it — and confirmed that
failure is caught cleanly and turned into a clear error rather than
crashing anything. Wrote 16 tests against real SQLite (not mocks) to prove
the query/mapping logic itself is correct, independent of the network/
driver layer this environment can't exercise. Attempted a live end-to-end
check with a deliberately bad SQL host and hit a real, unrelated hang in
this specific sandbox session (`ps`/`pkill`-related, not a bug in the
code) — rather than push through it, fell back to a safer, equally
rigorous foreground check with a hard `timeout` wrapper, which is what
actually caught a real bug: an unreachable host had no connection timeout
and would have hung a production request for 60+ seconds on the OS
default. Fixed it (`SQL_SERVER_CONNECT_TIMEOUT_SECONDS`, default 10) and
re-verified the fix with a mocked test, since the real driver still isn't
importable here to test it end-to-end directly.

**Result:** kept the timeout fix — found because of the testing hang, not
despite it. Also answered a direct follow-up question in the same
session ("are the participants real?") by pointing at exactly what was
already documented: no, they're fictional placeholders, and unmistakably
so once SQL or CSVs are connected instead.

---

## Entry 9 — Real-data + Streamlit rebuild (2026-09)

**Prompt:** Reggie Wade's review call flagged that the app should use
real ERCOT auction data (a full year), map real participant IDs to real
names, look at settlement prices (not just LMPs), map weather to
load-zones/hubs with a seasonality view, and answer "who's doing what" /
"what are the hot paths." Separately, the deliverable needed to become a
single shareable Streamlit app rather than a two-process React/FastAPI
setup.

**Validation before building anything:** rather than trust the project's
own prior "CRR auction data requires a browser session" conclusion,
directly tested ERCOT's legacy MIS servlet endpoints with `curl` and found
them reachable, unauthenticated, and serving the real files -- downloaded
and parsed a real auction result and a real participant list before
writing any ingestion code against assumed column names. This surfaced
real bugs: (1) the Market Participants List is a zip wrapping the xlsx,
not raw xlsx bytes; (2) the CRRAH sheet has a trailing footer/timestamp
row. Both would have shipped silently in code that only mocked the real
files.

**Design decisions made with the user, not assumed:** confirmed BUY/SELL
netting semantics (net position, not gross double-count) and the
tracked-pair universe (fully data-driven top-N, not a fixed curated list)
as explicit choices before writing the design spec, since real data made
both of these live architectural questions the synthetic dataset had never
raised.

**What Claude did:** Built `backend/scripts/fetch_real_ercot_data.py` to
pull real CRR Monthly Auction Results (1,120,889 records across 13 months,
Oct 2025–Oct 2026) and the real Market Participants List (521 unique
companies, 377 in the bundled auction data) from ERCOT's public legacy
MIS servlet. Implemented `analytics.discover_top_pairs` to derive the top
30 tracked pairs from the ~95,000 distinct pairs actually present in the
real data, not a hand-curated list. Added `analytics.top_paths` for the
Hot Paths overview panel and `analytics.participant_strategy` for the
per-participant Strategy view. Built the Streamlit app
(`streamlit_app/Overview.py`) as the primary shareable deliverable,
importing backend analytics modules directly. Added real ERCOT weather-zone
mapping (8 official zones) with trailing-12-month seasonality per zone.

**Validation:**
- Real-data fetch: downloaded and parsed real ERCOT files; fixed both
  discovered parsing bugs before committing to production code.
- Live QA pass: clicked through all four Streamlit pages
  (Overview, Source/Sink Explorer, Participants, Opportunity Signals),
  filters, search, and CSV export with real bundled data before calling
  done.
- Backend tests: 93 tests pass (pre-existing suite + new analytics tests).
- Weather zones: confirmed 8 official ERCOT zones; trailing-12-month
  seasonality series computes and renders correctly.
- Streamlit entry point: verified `streamlit run streamlit_app/Overview.py`
  as the canonical run command (not `app.py` — renamed during live QA for
  cleaner nav label).

**Result:** kept all of it. The live weather panel and live ERCOT MIS
servlet fetch were both directly confirmed working end-to-end against real
production servers during this work — real temperatures (e.g. 80-87°F
across the 8 zones) displayed during the live browser QA pass.

---

## Entry 10 — Pivoting off Streamlit, and finding a real data bug in the process

**Prompt:** Whether to keep Streamlit or build a dedicated frontend for more
visual control, given Streamlit's deployment simplicity was the main reason
it was chosen in the first place.

**What Claude did:** Laid out the actual tradeoff rather than jumping to an
answer — Streamlit's widget chrome (selectboxes, sidebar, buttons) can't be
restyled past a ceiling no CSS injection escapes, but a Vite/React app on
Vercel + a FastAPI backend on Render is barely more deployment effort than
Streamlit Community Cloud (two "Deploy" clicks instead of one). Built a
single design mock first (a dark grid-control-room aesthetic, deliberately
not the generic dark-SaaS-dashboard look) to agree the direction before
writing real app code. Once approved, scaffolded the real Vite + React
console (5 pages: Overview, Explorer, Participants, Signals, Binding
Constraints) against the existing FastAPI backend.

**The real bug this surfaced:** building the new frontend meant actually
looking at what the backend serves by default — and it turned out `main.py`
was never calling `ingestion.load_bulk_real_auction_data()`, the same real-
MIS-data function the Streamlit app already used. The FastAPI backend was
serving a different, poorer data path than Streamlit was, silently. The
first version of the new console surfaced this immediately as fabricated-
looking participant names ("Lone Star Power Trading LLC") where Streamlit
showed real ones ("Luminant Energy Company LLC"). Fixed by pointing
`main.py` at the same loader, then discovered a second-order problem: doing
that naively made every endpoint iterate the real dataset's ~95,000 distinct
pairs instead of a sane top-30, so `/api/pairs` and `/api/opportunity-scores`
had to get the same top-30-by-notional restriction Streamlit already applied
via `discover_top_pairs` — otherwise the API would return unusably large
payloads.

**Validation:**
- Backend: 6 of the 93 existing tests had encoded the old synthetic-by-
  default assumption (`data_source == "synthetic_demo"`, `pair_count == 15`)
  and had to be updated to reflect the new, correct real-data-by-default
  reality — not silently left passing on a stale premise. 136 tests total
  after the update, all passing.
- Live: booted both the real FastAPI backend and the real Vite dev server,
  clicked through all 5 pages, and confirmed real participant names, real
  MW figures, and real corridor codes matched what Streamlit showed for the
  same dataset.

**Result:** kept all of it. The bug is the more important story than the
rebuild itself — a second frontend consuming the same backend is exactly
the kind of change that exposes a data path nobody was looking at anymore.

---

## Entry 11 — Trader review, then real iteration (and one deliberate reversal)

**Prompt:** A senior-power-trader-and-senior-engineer review of the new
console against the capstone's own minimum-features list, followed by:
"start with the cache fix and the two Explorer gaps but also the
Participants search and the Texas map interactivity."

**What Claude did:** The review itself surfaced a live bug, not just a
punch list — `/api/weather` and `/api/live/binding-constraints` had zero
caching, and requesting the Binding Constraints page during the review
triggered a real HTTP 429 from ERCOT's own rate-limited live API,
reproducing exactly the failure the review had just flagged as a risk.
Fixed with a small TTL memoizer (1hr weather / 15min constraints, matching
the Streamlit app's existing `st.cache_data` TTLs) that never caches a
failed call, so a transient rate-limit doesn't get stuck. Also shipped, in
the same round: multi-pair compare (up to 3 corridors) and CSV export on
the Explorer, a live search filter on Participants, and — per a later,
detailed visual brief — a Texas map with real curved arcs colored by actual
average-Obligation-price sign, hover-to-isolate, and a search box.

**The reversal:** after using the finished map, the user judged it didn't
actually showcase what they wanted ("only four different places we can
highlight... doesn't look clean") and asked to scrap it entirely. Removed
`TexasMap.jsx`, its CSS, and the now-unused mapping dependencies
(`react-simple-maps`, `d3-geo`, `topojson-client`, `us-atlas`) rather than
leaving dead code around — this also cut the frontend's production bundle
from 810KB to 578KB. Overview's layout closed up around the removal instead
of leaving a gap.

**A real bug caught before the reversal:** while building the map's honest
"N of 30 corridors shown" disclosure (rather than silently hiding
corridors with no known coordinate), the first version miscounted —
flagging "West Hub → West Load Zone" as *not* shown when it actually was
(its hub and load zone share one real-world coordinate, so they render as
one dot, not two, but the pair itself was still represented). Caught by
manually cross-checking the disclosed "hidden" list against what was
visibly on screen, not assumed correct because the code compiled.

**Other fixes in this round, each with its own real verification:**
- Binding Constraints got relative High/Medium/Low severity tiers (an even
  tertile split of the current window's own shadow-price distribution, the
  same relative-ranking logic the opportunity scores already use, not an
  invented fixed dollar threshold) plus an All/High/Medium/Low filter —
  verified live: filtering to High correctly narrowed 9,273 rows to 3,091,
  right at a third.
- Answered a direct question ("are the opportunity signals hardcoded?")
  by pointing at the real, already-tested weighted-factor formula in
  `scoring.py` rather than a vague reassurance — then removed the "not
  enough history" placeholder sentence per request, checked first that no
  test asserted its exact text and that the existing `len(explanation) >=
  3` assertion still held with it gone.

**Validation:** 136 backend tests passing throughout every change in this
round; every frontend change checked live (real backend + real browser),
including several direct DOM/JS checks (`dispatchEvent`) where pixel-based
clicking proved unreliable at small map-marker sizes.

**Result:** kept the cache fix, compare mode, CSV export, Participants
search, and the tier/filter work on Binding Constraints. The map was kept
only long enough to learn it wasn't the right answer, then removed
cleanly — itself a data point for the lessons-learned doc: a working,
tested, bug-fixed feature can still be the wrong feature, and knowing when
to cut it is as much a part of this workflow as building it.

---

## Entry 12 — Root-causing a broken "Previous" button instead of patching it

**Prompt (paraphrased):**
> The Certificates table's Previous button is broken — advancing pages then
> going back either does nothing or shows stale data. Also, selecting a CRR
> type still shows the other type's rows. Find and fix the root cause; do
> not patch this cosmetically. Inspect pagination state, API params, and
> useEffect dependencies before changing anything.

**What Claude did:** Reproduced both bugs before touching code, per the
explicit "do not guess" instruction. Root cause #1: the certificate-fetch
effect special-cased `if (certPage === 1) return;`, on the assumption that
page 1 was always already loaded by a separate "full reload" effect — true
right after a filter change, false after paginating away and pressing
Previous back to page 1, so the table silently kept showing whichever later
page had last been fetched. Root cause #2: the CRR-type toggle only fed the
participant-search combobox, and was never passed to the certificates
endpoint at all — `/api/participants/{name}` didn't even accept a
`crr_type` parameter. Fixed by merging the reload/page-turn effects into
one, computing the effective page synchronously within a single fetch
rather than relying on a second effect's next-render timing (which would
reintroduce the exact same class of stale-page race), and adding real
`crr_type` filtering to the backend, applied before pagination.

**Validation:** New backend tests (`test_participant_detail_crr_type_
filters_strictly`, case-insensitivity, invalid-value 422) plus live browser
verification: Page 1 → Next → Next → Previous → Previous confirmed to
return the exact original page's rows at each step; switching CRR type
while sitting on page 2 confirmed to reset to page 1 with only the selected
type's rows. Caught and fixed a second real bug this same session, found
only through that live verification: the fix's `setDetail(body)` call was
still conditionally gated on "is this the run that detected the filter
change," which left `detail` stuck at `null` forever whenever two effect
runs fired for one logical change (the second one — the one that actually
survives the request-supersession guard — didn't believe itself to be the
"real" filter-change run). Un-gating it fixed a second live repro (switching
CRR type while on page 2 got stuck on "Loading activity…" until this was
found in the browser, not just reasoned about).

**Result:** Kept the unified-effect pattern and reused it for every
subsequent paginated section this session (Path settlement value,
Binding Constraints) specifically because it was independently verified
live, not just because it looked correct on paper.

---

## Entry 13 — Finding a real ERCOT data-quality bug while building pagination

**Prompt (paraphrased):**
> Paginate the Binding Constraints table server-side (it's loading 9,000+
> rows at once) and audit why the constraint search dropdown doesn't
> include every real constraint. Also clean up the column language — explain
> Hour, Constraint, Contingency, Element endpoints, and Shadow price from
> the actual backend/ERCOT fields, don't invent definitions. Fix the info
> tooltips, which don't display. Audit whether the High/Medium/Low labels
> are arbitrary before deciding to keep or remove them.

**What Claude did:** Before touching the UI, called the real live-
credentialed ERCOT endpoint directly to see the raw row shape rather than
guessing. Found the actual root cause behind the confusing "24:006437__F"
value the user had seen: `hourEnding` comes back from ERCOT as a zero-
padded `"24:00"` string — the exact same shape already discovered and
fixed once for the settlement-price endpoint, just never applied to this
one — and every string field (`constraintName`, `contingencyName`,
`fromStation`, `toStation`) carries leading whitespace baked in by ERCOT's
own fixed-width text formatting. Both normalized at the source. Separately
found and fixed why the tooltips didn't render: the table's
`overflow-x: auto` wrapper (needed for horizontal scroll) forces
`overflow-y: auto` too per the CSS spec, silently clipping every upward-
opening tooltip bubble that popped up near the top of that wrapper —
confirmed by measuring the bubble's rect landing entirely above its
scrolling ancestor's own top edge, not assumed from the symptom alone.
Rewrote the tooltip as a React portal to `document.body` so no ancestor's
overflow can ever clip it again. For the severity audit: traced the
High/Medium/Low logic to an even tertile split of the currently-loaded
window's own shadow prices — real, transparent, already-disclosed via its
own tooltip, but not an ERCOT-defined threshold.

**Validation:** New pagination/filter/sort backend tests plus a live
browser check that page 3 → Previous → Previous returns the exact original
page 1 rows; the constraint dropdown confirmed to carry all 402 distinct
real constraint names in the window (not just the 25 on the loaded page)
via a direct API check; the tooltip fix confirmed by measuring the portal-
rendered bubble's rect against the viewport for both an edge-clipped
(leftmost) and previously-invisible (rightmost) column.

**Result:** Kept the severity classification (with its methodology
disclosed) in this round, since it was defensible; a later, explicit
follow-up request removed it entirely in favor of the raw shadow price —
see Entry 14.

---

## Entry 14 — Final demo pass: a deliberate reversal, an honest cleanup audit, and knowing what not to delete

**Prompt (paraphrased):**
> Prepare this app for a live demo to power traders: improve page copy so
> the app's story is self-explanatory, remove the High/Medium/Low
> constraint labels entirely (the real shadow price is enough), but this
> time keep Hour and Constraint combined in one field/column instead of
> split — reverse that earlier decision. Then, only after the app is
> correct, audit the repo for dead code and stale docs and clean it up,
> but do not delete anything without checking references, tests, and
> runtime use first.

**What Claude did:** Reversed the Entry 13 column split on explicit
instruction — recombined Hour and Constraint into one "HourEnding :
Constraint" column, but rendered it as `24 : 6437__F` (a readable
separator) rather than literally reproducing the original unseparated
"24:006437__F" string the request's own example quoted, since every other
instruction in the same request explicitly asked for "clean," "professional,"
"demo-ready" copy — flagged this specific interpretation call back to the
user rather than silently picking one reading. Removed the severity tiers
end to end (backend thresholds/filter/response field, frontend badges/
filter/tooltip, the now-dead `.tier-chip` CSS) with no replacement score
invented. For the cleanup audit: checked every backend module's real
import graph (all genuinely referenced, nothing orphaned), grepped the
frontend for any `synthetic`/`demo`/`fake` language reaching the UI (found
none — the one match was an honest, intentional disclosure message, not a
leak), and specifically verified live that the running app's actual active
data source was real ERCOT data (`data_source: "ercot_mis_real"`, zero
warning) before writing that into the audit report as a confirmed fact
rather than an assumption. Found one genuinely dead field
(`/api/dashboard`'s `tier_distribution`/`top_opportunity_pairs`, a
Streamlit-era chart the React rebuild never rendered) and removed it —
but explicitly did NOT remove `weather_zones.py`/`/api/corridor-map`/
`/api/weather`, which have no current frontend consumer either, because
`weather_zones.py` is a shared module (corridor-map's zone data) and
deleting a whole working, tested feature under uncertainty is a much
bigger and more permanent call than trimming two confirmed-dead response
fields — flagged for a deliberate future decision instead of acted on
unilaterally.

**Validation:** 192 backend tests passing (down from 194: one dedicated
severity test removed, two dashboard tests merged to reflect the removed
fields, net new pagination/normalization tests added), `vite build` clean,
and a full live walkthrough of all 5 pages after a stale long-running dev
server session briefly appeared to hang on Overview — traced to the dev
server itself (a fresh restart fixed it immediately, and the underlying
production `vite build` had been clean the entire time), not a code
regression, before reporting it as such.

**Result:** Kept the reversal, the removed severity tiers, and the one
confirmed-dead-field cleanup; explicitly left the weather/corridor-map
question open rather than guessing at the "right" answer under time
pressure — itself a data point for the lessons-learned doc: knowing when
*not* to delete something is as much a judgment call as knowing when to.

---

## Entry 15 (template for your own use)

**Prompt:** *(fill in what you asked Claude for)*

**What Claude did:** *(what changed in the code)*

**Validation:** *(what test you ran, or what you clicked through, to
confirm it actually worked — this is the part graders will want to see)*

**Result:** *(keep, revert, or iterate again)*

---

## Lessons on prompting that came out of this build

1. **Ask Claude to verify data availability before designing around it.**
   "Does ERCOT publish X publicly, and can you actually fetch it from here?"
   is a better first prompt than "build me a dashboard with ERCOT data" —
   it surfaces architecture-changing constraints early instead of late.
2. **When you ask for "explainable," say what you're rejecting, not just
   what you want.** "Explainable, not a black box, not predictive" got a
   materially different (and better-suited) design than "explainable" alone
   would have.
3. **Ask for the test before you ask to see the feature.** Requesting "write
   a test that would fail if this were wrong" before or alongside a feature
   request catches silent regressions that a demo click-through would miss
   (e.g., the strong-pair-vs-weak-pair ranking test would have caught a
   scoring engine that looked plausible but weighted factors backwards).
4. **When a second frontend appears, ask it to prove it agrees with the
   first one — don't assume they share a backend just because they're
   supposed to.** Building the React console against the same FastAPI
   backend Streamlit already used is what surfaced Entry 10's real bug:
   the two had quietly been serving different data all along. A single-
   frontend project would never have caught that.
5. **A finished, tested, working feature is not automatically a kept
   feature.** The Texas map in Entry 11 was real, interactive, and bug-
   fixed — and still got scrapped once it was used and judged not to serve
   the trader. Build it, use it, then ask "does this actually work for the
   job," not just "does this work."
