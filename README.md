# ERCOT CRR Market Analytics — Prototype

A market-intelligence prototype for ERCOT Congestion Revenue Rights (CRR)
markets: participant analysis, Source/Sink pricing history, descriptive
analytics, and an explainable Low/Medium/High opportunity signal.

> **This is analytics tooling, not trading advice.** The opportunity score
> is a transparent composite of historical descriptive statistics — never a
> price prediction or a bidding recommendation.

> **Sign-off:** this build has been reviewed from three angles — Senior
> Software Engineer, Senior Power Trader, and Head of Frontend — against
> the project's own minimum-features criteria. See
> `docs/triple_check_review.md` for the full pass/gap breakdown.

## What's in this repo

```
ercot-crr-analytics/
├── backend/                  Python/FastAPI service — the real logic
│   ├── app/
│   │   ├── domain.py          ERCOT hub/load-zone/node reference data
│   │   ├── data_generator.py  Seeded synthetic CRR auction data generator (fallback only)
│   │   ├── db.py              SQL Server connection layer (env-var configured, see below)
│   │   ├── ingestion.py       Loader: real bundled ERCOT MIS data by default, else SQL
│   │   │                      Server, else dropped CSVs, else synthetic fallback
│   │   ├── analytics.py       Pure functions: avg/min/max/volatility/trend/downside-risk
│   │   ├── scoring.py         Explainable Low/Medium/High opportunity score
│   │   ├── ercot_live.py      Real ERCOT Public API client (live DAM prices, free to register)
│   │   ├── live_congestion.py Turns live DAM prices into real Source/Sink congestion value
│   │   └── main.py            FastAPI routes
│   ├── tests/                 136 pytest tests covering all of the above
│   ├── scripts/
│   │   ├── export_snapshot.py           Regenerates data/snapshot.json (feeds the presentation deck)
│   │   ├── fetch_real_ercot_data.py     Refreshes the bundled real MIS data described below
│   │   └── create_sql_server_schema.sql T-SQL to create the expected SQL Server table
│   ├── .env.example            Copy to .env -- every environment variable this backend reads
│   ├── requirements.txt
│   └── pytest.ini
├── frontend/                 Vite + React console — the primary, deployable UI
│   ├── src/
│   │   ├── App.jsx             Nav rail + routes
│   │   ├── api.js              Fetch client against the FastAPI backend
│   │   ├── styles.css          The console's design system (dark, hairline-bordered)
│   │   └── pages/               Overview, Explorer, Participants, Signals, BindingConstraints
│   ├── .env.example            Copy to .env.local -- points the console at a running backend
│   └── package.json
├── data/
│   ├── snapshot.json          Static export of the real tracked dataset (feeds the deck's charts)
│   ├── raw/crr_auction/       Bundled real ERCOT CRR Monthly Auction Results (see below)
│   └── reference/participants.csv   Bundled real ERCOT Market Participants List
├── docs/
│   ├── requirements.md                    Full requirements doc (functional + non-functional)
│   ├── prompt_journal.md                  AI prompt evolution & validation log, 12 entries
│   ├── triple_check_review.md             Multi-round persona sign-off log
│   ├── copilot_sql_connection_prompt.md   Ready-to-paste prompt for connecting a real SQL Server
│   ├── lessons_learned_and_future_work.md
│   └── superpowers/                       Dated design specs/plans from earlier build rounds
└── presentation/
    ├── ERCOT_CRR_Capstone_Presentation.pptx   60-minute presentation deck
    └── build/                                  Node scripts that generate the deck above --
                                                  `node make_icons.js && node build_deck.js`
                                                  (run from presentation/build/, needs
                                                  `npm install pptxgenjs sharp react react-dom react-icons`)
```

## Quick start — backend

```bash
cd backend
pip install -r requirements.txt
python -m pytest -q          # 136 tests, all passing
uvicorn app.main:app --reload --port 8000
# then browse http://localhost:8000/docs for interactive Swagger UI
```

