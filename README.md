# ERCOT CRR Trading Console

A market-intelligence web app for ERCOT Congestion Revenue Rights (CRR)
markets — auction activity, participant positions, real settlement value,
and the live transmission constraints behind congestion.

> **Analytics tooling, not trading advice.** Every figure in this app is a
> transparent, auditable computation over real ERCOT data — never a price
> prediction or a bidding recommendation.

## 1. What the app does

Five pages tell one connected story: what CRR paths were auctioned, who
holds them, how those positions actually settled (real ERCOT Day-Ahead
prices, not the auction price), and what live grid constraints are
driving the underlying congestion. See
[`docs/DEMO_WALKTHROUGH.md`](docs/DEMO_WALKTHROUGH.md) for a live-demo
speaking guide and [`docs/CRR_GLOSSARY.md`](docs/CRR_GLOSSARY.md) for
plain-language term definitions.

## 2. Tech stack

- **Backend:** Python / FastAPI, pure-function analytics modules, pytest
- **Frontend:** React + Vite, `recharts` for charts, no UI framework
- **Data:** real bundled ERCOT MIS auction data (default), optional SQL
  Server, optional live ERCOT Public API for settlement prices and
  transmission constraints

## 3. Data sources

- **Bundled real ERCOT CRR auction results** (`data/raw/crr_auction/`) —
  13 months, ~1.1M records, fetched directly from ERCOT's public MIS
  servlet. This is the default data source; no setup required.
- **Real ERCOT Market Participants List** (`data/reference/participants.csv`)
- **Live ERCOT Public API** (`api.ercot.com`, free registration) — real
  Day-Ahead settlement point prices (Path Settlements) and real binding
  transmission constraints (Binding Constraints). Optional; see §6.
- **Optional SQL Server** — point the backend at your own warehouse
  instead of the bundled data. See `backend/app/db.py` and
  `backend/scripts/create_sql_server_schema.sql`.
- **Synthetic fallback** — a seeded, clearly-labeled generator used only
  if the bundled data and SQL Server are both unavailable. The active
  data source is always surfaced (`data_source` on `/api/meta`,
  `/api/dashboard`, `/api/system/status`), so the app never silently
  shows fake data as real. See §8.

## 4. Running the backend

```bash
cd backend
pip install -r requirements.txt
python -m pytest -q          # 192 tests, all passing
uvicorn app.main:app --reload --port 8000
# http://localhost:8000/docs for interactive Swagger UI
```

No environment variables are required — the backend reads the bundled
real ERCOT data by default.

## 5. Running the frontend

```bash
cd frontend
npm install
cp .env.example .env.local     # points VITE_API_BASE_URL at your backend
npm run dev                    # http://localhost:5173
```

Production build: `npm run build` (outputs `frontend/dist/`), deployable
to any static host that can reach a running backend.

## 6. Environment variables

All optional — the app runs on bundled real data with none of these set.

| Variable | Enables |
|---|---|
| `ERCOT_API_USERNAME` / `ERCOT_API_PASSWORD` / `ERCOT_API_SUBSCRIPTION_KEY` | Live ERCOT Public API (Path Settlements, Binding Constraints) — free at https://apiexplorer.ercot.com/ |
| `DATABASE_URL` (or `SQL_SERVER_HOST`/`SQL_SERVER_DATABASE`/credentials) | Real SQL Server as the primary data source instead of bundled CSVs |
| `VITE_API_BASE_URL` (frontend `.env.local`) | Where the console looks for the backend |

Full details in `backend/.env.example` and `frontend/.env.example`
(gitignored — real credentials never get committed).

## 7. Main features

- Server-side, filter-before-paginate tables everywhere the data is
  large (Certificates, Path settlement value, Binding Constraints)
- Searchable comboboxes (participant, path, constraint) driven by the
  full real dataset, never just the currently-loaded page
- Strict CRR-type (Obligation/Option) filtering throughout
- Real settlement value: Sink SPP − Source SPP (Obligation), floored at
  zero (Option), computed from live ERCOT Day-Ahead prices
- Live ERCOT transmission constraints with real shadow prices — no
  invented severity classification, the real $/MWh number speaks for
  itself
- Every page states plainly which data is real-time vs. settled-auction,
  and never merges the two clocks

## 8. Real ERCOT data disclaimer

Auction data, participant records, and (when configured) live settlement
prices and transmission constraints are all real ERCOT data — never
fabricated. A small synthetic fallback exists purely so the app degrades
gracefully if the bundled data is ever missing; when active, it uses
fictional participant names and is always disclosed via
`data_source`/`data_source_warning` in the API response, never presented
as real. As shipped and configured, the running app uses 100% real data.

## 9. Page-by-page overview

| Page | Answers |
|---|---|
| **Overview** | What's happening in the CRR market right now? |
| **Source / Sink Explorer** | What did these paths cost at auction, over time? |
| **Participants** | Who owns what, how active are they, and what did their positions settle for? |
| **Path Settlements** | How did these Source → Sink paths actually settle, using real ERCOT SPPs? |
| **Binding Constraints** | What live transmission constraints are driving congestion right now? |

## 10. Testing / build

```bash
# Backend
cd backend && python -m pytest -q

# Frontend
cd frontend && npm run build
```

## More documentation

- [`docs/DEMO_WALKTHROUGH.md`](docs/DEMO_WALKTHROUGH.md) — live-demo speaking guide
- [`docs/CRR_GLOSSARY.md`](docs/CRR_GLOSSARY.md) — plain-language term glossary
- [`docs/requirements.md`](docs/requirements.md) — full functional/non-functional requirements
- [`docs/triple_check_review.md`](docs/triple_check_review.md) — multi-round engineering/trader/UX review log
- [`docs/lessons_learned_and_future_work.md`](docs/lessons_learned_and_future_work.md)
- [`docs/prompt_journal.md`](docs/prompt_journal.md) — AI-assisted build process log
