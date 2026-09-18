# ERCOT CRR Market Analytics — Prototype

A market-intelligence prototype for ERCOT Congestion Revenue Rights (CRR)
markets: participant analysis, Source/Sink pricing history, descriptive
analytics, and an explainable Low/Medium/High opportunity signal.

> **This is analytics tooling, not trading advice.** The opportunity score
> is a transparent composite of historical descriptive statistics — never a
> price prediction or a bidding recommendation.

> **Sign-off:** this build has been reviewed from three angles — Head of
> Software Engineering, Senior Power Trader, and Head of Frontend — against
> the project's own minimum-features criteria. See
> `docs/triple_check_review.md` for the full pass/gap breakdown.

## What's in this repo

```
ercot-crr-analytics/
├── backend/                  Python/FastAPI service — the real logic
│   ├── app/
│   │   ├── domain.py          ERCOT hub/load-zone/node reference data
│   │   ├── data_generator.py  Seeded synthetic CRR auction data generator
│   │   ├── db.py              SQL Server connection layer (env-var configured, see below)
│   │   ├── ingestion.py       Loader: SQL Server, else real ERCOT CSVs, else synthetic fallback
│   │   ├── analytics.py       Pure functions: avg/min/max/volatility/trend/downside-risk
│   │   ├── scoring.py         Explainable Low/Medium/High opportunity score
│   │   ├── ercot_live.py      Real ERCOT Public API client (live DAM prices, free to register)
│   │   ├── live_congestion.py Turns live DAM prices into real Source/Sink congestion value
│   │   └── main.py            FastAPI routes
│   ├── tests/                 93 pytest tests covering all of the above
│   ├── scripts/
│   │   ├── export_snapshot.py           Regenerates data/snapshot.json (run after any analytics change)
│   │   └── create_sql_server_schema.sql T-SQL to create the expected SQL Server table
│   ├── .env.example            Copy to .env -- every environment variable this backend reads
│   ├── requirements.txt
│   └── pytest.ini
├── frontend/
│   └── src/
│       ├── component_body.jsx      React UI — connects to a live backend when available,
│       │                           falls back to the embedded snapshot otherwise
│       └── ErcotCrrDashboard.jsx   component_body.jsx + an embedded data snapshot,
│                                   ready to run standalone (this is the file
│                                   shared as the in-chat interactive artifact)
├── data/
│   ├── snapshot.json          JSON export of the synthetic dataset (for the demo UI)
│   └── raw/                   Drop real ERCOT MIS CRR Auction Result CSVs here
├── docs/
│   ├── requirements.md                    Full requirements doc (functional + non-functional), v1.3
│   ├── prompt_journal.md                  AI prompt evolution & validation log, 8 entries
│   ├── triple_check_review.md             Head of SWE / Senior Trader / Head of Frontend sign-off
│   ├── copilot_sql_connection_prompt.md   Ready-to-paste prompt for connecting a real SQL Server
│   └── lessons_learned_and_future_work.md
└── presentation/
    └── ERCOT_CRR_Capstone_Presentation.pptx   60-minute presentation outline/deck (v1.1 feature set --
                                                not yet updated for v1.3, see lessons-learned)
```

## Quick start — backend + tests

```bash
cd backend
pip install -r requirements.txt
python -m pytest -q          # 93 tests, all passing
uvicorn app.main:app --reload --port 8000
# then browse http://localhost:8000/docs for interactive Swagger UI
```

Key endpoints: `GET /api/dashboard`, `/api/pairs`,
`/api/pairs/{source}/{sink}/series` (accepts `crr_type`/`time_of_use`
filters and `?format=csv`), `/api/pairs/{source}/{sink}/participants`,
`/api/participants`, `/api/participants/{name}`, `/api/opportunity-scores`,
`/api/meta`, `/health` — plus the live-data endpoints below.

## Quick look — the UI