No environment variables are required for this to work with real data —
the backend reads the bundled real ERCOT auction data described below by
default. Key endpoints: `GET /api/dashboard`, `/api/pairs`,
`/api/pairs/{source}/{sink}/series` (accepts `crr_type`/`time_of_use`
filters and `?format=csv`), `/api/pairs/{source}/{sink}/participants`,
`/api/participants`, `/api/participants/{name}`, `/api/opportunity-scores`,
`/api/hot-paths`, `/api/corridor-map`, `/api/weather`, `/api/meta`,
`/health` — plus the live-data endpoints described further down.

## Quick start — the console (frontend)

```bash
cd frontend
npm install
cp .env.example .env.local     # points VITE_API_BASE_URL at your backend
npm run dev                    # http://localhost:5173, with the backend running on :8000
```

Five pages, all reading real data from the backend above:

- **Overview** — latest auction month, MW awarded (with a prior-month
  delta), active participants, tracked corridors, hot paths, opportunity
  tier distribution, top participants by notional, and a live weather panel
  for the regions behind the tracked corridors (see "Live weather context"
  below).
- **Source/Sink Explorer** — pick a tracked corridor (or compare up to 3 at
  once), Peak-Weekday/Peak-Weekend/Off-Peak/All filtering, Obligation vs.
  Option overlay, the participants active on that pair, and CSV export of
  whatever's charted.
- **Participants** — a searchable, scrollable list of every real CRR
  Account Holder active on a tracked corridor, with a detail pane (net MW,
  notional, distinct corridors, certificates, recent activity) that updates
  in place as you click through the list.
- **Opportunity Signals** — every tracked corridor's Low/Medium/High score,
  filterable by tier and searchable by hub/zone name, each with its four
  factor sub-scores and a plain-language explanation.
- **Binding Constraints** — real, live ERCOT transmission constraints for a
  trailing 7/14/30-day window, with a "most active constraints" ranking,
  relative High/Medium/Low severity tiers, and search/sort/filter on the
  full table — a separate, real-time clock from the settled auction data
  shown elsewhere, never merged with it.

The console always talks to a real backend over `fetch` (`VITE_API_BASE_URL`
in `.env.local`) — there's no embedded-snapshot/offline mode. To build it
for deployment: `npm run build` (outputs `frontend/dist/`), deployable to
any static host (Vercel, Netlify, GitHub Pages, ...) as long as it can reach
a running instance of the backend above.

## Real ERCOT CRR auction data (bundled, no download required)

This repo ships with 13 months of real ERCOT CRR Monthly Auction Results
(`data/raw/crr_auction/`, 1,120,889 records spanning Oct 2025 – Oct 2026)
and the real ERCOT Market Participants List (`data/reference/participants.csv`,
521 unique companies, 377 appearing in the bundled auction data), fetched
directly from ERCOT's public, unauthenticated legacy MIS servlet endpoints
-- no browser session, no login, no MIS account required. This corrects an
earlier assumption in this project (see `docs/lessons_learned_and_future_work.md`
and `docs/prompt_journal.md` Entry 9) that this data could only be reached
through the modern, JS-gated `mis.ercot.com` file browser.

**Both the backend and the console read this bundled data by default** —
`ingestion.load_bulk_real_auction_data()` is the single entry point both
`main.py` and `data/snapshot.json`'s export script use, so there's one real
dataset behind everything in this repo, not two that could quietly drift
apart (see `docs/prompt_journal.md` Entry 10 for the bug this exact
divergence caused, and how it was caught). To refresh the bundled data
after a new monthly auction posts:

```bash
cd backend
python scripts/fetch_real_ercot_data.py
```

This is idempotent -- it only downloads auction months not already present
locally, and always refreshes the participant registry (a small file,
updated daily by ERCOT).

Every pair-level view (the Explorer's corridor list, Opportunity Signals,
Participants) works off the top 30 corridors by real notional activity, not
the full ~95,000 distinct pairs in the raw data — see
`analytics.discover_top_pairs`. `/api/meta` and `/api/system/status` expose
the full raw counts if you need them.

## Using your own ERCOT CRR auction data files (optional)

If you have your own real ERCOT CRR Auction Results CSVs from
`ercot.com/mp/data-products` (e.g., **NP7-802-M** for Long-Term or
**NP7-803-M** for Monthly Auction Results — including Source, Sink, CRR
type, clearing price, and CRR Account Holder): drop them into `data/raw/`
directly (not `data/raw/crr_auction/`, which is reserved for the bundled
real data described above). This is a separate, lower-priority tier used
only by `ingestion.load_records()` (SQL Server, then this flat-CSV tier,
then synthetic) — see that module's docstring for exactly how the two
loaders relate.

## Live ERCOT data (real, free, API-based)

Beyond the bundled CRR auction data above, this project also integrates
**ERCOT's real Public Data API** (`api.ercot.com`) — a genuine, separate,
free-to-register REST API for live market data, distinct from the
JS-gated MIS file browser and the legacy servlet that supplies the bundled
data. It does not expose CRR auction awards, but it does expose real, live
Day-Ahead Market settlement point prices and the binding transmission
constraints behind them, and this project uses both — the latter powers
the console's Binding Constraints page.

**Why this is legitimate CRR-relevant data, not a workaround:** a
Point-To-Point (PTP) Obligation CRR pays its holder exactly
`Sink DAM price − Source DAM price` per MWh, per hour — that's ERCOT's own
settlement formula. So the live price spread between two real settlement
points *is* real, realized Obligation-CRR value, computed straight from
the same live feed ERCOT itself publishes — available same-day rather than
waiting for the next monthly auction, and reflecting what actually
happened on the grid rather than what a bidder guessed weeks earlier.

### Enabling it (free, ~5 minutes)

1. Register at **https://apiexplorer.ercot.com/**
2. Subscribe to **"Public API"** on that portal to get a subscription key
3. Set three environment variables before starting the backend:
   ```bash
   export ERCOT_API_USERNAME="the email you registered with"
   export ERCOT_API_PASSWORD="your apiexplorer.ercot.com password"
   export ERCOT_API_SUBSCRIPTION_KEY="the subscription key from step 2"
   ```
   (or put them in `backend/.env` — see `backend/.env.example`; that file
   is gitignored, so your real credentials never get committed)
4. `GET /api/live/status` confirms it's configured; the endpoints below then
   pull real, live data on every call.

### What it adds

| Endpoint | What it returns |
|---|---|
| `GET /api/live/status` | Whether live credentials are configured on this server |
| `GET /api/pairs/{source}/{sink}/live-lmp-spread?months_back=24` | Real DAM price spread for that pair, fetched and aggregated just now, run through the exact same tested `analytics.py` metrics as everything else |
| `GET /api/live/binding-constraints?date_from=...&date_to=...` | The actual named transmission constraint(s) driving congestion in that window, straight from ERCOT's shadow-price data — real "why," not a statistical guess. Cached 15 minutes and paginated up to 15,000 rows; powers the console's Binding Constraints page. |

Live data is only available for real ERCOT hub/load-zone codes — the
project's small set of illustrative synthetic resource-node pairs
(`PANHANDLE_WIND_RN`, etc., clearly labeled as such in `domain.py`) don't
resolve against ERCOT's live systems and are rejected with a clear 422 if
requested.