`frontend/src/ErcotCrrDashboard.jsx` is a self-contained React component
(Recharts + Lucide icons) that **talks to a real backend when one is
reachable, and falls back to an embedded demo snapshot when it isn't** —
it's not just a static mockup. Four views: **Overview** (recent-auction
summary, opportunity-tier distribution across *all* tracked pairs, a
trailing-12-month market MW trend, and a live weather panel for the
regions behind the tracked corridors — see "Live weather context" below),
**Source/Sink Explorer** (Peak-Weekday/Peak-Weekend/Off-Peak/All filter,
Obligation vs. Option, up to 3-pair overlay comparison, a trailing-12-month
average alongside the all-time average, a seasonality strip by calendar
month, the list of participants active on that specific pair, and one-click
CSV download), **Participants** (activity + notional ranking), and
**Opportunity Signals** (every pair's score with its factor breakdown,
filterable by tier and searchable by hub/zone name).

**Connecting it to a real backend:** at the top of the app is a connection
bar. Run the backend (`uvicorn app.main:app --port 8000`), type its URL
(default `http://localhost:8000`) into the connection bar, and click
Connect — the whole UI switches to live data with no code changes, because
every view is written against one `provider` interface
(`demoProvider`/`liveProvider` in `component_body.jsx`) rather than reading
the embedded snapshot directly. Disconnect returns to the demo dataset.
**Note:** browser sandboxing inside Claude's chat preview may block this
connection even though the code is correct and tested against a real
running server (see "What was and wasn't validated" below) — it will work
when this file is run as a normal web app (see "Running as a standalone
app" below).

### Running as a standalone app

This is plain React + Recharts + Lucide with no build-tool-specific syntax,
so it drops into any React setup:

```bash
npm create vite@latest ercot-crr-ui -- --template react
cd ercot-crr-ui
npm install recharts lucide-react
# replace src/App.jsx with frontend/src/ErcotCrrDashboard.jsx's contents
npm run dev
```

Regenerate `data/snapshot.json` after any backend analytics change with
`cd backend && python scripts/export_snapshot.py`, then re-paste the new
`const DATA = {...}` block at the top of `ErcotCrrDashboard.jsx` (or just
keep `component_body.jsx` and `data/snapshot.json` separate if you're
running this as a real app rather than a single-file artifact).

## Live ERCOT data (real, free, no CSV download required)

Beyond the CRR auction CSV path above, this project also integrates
**ERCOT's real Public Data API** (`api.ercot.com`) — a genuine, separate,
free-to-register REST API for live market data, distinct from the
JS-gated MIS file browser the CRR auction results live behind. It does not
expose CRR auction awards, but it does expose real, live Day-Ahead Market
settlement point prices and the binding transmission constraints behind
them, and this project uses both.

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
4. `GET /api/live/status` confirms it's configured; the endpoints below then
   pull real, live data on every call.

### What it adds

| Endpoint | What it returns |
|---|---|
| `GET /api/live/status` | Whether live credentials are configured on this server |
| `GET /api/pairs/{source}/{sink}/live-lmp-spread?months_back=24` | Real DAM price spread for that pair, fetched and aggregated just now, run through the exact same tested `analytics.py` metrics as everything else |
| `GET /api/live/binding-constraints?date_from=...&date_to=...` | The actual named transmission constraint(s) driving congestion in that window, straight from ERCOT's shadow-price data — real "why," not a statistical guess |

Live data is only available for real ERCOT hub/load-zone codes (the same
ones this project already uses for the demo, e.g. `HB_WEST`, `HB_HOUSTON`,
`LZ_AEN`) — the project's small set of illustrative synthetic resource-node
pairs (`PANHANDLE_WIND_RN`, etc., clearly labeled as such in `domain.py`)
don't resolve against ERCOT's live systems and are rejected with a clear
422 if requested.

**Known limitation, disclosed upstream by ERCOT itself and by third-party
clients:** this API is an explicit work-in-progress and has documented
intermittent reliability issues (timeouts/500s under load — see
[ercot/api-specs discussion #124](https://github.com/ercot/api-specs/discussions/124)).
`ercot_live.py` retries with backoff and surfaces a clear, actionable error
rather than hanging or failing silently; see its module docstring for
specifics.

**What was and wasn't validated from this project's build environment:**
that environment's own network egress is allowlisted to a fixed set of
package-registry domains and does not include `api.ercot.com` or
`ercotb2c.b2clogin.com`, so a real end-to-end login could not be performed
there. What *was* verified: the real FastAPI server boots and its
`/api/live/status`, 501 ("not configured"), and 422 ("ineligible pair")
paths behave correctly; and, with placeholder credentials, the client was
confirmed to make a genuine HTTPS request to ERCOT's real token URL and
degrade cleanly (a `502` to the API caller, not a crash or a hang) when
that request is rejected. All request/response parsing logic is covered by
27 unit tests mocked against ERCOT's documented and forum-confirmed
response shapes. **A genuine live pull with real credentials has not been
performed and should be your first check after registering.**

**Why the ERCOT-specific live endpoints (LMP spread, binding constraints)
aren't exposed directly in the UI:** they require the three
`ERCOT_API_*` environment variables above, on top of the base backend
connection described in "Quick look — the UI." The UI's connection bar
does let you point the whole app at a real running backend — that part
works today — but wiring the ERCOT-specific endpoints into the Explorer as
an additional overlay is still open (see `docs/requirements.md` and
`lessons_learned_and_future_work.md`). Either way, this backend capability
is real and fully tested (27 tests across `ercot_live.py`/
`live_congestion.py` plus the endpoint tests in `test_api.py`) and callable
today via `uvicorn` + the three environment variables — see its Swagger UI
at `/docs`.

## Live weather context (genuinely live, verified honestly)

The Overview tab includes a weather panel for the four real-world regions
behind the tracked corridors (West Texas/Permian, Texas Panhandle, Houston/
Gulf Coast, North Texas/DFW), fetched from **Open-Meteo**
(`api.open-meteo.com`) directly in the browser on every load — no API key,
no signup, `Access-Control-Allow-Origin: *`.

**Why weather, and why here:** wind output at West Texas/Panhandle and
temperature-driven AC load at Houston/DFW are the actual physical drivers
of the congestion this app's Source/Sink pairs measure — not a random
enrichment. The panel is explicitly framed as context, not a forecast of
CRR value or an input to the opportunity score.

**Why Open-Meteo specifically, and how that was checked before building
anything:** unlike ERCOT's OAuth-based Public API, Open-Meteo is a plain
`GET` request with no auth headers and an open CORS policy — confirmed via
a working browser `fetch()` code sample in search results before writing
any integration code, precisely because that combination (no key, no
custom headers, wildcard CORS) is the profile most likely to survive a
strict browser sandbox's content-security policy.

**What was and wasn't verified:** the panel fails open — loading, then
either real data or a visible, honest error message, never a blank box.
Tested directly (not assumed) whether this project's own build sandbox
could reach Open-Meteo: it could not (`Host not in allowlist:
api.open-meteo.com` — the same category of restriction that affects the
ERCOT domain, see above). That means the live weather fetch has **not**
been confirmed working end-to-end from this specific environment. It is
expected to work when this app runs as a normal deployed page (a different
runtime with a different, and typically much less restrictive, network
policy than this build sandbox's own tool access) — but that expectation
is stated as an expectation, not a verified fact.

## Connecting to a real SQL Server database (the production data path)

The backend can read the full auction/participant dataset (Dashboard,
Participants, Opportunity Signals) directly from a real SQL Server
database instead of the synthetic demo or CSV files — this is the
intended way to run this against real ERCOT data once you have it loaded
somewhere. **The database does not need to be on the same machine as the
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

### Why this degrades safely instead of breaking the app

A misconfigured or temporarily-unreachable SQL Server never takes the
whole backend down. `ingestion.load_records()` tries SQL first, then real
CSV files in `data/raw/`, then the synthetic generator — each tier only
used if the one before it isn't configured or fails, and a failure is
always reported (via `data_source_warning` on `/api/meta`,
`/api/dashboard`, and `/api/system/status`, and surfaced as a visible
banner in the UI) rather than silently substituting different data and
looking fine. An unreachable host also fails in a few seconds, not the
60+-second OS default, via `SQL_SERVER_CONNECT_TIMEOUT_SECONDS`.

## Using real ERCOT CRR auction data via CSV (no database available)

If you don't have a SQL Server set up (previous section) but do have
access to real ERCOT files, this is the lighter-weight option — it's the
second-priority data source, used only if SQL Server isn't configured.

ERCOT publishes real historical CRR Auction Results at
`ercot.com/mp/data-products` — **NP7-802-M** (Long-Term Auction Results)
and **NP7-803-M** (Monthly Auction Results) — including Source, Sink, CRR
type, clearing price, and CRR Account Holder (participant), free to the
public via MIS. That download center requires a browser session and isn't
scriptable from this offline build environment, so this prototype ships
with a synthetic-but-realistic fallback (see "Why synthetic data?" below).

To use real data: log into `mis.ercot.com`, download the CRR Auction
Results CSV(s) you want, and drop them into `data/raw/`. On next backend
start, `ingestion.py` will detect them (column-matched case-insensitively
against ERCOT's published header names) and use them automatically instead
of the synthetic generator — no code changes required. The analytics and
scoring modules are 100% agnostic to where the records came from.

## Why synthetic data, and how it was built responsibly

- Every synthetic record is real-hub-named (`HB_NORTH`, `HB_WEST`,
  `HB_HOUSTON`, `LZ_AEN`, ...) but `is_synthetic: true`-tagged, and the UI
  shows a persistent banner saying so — this project never presents
  synthetic numbers as if they were ERCOT's real historical settlements.
- **Participant names are fictional.** "Lone Star Power Trading LLC,"
  "Permian Basin Energy Partners," and the dozen or so others in
  `data_generator.py` are made-up placeholder company names, not real
  ERCOT market participants. There is no way to get real CRR Account
  Holder data short of a real database load (see "Connecting to a real SQL
  Server database" above) or real CSVs from `mis.ercot.com` — ERCOT's live
  Public API has no participant-level endpoint at all (see "Live ERCOT
  data" above). Once SQL or CSVs are connected, real participant names
  flow through automatically with zero code changes.
- The price process is a **seeded, fully deterministic** random walk
  (`SEED` in `data_generator.py`) with pair-specific base congestion
  levels, summer/winter seasonal premiums, and a few illustrative
  stress-event multipliers — calibrated for *shape* (the kind of
  seasonality and locational spread real ERCOT congestion shows), not as a
  claim of historical accuracy for any specific month.
- See `docs/requirements.md` §6 for the full data-sourcing disclosure and
  `docs/prompt_journal.md` Entry 1 for how this was verified before being
  designed around.

## Running the analytics/scoring logic outside the API

Because `analytics.py` and `scoring.py` are pure functions over plain
dicts, you can use them directly in a notebook:

```python
from app.ingestion import load_records
from app import analytics, scoring

records, used_real = load_records()
scores = scoring.score_all_pairs(records)
top5 = scores[:5]
```

## Presentation

`presentation/ERCOT_CRR_Capstone_Presentation.pptx` is a ready-to-edit
60-minute deck outline covering ERCOT CRR fundamentals, the AI-assisted
build workflow, a live-demo script (walks the same four tabs as the
artifact), and lessons learned / future enhancements (also written out in
full in `docs/lessons_learned_and_future_work.md`).