**Known limitation, disclosed upstream by ERCOT itself and by third-party
clients:** this API is an explicit work-in-progress and has documented
intermittent reliability issues (timeouts/429s/500s under load — see
[ercot/api-specs discussion #124](https://github.com/ercot/api-specs/discussions/124),
and this project's own `docs/prompt_journal.md` Entry 11 for a real 429
hit and fixed during review). `ercot_live.py` retries with backoff and
surfaces a clear, actionable error rather than hanging or failing
silently; see its module docstring for specifics.

**What was and wasn't validated from this project's original build
environment:** that environment's own network egress was allowlisted to a
fixed set of package-registry domains and did not include `api.ercot.com`,
so a real end-to-end login could not be performed from inside it at the
time. What *was* verified there: the real FastAPI server boots and its
`/api/live/status`, 501 ("not configured"), and 422 ("ineligible pair")
paths behave correctly; and, with placeholder credentials, the client made
a genuine HTTPS request to ERCOT's real token URL and degraded cleanly (a
`502`, not a crash). All request/response parsing logic is covered by unit
tests mocked against ERCOT's documented and forum-confirmed response
shapes. In later sessions, real authenticated calls were made successfully
against the live API from a different environment — see
`docs/prompt_journal.md` for details.

## Live weather context (genuinely live, verified honestly)

The console's Overview page includes a weather panel for the real-world
regions behind the tracked corridors, fetched server-side from
**Open-Meteo** (`api.open-meteo.com`) via `GET /api/weather` — no API key,
no signup. Cached an hour on the backend (matches the cadence weather
actually changes at, and avoids hitting Open-Meteo on every page load).

**Why weather, and why here:** wind output at West Texas/Panhandle and
temperature-driven AC load at Houston/DFW are the actual physical drivers
of the congestion this app's Source/Sink pairs measure — not a random
enrichment. The panel is explicitly framed as context, not a forecast of
CRR value or an input to the opportunity score.

**What was and wasn't verified:** the panel fails open — either real data
or a visible, honest error message per zone, never a blank box. Confirmed
live: the backend fetches real current temperatures/wind speeds from
Open-Meteo and the console renders them correctly.

## Connecting to a real SQL Server database (the production data path)

The backend can read the full auction/participant dataset directly from a
real SQL Server database instead of the bundled real data or the synthetic
fallback — useful if your organization already loads ERCOT data into a
warehouse. **The database does not need to be on the same machine as the
backend** — this is built entirely around environment variables, so the
backend can run on one machine and point at a SQL Server on another.

### Setup (do this in this order)

1. **Create the table.** Run `backend/scripts/create_sql_server_schema.sql`
   against your target database. If you already have CRR data in a
   differently-shaped table, create a SQL `VIEW` named `crr_auction_records`
   with the same column names/types instead of migrating your real table —
   the backend only ever runs a plain `SELECT * FROM crr_auction_records`.
2. **Load real data into it** (or point the view at wherever it already
   lives), matching the column meanings documented in the schema script and
   in `backend/app/db.py`'s module docstring.
3. **Configure the connection.** Copy `backend/.env.example` to
   `backend/.env` and fill in either `DATABASE_URL` (one connection string)
   or the separate `SQL_SERVER_HOST`/`SQL_SERVER_DATABASE`/credentials
   variables — full details and both auth modes (SQL auth and Windows
   trusted-connection) are documented in that file and in `db.py`.
4. **Install the system-level ODBC driver** on the machine running the
   backend — this is separate from `pip install`, an OS-level component:
   - Windows: usually already present; otherwise install "ODBC Driver 18
     for SQL Server" from Microsoft.
   - macOS: `brew tap microsoft/mssql-release && brew install msodbcsql18`
   - Linux: see Microsoft's "Install the Microsoft ODBC driver for SQL
     Server on Linux" docs for your distribution.
5. **Start the backend** (`uvicorn app.main:app --port 8000`) and verify:
   ```bash
   curl http://localhost:8000/api/system/status
   ```
   Look for `"active_data_source": "sql_server_real"` and
   `"sql_configured": true`. If `data_source_warning` is non-null, the SQL
   connection was attempted and failed — the message explains exactly why
   (unreachable host, missing table, bad credentials, missing ODBC driver,
   etc.) and the backend automatically fell back to CSV files or the
   synthetic demo rather than crashing.

Note: `main.py`'s primary data path is `ingestion.load_bulk_real_auction_data()`
(the bundled real MIS data described above), which is tried before this
SQL tier only falls back to it. If you want SQL Server to take priority
over the bundled real data for the console/API, point `ingestion.load_records()`
at it directly (see that module's docstring) or remove/relocate
`data/raw/crr_auction/`.

### Why this degrades safely instead of breaking the app

A misconfigured or temporarily-unreachable SQL Server never takes the
whole backend down — each tier only used if the one before it isn't
configured or fails, and a failure is always reported (via
`data_source_warning` on `/api/meta`, `/api/dashboard`, and
`/api/system/status`) rather than silently substituting different data and
looking fine. An unreachable host also fails in a few seconds, not the
60+-second OS default, via `SQL_SERVER_CONNECT_TIMEOUT_SECONDS`.

## Why synthetic data exists, and how it was built responsibly

Synthetic data is now strictly a fallback — real bundled data is the
default, described above — but it's still there for a reason: the app
should never fully break just because `data/raw/crr_auction/` is missing
or the real registry can't be parsed.

- Every synthetic record is real-hub-named (`HB_NORTH`, `HB_WEST`,
  `HB_HOUSTON`, `LZ_AEN`, ...) but `is_synthetic: true`-tagged, and the API
  surfaces which tier is actually serving data (`data_source` on
  `/api/meta`/`/api/dashboard`/`/api/system/status`) — this project never
  presents synthetic numbers as if they were ERCOT's real historical
  settlements.
- **Participant names are fictional — but only in this synthetic fallback
  path.** "Lone Star Power Trading LLC," "Permian Basin Energy Partners,"
  and the dozen or so others in `data_generator.py` are made-up
  placeholder company names, not real ERCOT market participants.
- The price process is a **seeded, fully deterministic** random walk
  (`SEED` in `data_generator.py`) with pair-specific base congestion
  levels, summer/winter seasonal premiums, and a few illustrative
  stress-event multipliers — calibrated for *shape* (the kind of
  seasonality and locational spread real ERCOT congestion shows), not as a
  claim of historical accuracy for any specific month.
- See `docs/requirements.md` §6 for the full data-sourcing disclosure and
  `docs/prompt_journal.md` Entries 1 and 9 for how this was verified
  before, and re-verified after, being designed around.

## Running the analytics/scoring logic outside the API

Because `analytics.py` and `scoring.py` are pure functions over plain
dicts, you can use them directly in a notebook:

```python
from app.ingestion import load_bulk_real_auction_data
from app import analytics, scoring

records, source, warning = load_bulk_real_auction_data()
top_pairs = analytics.discover_top_pairs(records, n=30)
tracked_keys = {(p["source"], p["sink"]) for p in top_pairs}
tracked_records = [r for r in records if (r["source"], r["sink"]) in tracked_keys]
scores = scoring.score_all_pairs(tracked_records)
top5 = sorted(scores, key=lambda s: s.score, reverse=True)[:5]
```

## Presentation

`presentation/ERCOT_CRR_Capstone_Presentation.pptx` is a ready-to-edit
60-minute deck covering ERCOT CRR fundamentals, the AI-assisted build
workflow (including the real data-access course-correction and the
FastAPI/Streamlit data-divergence bug described in the prompt journal), a
live-demo script for the console's 5 pages, testing/validation proof, and
lessons learned / future enhancements (also written out in full in
`docs/lessons_learned_and_future_work.md`).

It's generated from `presentation/build/build_deck.js` rather than edited
directly, so its charts stay tied to the app's own real output
(`data/snapshot.json`) instead of hand-typed numbers. To regenerate after
any change:

```bash
cd presentation/build
npm install pptxgenjs sharp react react-dom react-icons   # first time only
node make_icons.js     # first time only, or if you change the icon set
cd ../../backend && python scripts/export_snapshot.py     # refresh the real data behind the charts
cd ../presentation/build && node build_deck.js
```
