# Settlement-Price Opportunity Signals & Participant P&L Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the Opportunity Signals and Participants pages so both are driven by real ERCOT settlement point prices (SPP) — not CRR auction bid/clearing prices — per the 2026-09-21 feedback call with Reginald Wade, and fix a real, currently-broken parsing bug in the live ERCOT price client uncovered while scoping this work.

**Architecture:** The backend already has 90% of the plumbing (`ercot_live.py` fetches real DAM SPP data; `live_congestion.py` computes Source/Sink spread = the literal Obligation-CRR settlement formula). This plan (1) fixes a real-world API response-shape bug in that path, (2) extends it with a daily time series and an Option payoff variant, (3) adds one new endpoint exposing that per pair for charting and one new endpoint joining it against each participant's already-known awarded MW to compute realized settlement $ ("who won, who lost"), and (4) wires both into the existing React pages using the same recharts/table patterns already used in `Explorer.jsx`.

**Tech Stack:** Python/FastAPI backend (pure functions in `analytics.py`-style modules, pytest), React/Vite frontend with `recharts`, no new dependencies.

## Global Constraints

- Every new backend function is a pure, dict-in/dict-out function, unit tested in isolation, matching the existing `analytics.py`/`live_congestion.py` style — no ORM/framework coupling.
- Every new live-data code path must degrade honestly (a clear error/empty-state, never a silent wrong number or a crash) — matches this project's existing pattern for `/api/live/*` endpoints.
- Live settlement data only applies to real ERCOT hub/load-zone pairs (`domain.is_live_api_eligible`) — the project's illustrative synthetic `GEN_NODES` pairs must show an honest "not available for this corridor" state, never fabricated numbers.
- Do not touch the CRR-auction-clearing-price scoring math in `scoring.py` — Reginald's ask is to *add* real settlement-price history alongside it and make the distinction between the two explicit in the UI, not to delete a working, tested feature.
- Match existing code style exactly: snake_case Python, the project's existing docstring density, the frontend's existing `var(--...)` CSS tokens and `panel`/`field-row`/`seg`/`state-msg` classes (see `frontend/src/styles.css` and `Explorer.jsx`).
- All 136 existing backend tests must keep passing after every task (`cd backend && python -m pytest -q`).

---

### Task 1: Fix the real ERCOT `hourEnding` parsing bug

**Context:** Live-testing `fetch_settlement_point_hourly_prices` against the real, credentialed ERCOT API during planning surfaced a real bug: ERCOT's live API now returns `hourEnding` as a string like `"01:00"`, not the bare integer (`8`, `9`) the existing code and its tests assume. `int(float("01:00"))` raises `ValueError: could not convert string to float: '01:00'`, meaning the entire live-settlement-price path (already shipped, used by `/api/pairs/{source}/{sink}/live-lmp-spread`) is currently broken end-to-end against the real API. This must be fixed before anything in this plan can work against real data.

**Files:**
- Modify: `backend/app/live_congestion.py:104-108` (inside `fetch_settlement_point_hourly_prices`)
- Test: `backend/tests/test_live_congestion.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_live_congestion.py` (near the top, after the imports — add `_parse_hour_ending` to the import line):

```python
from app.live_congestion import (
    LIVE_PARTICIPANT_TAG,
    _parse_hour_ending,
    aggregate_to_monthly_records,
    classify_tou,
    compute_spread_records,
    fetch_live_pair_records,
    fetch_settlement_point_hourly_prices,
    parse_api_rows,
    total_pages,
)
```

Add this test anywhere in the file:

```python
@pytest.mark.parametrize(
    "raw,expected",
    [
        (8, 8),
        (8.0, 8),
        ("8", 8),
        ("08", 8),
        ("01:00", 1),
        ("24:00", 24),
        ("14:00", 14),
    ],
)
def test_parse_hour_ending_handles_int_and_real_api_hhmm_string(raw, expected):
    # ERCOT's real live API returns hourEnding as "01:00"-style strings, not
    # bare integers -- confirmed 2026-09-21 against the actual credentialed
    # API, which raised ValueError under the old int(float(x)) parsing.
    assert _parse_hour_ending(raw) == expected


def test_fetch_settlement_point_hourly_prices_parses_real_hhmm_hour_ending(monkeypatch):
    client = MagicMock()
    page = {
        "fields": [{"name": "deliveryDate"}, {"name": "hourEnding"}, {"name": "settlementPointPrice"}],
        "data": [["2026-09-02", "01:00", 28.46], ["2026-09-02", "02:00", 25.92]],
        "_meta": {"totalPages": 1},
    }
    client.get_dam_settlement_point_prices.return_value = page

    result = fetch_settlement_point_hourly_prices(client, "HB_WEST", "2026-09-01", "2026-09-02")

    assert result == [
        {"delivery_date": "2026-09-02", "hour_ending": 1, "price": 28.46},
        {"delivery_date": "2026-09-02", "hour_ending": 2, "price": 25.92},
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_live_congestion.py -k "hour_ending" -v`
Expected: `test_parse_hour_ending_handles_int_and_real_api_hhmm_string` fails with `ImportError: cannot import name '_parse_hour_ending'`.

- [ ] **Step 3: Implement the fix**

In `backend/app/live_congestion.py`, add this function above `fetch_settlement_point_hourly_prices` (after `_field`):

```python
def _parse_hour_ending(raw: Any) -> int:
    """Normalizes ERCOT's `hourEnding` field to a plain int (1-24).

    ERCOT's real live Public API returns this field as a zero-padded
    "HH:00" string (e.g. "01:00", "24:00"), not the bare integer this
    module originally assumed -- confirmed by a live, credentialed call
    during the 2026-09-21 settlement-price feature work, which raised
    ValueError under the old `int(float(x))` parsing. Also accepts a
    plain int/float or a numeric string, so any future API response shape
    change back to a bare number keeps working too.
    """
    if isinstance(raw, (int, float)):
        return int(raw)
    text = str(raw).strip()
    if ":" in text:
        text = text.split(":", 1)[0]
    return int(float(text))
```

Then change line ~105 (inside `fetch_settlement_point_hourly_prices`) from:

```python
                    "hour_ending": int(float(_field(row, "hourEnding", "HourEnding"))),
```

to:

```python
                    "hour_ending": _parse_hour_ending(_field(row, "hourEnding", "HourEnding")),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_live_congestion.py -v`
Expected: all tests pass, including the two new ones.

- [ ] **Step 5: Verify against the real live API**

Run:
```bash
cd backend && python3 -c "
from dotenv import load_dotenv
load_dotenv()
from app.ercot_live import ErcotApiClient
from app.live_congestion import fetch_settlement_point_hourly_prices
c = ErcotApiClient()
rows = fetch_settlement_point_hourly_prices(c, 'HB_WEST', '2026-09-01', '2026-09-05')
print('OK, rows:', len(rows), rows[:2])
"
```
Expected: `OK, rows: <N> [...]` with real price data, no traceback.

- [ ] **Step 6: Commit**

```bash
cd backend && git add app/live_congestion.py tests/test_live_congestion.py
git commit -m "fix: parse ERCOT's real HH:MM hourEnding format in live SPP client"
```

---

### Task 2: Add daily settlement series + monthly per-TOU settlement value to `live_congestion.py`

**Context:** The existing `aggregate_to_monthly_records` only produces one Obligation-shaped clearing-price average per (month, TOU) — enough to feed the old scoring pipeline, but not enough to (a) chart a real day-by-day settlement price history, or (b) compute an Option payoff (`max(spread, 0)`), or (c) compute the *summed* per-MW dollar value a participant would realize over a period (as opposed to an average). This task adds those three primitives.

**Files:**
- Modify: `backend/app/live_congestion.py`
- Test: `backend/tests/test_live_congestion.py`

**Interfaces:**
- Produces: `aggregate_to_daily_series(hourly_spreads: list[dict]) -> list[dict]` — each row `{"date": "YYYY-MM-DD", "obligation_price": float, "option_price": float}`, sorted by date.
- Produces: `aggregate_to_period_settlement_value(hourly_spreads: list[dict]) -> list[dict]` — each row `{"auction_month": "YYYY-MM", "time_of_use": str, "obligation_value_per_mw": float, "option_value_per_mw": float, "hours": int}`, sorted by (month, time_of_use). `obligation_value_per_mw`/`option_value_per_mw` are **sums** (not averages) of the hourly payoff across the bucket — this is $ per MW of award held for that whole month/TOU bucket, i.e. exactly what Task 4 multiplies by `awarded_mw`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_live_congestion.py` (update the import block to also pull in the two new names):

```python
from app.live_congestion import (
    LIVE_PARTICIPANT_TAG,
    _parse_hour_ending,
    aggregate_to_daily_series,
    aggregate_to_monthly_records,
    aggregate_to_period_settlement_value,
    classify_tou,
    compute_spread_records,
    fetch_live_pair_records,
    fetch_settlement_point_hourly_prices,
    parse_api_rows,
    total_pages,
)
```

```python
def test_aggregate_to_daily_series_averages_per_day_and_computes_option_floor():
    hourly = [
        {"delivery_date": "2026-01-01", "hour_ending": 1, "spread": 10.0, "time_of_use": "OFF_PEAK"},
        {"delivery_date": "2026-01-01", "hour_ending": 2, "spread": -4.0, "time_of_use": "OFF_PEAK"},
        {"delivery_date": "2026-01-02", "hour_ending": 1, "spread": 6.0, "time_of_use": "OFF_PEAK"},
    ]
    series = aggregate_to_daily_series(hourly)
    assert series == [
        {"date": "2026-01-01", "obligation_price": 3.0, "option_price": 5.0},  # avg(10,-4)=3; avg(10,0)=5
        {"date": "2026-01-02", "obligation_price": 6.0, "option_price": 6.0},
    ]


def test_aggregate_to_daily_series_empty_input():
    assert aggregate_to_daily_series([]) == []


def test_aggregate_to_period_settlement_value_sums_not_averages_and_floors_option():
    hourly = [
        {"delivery_date": "2026-01-05", "hour_ending": 8, "spread": 10.0, "time_of_use": "PEAK_WD"},
        {"delivery_date": "2026-01-12", "hour_ending": 9, "spread": -3.0, "time_of_use": "PEAK_WD"},
        {"delivery_date": "2026-02-05", "hour_ending": 8, "spread": 100.0, "time_of_use": "PEAK_WD"},
    ]
    result = aggregate_to_period_settlement_value(hourly)
    by_key = {(r["auction_month"], r["time_of_use"]): r for r in result}

    jan = by_key[("2026-01", "PEAK_WD")]
    assert jan["obligation_value_per_mw"] == pytest.approx(7.0)   # 10 + (-3)
    assert jan["option_value_per_mw"] == pytest.approx(10.0)      # max(10,0) + max(-3,0)
    assert jan["hours"] == 2

    feb = by_key[("2026-02", "PEAK_WD")]
    assert feb["obligation_value_per_mw"] == pytest.approx(100.0)
    assert feb["option_value_per_mw"] == pytest.approx(100.0)
    assert feb["hours"] == 1


def test_aggregate_to_period_settlement_value_empty_input():
    assert aggregate_to_period_settlement_value([]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_live_congestion.py -k "daily_series or period_settlement_value" -v`
Expected: `ImportError` (names don't exist yet).

- [ ] **Step 3: Implement**

Add to `backend/app/live_congestion.py`, directly below `aggregate_to_monthly_records`:

```python
def aggregate_to_daily_series(hourly_spreads: list[dict]) -> list[dict]:
    """Averages hourly Source/Sink spreads into one row per calendar day,
    for charting a real settlement-price history -- Obligation is the raw
    average spread (can be negative: the holder owes ERCOT that hour);
    Option is the average of max(spread, 0) per hour (an Option holder
    never owes money, per ERCOT's actual CRR settlement rules)."""
    by_day: dict[str, list[float]] = defaultdict(list)
    for row in hourly_spreads:
        by_day[row["delivery_date"]].append(row["spread"])

    out = []
    for day in sorted(by_day):
        spreads = by_day[day]
        out.append(
            {
                "date": day,
                "obligation_price": round(sum(spreads) / len(spreads), 3),
                "option_price": round(sum(max(s, 0.0) for s in spreads) / len(spreads), 3),
            }
        )
    return out


def aggregate_to_period_settlement_value(hourly_spreads: list[dict]) -> list[dict]:
    """Sums (not averages) hourly Source/Sink spreads into one row per
    (auction_month, time_of_use) bucket -- this is the real $/MW-held value
    a CRR of that type would have realized across every hour in that
    bucket, i.e. exactly the number to multiply by a participant's
    awarded_mw to get their real settlement $ for that month (see
    scoring the same way ERCOT itself does: Obligation pays sink-source
    every hour including negative hours; Option only pays the positive
    hours, per the module docstring above)."""
    by_key: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in hourly_spreads:
        month = row["delivery_date"][:7]
        by_key[(month, row["time_of_use"])].append(row["spread"])

    out = []
    for (month, tou), spreads in sorted(by_key.items()):
        out.append(
            {
                "auction_month": month,
                "time_of_use": tou,
                "obligation_value_per_mw": round(sum(spreads), 3),
                "option_value_per_mw": round(sum(max(s, 0.0) for s in spreads), 3),
                "hours": len(spreads),
            }
        )
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_live_congestion.py -v`
Expected: all pass (previous + new).

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/live_congestion.py tests/test_live_congestion.py
git commit -m "feat: add daily settlement series and per-MW settlement value aggregation"
```

---

### Task 3: Add `live_eligible` to `/api/pairs` and `/api/opportunity-scores`

**Context:** The frontend needs an honest, data-driven way to know which of the 30 tracked corridors can show a real live settlement chart (real ERCOT hub/load-zone pairs) versus which can't (this project's illustrative synthetic `GEN_NODES` pairs) — `domain.is_live_api_eligible` already implements exactly this check, it's just not exposed in these two responses yet.

**Files:**
- Modify: `backend/app/main.py:132-154` (`pairs()`) and `:261-280` (`opportunity_scores()`)
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_api.py`:

```python
def test_pairs_endpoint_reports_live_eligibility():
    r = client.get("/api/pairs")
    assert r.status_code == 200
    body = r.json()
    assert len(body) > 0
    for pair in body:
        assert "live_eligible" in pair
        assert isinstance(pair["live_eligible"], bool)


def test_opportunity_scores_endpoint_reports_live_eligibility():
    r = client.get("/api/opportunity-scores")
    assert r.status_code == 200
    body = r.json()
    assert len(body) > 0
    for score in body:
        assert "live_eligible" in score
        assert isinstance(score["live_eligible"], bool)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api.py -k "live_eligibility" -v`
Expected: `KeyError`/`AssertionError` — field missing.

- [ ] **Step 3: Implement**

In `backend/app/main.py`, change the import line:

```python
from .domain import SP_BY_CODE, is_live_api_eligible
```
(already imported — no change needed there.)

In `pairs()`, inside the `for p in top_pairs:` loop, add one field to the dict literal:

```python
        out.append({
            "source": source,
            "source_name": _settlement_point_name(source),
            "sink": sink,
            "sink_name": _settlement_point_name(sink),
            "average_obligation_price": m["average"],
            "trend_direction": m["trend_direction"],
            "total_notional": p["total_notional"],
            "participant_count": p["participant_count"],
            "live_eligible": is_live_api_eligible(source, sink),
        })
```

In `opportunity_scores()`, add the same field to its dict literal:

```python
    return [
        {
            "source": s.source,
            "source_name": _settlement_point_name(s.source),
            "sink": s.sink,
            "sink_name": _settlement_point_name(s.sink),
            "score": s.score,
            "tier": s.tier,
            "factors": s.factors,
            "explanation": s.explanation,
            "metrics": s.metrics,
            "live_eligible": is_live_api_eligible(s.source, s.sink),
        }
        for s in scores
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_api.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/main.py tests/test_api.py
git commit -m "feat: expose live-settlement-data eligibility on pairs and opportunity scores"
```

---

### Task 4: New endpoint — real settlement-price history per pair

**Context:** This is the centerpiece of Reginald's feedback: "I would just have a mini time series plot there... go back to January 1st" of the *real settlement point price* spread (not the auction bid/clearing price already shown elsewhere). This wraps Task 1/2's fixed, extended `live_congestion.py` functions in a route, following the exact `_require_live_api`/`is_live_api_eligible`/`_ttl_cache` pattern `live_lmp_spread` and `_binding_constraints_cached` already use.

**Files:**
- Modify: `backend/app/main.py` (add route after `live_lmp_spread`, ~line 502)
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `fetch_settlement_point_hourly_prices(client, settlement_point, date_from, date_to)` from Task 1, `compute_spread_records(source_prices, sink_prices, source, sink)` (existing), `aggregate_to_daily_series(hourly_spreads)` from Task 2.
- Produces: `GET /api/pairs/{source}/{sink}/settlement-history?date_from=&date_to=` — route name other tasks/the frontend call by this exact path.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_api.py`:

```python
def test_settlement_history_without_credentials_returns_501(monkeypatch):
    monkeypatch.delenv("ERCOT_API_USERNAME", raising=False)
    monkeypatch.delenv("ERCOT_API_PASSWORD", raising=False)
    monkeypatch.delenv("ERCOT_API_SUBSCRIPTION_KEY", raising=False)
    r = client.get("/api/pairs/HB_WEST/HB_HOUSTON/settlement-history")
    assert r.status_code == 501


def test_settlement_history_rejects_synthetic_resource_node_pairs(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")
    r = client.get("/api/pairs/PANHANDLE_WIND_RN/HB_NORTH/settlement-history")
    assert r.status_code == 422


def test_settlement_history_success_with_mocked_client(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")

    import app.main as main_module

    fake_hourly = [
        {"delivery_date": "2026-01-01", "hour_ending": 8, "spread": 10.0, "time_of_use": "PEAK_WD"},
        {"delivery_date": "2026-01-02", "hour_ending": 8, "spread": -2.0, "time_of_use": "PEAK_WD"},
    ]
    monkeypatch.setattr(
        main_module,
        "fetch_settlement_point_hourly_prices",
        lambda client, sp, date_from, date_to: [{"delivery_date": "x", "hour_ending": 1, "price": 1.0}],
    )
    monkeypatch.setattr(main_module, "compute_spread_records", lambda src, snk, source, sink: fake_hourly)

    r = client.get(
        "/api/pairs/HB_WEST/HB_HOUSTON/settlement-history",
        params={"date_from": "2026-01-01", "date_to": "2026-01-02"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["data_source"] == "ercot_live_dam_spp"
    assert body["source"] == "HB_WEST"
    assert body["sink"] == "HB_HOUSTON"
    assert body["daily_series"] == [
        {"date": "2026-01-01", "obligation_price": 10.0, "option_price": 10.0},
        {"date": "2026-01-02", "obligation_price": -2.0, "option_price": 0.0},
    ]


def test_settlement_history_no_data_returns_404(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")

    import app.main as main_module

    monkeypatch.setattr(main_module, "fetch_settlement_point_hourly_prices", lambda *a, **k: [])
    monkeypatch.setattr(main_module, "compute_spread_records", lambda *a, **k: [])

    r = client.get("/api/pairs/HB_WEST/HB_HOUSTON/settlement-history")
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api.py -k "settlement_history" -v`
Expected: 404 for all (route doesn't exist yet).

- [ ] **Step 3: Implement**

In `backend/app/main.py`, change the `live_congestion` import line near the top:

```python
from .live_congestion import (
    aggregate_to_daily_series,
    compute_spread_records,
    fetch_live_pair_records,
    fetch_settlement_point_hourly_prices,
)
```

Add this route directly after `live_lmp_spread` (after its closing `}` around line 501):

```python
@app.get("/api/pairs/{source}/{sink}/settlement-history")
def settlement_history(
    source: str,
    sink: str,
    date_from: str | None = Query(None, description="YYYY-MM-DD, defaults to Jan 1 of the current year"),
    date_to: str | None = Query(None, description="YYYY-MM-DD, defaults to today"),
):
    """Real, live day-by-day Source/Sink settlement-price history -- what
    Reginald Wade's 2026-09-21 feedback asked for directly: a time series
    of the *real settlement point price* spread (not the CRR auction bid
    price shown in opportunity-scores/pair_series), with both the
    Obligation payoff (raw spread, can be negative) and Option payoff
    (floored at zero) shown side by side. Defaults to January 1st of the
    current year through today, matching Reginald's "just go back to
    January 1st" guidance, capped at 400 days so a very wide explicit
    range still degrades to a bounded number of ERCOT API calls."""
    _require_live_api()

    if source not in SP_BY_CODE or sink not in SP_BY_CODE:
        raise HTTPException(404, "Unknown settlement point")
    if not is_live_api_eligible(source, sink):
        raise HTTPException(
            422,
            f"{source} and/or {sink} are illustrative demo settlement points, not "
            "real ERCOT codes, so they can't be queried against the live API. "
            "Live settlement history is available for real ERCOT hub and load-zone pairs.",
        )

    resolved_date_to = date.fromisoformat(date_to) if date_to else date.today()
    resolved_date_from = (
        date.fromisoformat(date_from) if date_from else date(resolved_date_to.year, 1, 1)
    )
    if (resolved_date_to - resolved_date_from).days > 400:
        resolved_date_from = resolved_date_to - timedelta(days=400)

    try:
        client = _get_live_client()
        source_prices = fetch_settlement_point_hourly_prices(
            client, source, resolved_date_from.isoformat(), resolved_date_to.isoformat()
        )
        sink_prices = fetch_settlement_point_hourly_prices(
            client, sink, resolved_date_from.isoformat(), resolved_date_to.isoformat()
        )
    except ErcotApiError as e:
        raise HTTPException(502, str(e))

    hourly = compute_spread_records(source_prices, sink_prices, source, sink)
    if not hourly:
        raise HTTPException(
            404,
            f"ERCOT returned no DAM price data for {source}/{sink} in the requested "
            "window. This can happen for very new settlement points or during an "
            "ERCOT API outage -- try a narrower date range.",
        )

    daily_series = aggregate_to_daily_series(hourly)
    return {
        "source": source,
        "sink": sink,
        "data_source": "ercot_live_dam_spp",
        "date_from": resolved_date_from.isoformat(),
        "date_to": resolved_date_to.isoformat(),
        "daily_series": daily_series,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_api.py -v`
Expected: all pass.

- [ ] **Step 5: Verify against the real live API**

Run:
```bash
cd backend && uvicorn app.main:app --port 8000 &
sleep 2
curl -s "http://localhost:8000/api/pairs/HB_WEST/HB_HOUSTON/settlement-history?date_from=2026-09-01&date_to=2026-09-10" | python3 -m json.tool | head -30
kill %1
```
Expected: real JSON with a non-empty `daily_series`, no 5xx.

- [ ] **Step 6: Commit**

```bash
cd backend && git add app/main.py tests/test_api.py
git commit -m "feat: add /settlement-history endpoint for real per-pair SPP time series"
```

---

### Task 5: New endpoint — participant settlement leaderboard (winners & losers)

**Context:** Reginald's second major ask: "here's how much part[y] made... here's how much BP made... the biggest winners and losers" — computed the exact way he walked through by hand (sink SPP minus source SPP, times MW held, per month). This joins the real per-MW settlement value from Task 2 against each participant's already-known `awarded_mw` from the real CRR auction records for one pair/month.

**Files:**
- Modify: `backend/app/main.py` (add route after `settlement_history`)
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `aggregate_to_period_settlement_value(hourly_spreads)` from Task 2; `analytics.filter_records`, `_records()` (existing).
- Produces: `GET /api/pairs/{source}/{sink}/settlement-leaderboard?auction_month=YYYY-MM`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_api.py`:

```python
def test_settlement_leaderboard_without_credentials_returns_501(monkeypatch):
    monkeypatch.delenv("ERCOT_API_USERNAME", raising=False)
    monkeypatch.delenv("ERCOT_API_PASSWORD", raising=False)
    monkeypatch.delenv("ERCOT_API_SUBSCRIPTION_KEY", raising=False)
    r = client.get("/api/pairs/HB_WEST/HB_HOUSTON/settlement-leaderboard", params={"auction_month": "2026-01"})
    assert r.status_code == 501


def test_settlement_leaderboard_requires_auction_month():
    r = client.get("/api/pairs/HB_WEST/HB_HOUSTON/settlement-leaderboard")
    assert r.status_code == 422  # FastAPI's own required-query-param validation


def test_settlement_leaderboard_computes_realized_value_from_awarded_mw(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")

    import app.main as main_module

    fake_records = [
        {"auction_month": "2026-01", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "crr_type": "OBLIGATION", "time_of_use": "PEAK_WD", "clearing_price": 5.0,
         "awarded_mw": 10.0, "participant": "Winner Co", "is_synthetic": False},
        {"auction_month": "2026-01", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "crr_type": "OPTION", "time_of_use": "PEAK_WD", "clearing_price": 1.0,
         "awarded_mw": 20.0, "participant": "Option Holder Co", "is_synthetic": False},
        {"auction_month": "2026-02", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "crr_type": "OBLIGATION", "time_of_use": "PEAK_WD", "clearing_price": 5.0,
         "awarded_mw": 999.0, "participant": "Wrong Month Co", "is_synthetic": False},
    ]
    monkeypatch.setattr(main_module, "_records", lambda: fake_records)
    monkeypatch.setattr(main_module, "fetch_settlement_point_hourly_prices", lambda *a, **k: [{"x": 1}])
    monkeypatch.setattr(main_module, "compute_spread_records", lambda *a, **k: [
        {"delivery_date": "2026-01-05", "hour_ending": 8, "spread": 10.0, "time_of_use": "PEAK_WD"},
        {"delivery_date": "2026-01-12", "hour_ending": 8, "spread": -2.0, "time_of_use": "PEAK_WD"},
    ])

    r = client.get(
        "/api/pairs/HB_WEST/HB_HOUSTON/settlement-leaderboard",
        params={"auction_month": "2026-01"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["data_source"] == "ercot_live_dam_spp"
    rows = {row["participant"]: row for row in body["rows"]}

    # obligation_value_per_mw for 2026-01/PEAK_WD = 10 + (-2) = 8
    assert rows["Winner Co"]["realized_value"] == pytest.approx(80.0)   # 10 MW * 8
    assert rows["Winner Co"]["crr_type"] == "OBLIGATION"

    # option_value_per_mw for 2026-01/PEAK_WD = max(10,0) + max(-2,0) = 10
    assert rows["Option Holder Co"]["realized_value"] == pytest.approx(200.0)  # 20 MW * 10

    assert "Wrong Month Co" not in rows  # different auction_month, excluded


def test_settlement_leaderboard_no_awards_for_month_returns_empty_rows(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")

    import app.main as main_module

    monkeypatch.setattr(main_module, "_records", lambda: [])
    monkeypatch.setattr(main_module, "fetch_settlement_point_hourly_prices", lambda *a, **k: [{"x": 1}])
    monkeypatch.setattr(main_module, "compute_spread_records", lambda *a, **k: [
        {"delivery_date": "2026-01-05", "hour_ending": 8, "spread": 10.0, "time_of_use": "PEAK_WD"},
    ])

    r = client.get(
        "/api/pairs/HB_WEST/HB_HOUSTON/settlement-leaderboard",
        params={"auction_month": "2026-01"},
    )
    assert r.status_code == 200
    assert r.json()["rows"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_api.py -k "settlement_leaderboard" -v`
Expected: 404s (route doesn't exist yet).

- [ ] **Step 3: Implement**

In `backend/app/main.py`, extend the `live_congestion` import from Task 4 to also pull in `aggregate_to_period_settlement_value`:

```python
from .live_congestion import (
    aggregate_to_daily_series,
    aggregate_to_period_settlement_value,
    compute_spread_records,
    fetch_live_pair_records,
    fetch_settlement_point_hourly_prices,
)
```

Add this route directly after `settlement_history`:

```python
@app.get("/api/pairs/{source}/{sink}/settlement-leaderboard")
def settlement_leaderboard(source: str, sink: str, auction_month: str = Query(..., description="YYYY-MM")):
    """Real winners-and-losers board for one corridor/month: joins each
    participant's already-known awarded_mw (from the real CRR auction
    records) against the real settlement value per MW for that exact
    (month, time_of_use) bucket -- i.e. literally the by-hand calculation
    Reginald Wade walked through in the 2026-09-21 feedback call (sink SPP
    minus source SPP, summed over the hours held, times MW). Obligation
    awards are valued off the raw (possibly negative) spread sum; Option
    awards off the floored-at-zero spread sum, matching ERCOT's actual
    CRR payoff rules for each type."""
    _require_live_api()

    if source not in SP_BY_CODE or sink not in SP_BY_CODE:
        raise HTTPException(404, "Unknown settlement point")
    if not is_live_api_eligible(source, sink):
        raise HTTPException(
            422,
            f"{source} and/or {sink} are illustrative demo settlement points, not "
            "real ERCOT codes, so they can't be queried against the live API. "
            "The settlement leaderboard is available for real ERCOT hub and load-zone pairs.",
        )

    try:
        year, month_num = auction_month.split("-")
        month_start = date(int(year), int(month_num), 1)
    except (ValueError, IndexError):
        raise HTTPException(422, "auction_month must be in YYYY-MM format")
    month_end = (date(month_start.year + (month_start.month == 12), (month_start.month % 12) + 1, 1)
                 - timedelta(days=1))

    try:
        client = _get_live_client()
        source_prices = fetch_settlement_point_hourly_prices(
            client, source, month_start.isoformat(), month_end.isoformat()
        )
        sink_prices = fetch_settlement_point_hourly_prices(
            client, sink, month_start.isoformat(), month_end.isoformat()
        )
    except ErcotApiError as e:
        raise HTTPException(502, str(e))

    hourly = compute_spread_records(source_prices, sink_prices, source, sink)
    value_by_key = {
        (v["auction_month"], v["time_of_use"]): v
        for v in aggregate_to_period_settlement_value(hourly)
    }

    awards = analytics.filter_records(_records(), source=source, sink=sink)
    awards = [r for r in awards if r["auction_month"] == auction_month]

    rows = []
    for r in awards:
        value_row = value_by_key.get((auction_month, r["time_of_use"]))
        if value_row is None:
            continue
        per_mw = (
            value_row["obligation_value_per_mw"]
            if r["crr_type"] == "OBLIGATION"
            else value_row["option_value_per_mw"]
        )
        rows.append(
            {
                "participant": r["participant"],
                "crr_type": r["crr_type"],
                "time_of_use": r["time_of_use"],
                "awarded_mw": r["awarded_mw"],
                "realized_value": round(r["awarded_mw"] * per_mw, 2),
            }
        )
    rows.sort(key=lambda row: row["realized_value"], reverse=True)

    return {
        "source": source,
        "sink": sink,
        "auction_month": auction_month,
        "data_source": "ercot_live_dam_spp",
        "rows": rows,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_api.py -v && python -m pytest -q`
Expected: all 136+ tests pass.

- [ ] **Step 5: Commit**

```bash
cd backend && git add app/main.py tests/test_api.py
git commit -m "feat: add /settlement-leaderboard endpoint for real participant win/loss"
```

---

### Task 6: Frontend — `api.js` additions

**Files:**
- Modify: `frontend/src/api.js`

- [ ] **Step 1: Add the two new client calls**

In `frontend/src/api.js`, add to the exported `api` object (after `bindingConstraints`):

```javascript
  settlementHistory: (source, sink, params) =>
    getJSON(`/api/pairs/${source}/${sink}/settlement-history`, params),
  settlementLeaderboard: (source, sink, auctionMonth) =>
    getJSON(`/api/pairs/${source}/${sink}/settlement-leaderboard`, { auction_month: auctionMonth }),
```

- [ ] **Step 2: Verify by hand**

Run: `cd frontend && npm run dev` (backend must be running on :8000), then in the browser console at `http://localhost:5173`: this is covered by Tasks 7/8's manual verification, no standalone test needed for a 4-line data-fetch addition matching the file's existing untested pattern.

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/api.js
git commit -m "feat: add settlementHistory/settlementLeaderboard API client calls"
```

---

### Task 7: Frontend — rework `Signals.jsx` with a real settlement-price chart

**Context:** Reginald: *"I would just have a mini time series plot there... showcase more of the settlement price."* Keep the existing Low/Medium/High tier cards (still a valid, tested, explainable signal off auction clearing prices — Reginald never asked to remove it, and the project's own review log treats it as a deliberate, working feature) but make each card expandable to reveal a real settlement-price chart, and make the bid-price-vs-settlement-price distinction explicit in the UI copy — directly answering Reginald's "those are only your bid prices, those aren't your settlement prices" correction so a viewer of the app learns the same distinction he taught Saif.

**Files:**
- Modify: `frontend/src/pages/Signals.jsx`

- [ ] **Step 1: Rewrite the file**

Replace the full contents of `frontend/src/pages/Signals.jsx` with:

```jsx
import React, { useEffect, useMemo, useState } from "react";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
} from "recharts";
import { api } from "../api.js";

const TIER_FILTERS = ["All", "High", "Medium", "Low"];
const FACTOR_COLOR = { value: "var(--cyan)", trend: "var(--cyan)", consistency: "var(--cyan)", liquidity: "var(--cyan)" };

function currentYearJan1() {
  return `${new Date().getFullYear()}-01-01`;
}
function today() {
  return new Date().toISOString().slice(0, 10);
}

function SettlementChart({ source, sink }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    api
      .settlementHistory(source, sink, { date_from: currentYearJan1(), date_to: today() })
      .then((body) => { if (!cancelled) setData(body.daily_series); })
      .catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [source, sink]);

  if (error) return <div className="state-msg error">Couldn't load real settlement history — {error}</div>;
  if (!data) return <div className="state-msg">Loading real ERCOT settlement price history…</div>;
  if (data.length === 0) return <div className="state-msg">No settlement price data in this window.</div>;

  return (
    <div style={{ width: "100%", height: 220, marginTop: 12 }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 6, right: 12, left: -6, bottom: 0 }}>
          <CartesianGrid stroke="#171f29" vertical={false} />
          <XAxis dataKey="date" tick={{ fill: "#64768a", fontSize: 10 }} axisLine={{ stroke: "#212b37" }} tickLine={false} />
          <YAxis tick={{ fill: "#64768a", fontSize: 11 }} axisLine={{ stroke: "#212b37" }} tickLine={false} width={54} />
          <Tooltip contentStyle={{ background: "#10161e", border: "1px solid #212b37", fontSize: 12 }} labelStyle={{ color: "#dee6ec" }} />
          <Line type="monotone" dataKey="obligation_price" name="Obligation ($/MWh)" stroke="#3fbf8f" strokeWidth={2} dot={false} connectNulls />
          <Line type="monotone" dataKey="option_price" name="Option ($/MWh)" stroke="#de9a4e" strokeWidth={2} dot={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function Signals() {
  const [scores, setScores] = useState(null);
  const [tier, setTier] = useState("All");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.opportunityScores().then(setScores).catch((e) => setError(e.message));
  }, []);

  const filtered = useMemo(() => {
    if (!scores) return [];
    const q = query.trim().toLowerCase();
    return scores.filter((s) => {
      if (tier !== "All" && s.tier !== tier) return false;
      if (!q) return true;
      return (
        s.source_name.toLowerCase().includes(q) ||
        s.sink_name.toLowerCase().includes(q) ||
        s.source.toLowerCase().includes(q) ||
        s.sink.toLowerCase().includes(q)
      );
    });
  }, [scores, tier, query]);

  if (error) return <div className="state-msg error">Couldn't reach the backend — {error}</div>;
  if (!scores) return <div className="state-msg">Loading opportunity signals…</div>;

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Opportunity signals</h1>
          <p className="subline">
            <span className="dot" />
            {scores.length} scored corridors — the tier score below is an explainable signal built from
            historical CRR <em>auction clearing prices</em> (bid prices); expand a card for the real ERCOT
            <em> settlement point price</em> history — what actually got paid, not what was bid.
          </p>
        </div>
      </header>

      <div className="field-row">
        <div className="seg">
          {TIER_FILTERS.map((t) => (
            <button key={t} className={tier === t ? "active" : ""} onClick={() => setTier(t)}>
              {t}
            </button>
          ))}
        </div>
        <input
          type="search"
          placeholder="Search hub or zone…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ minWidth: 220 }}
        />
      </div>

      {filtered.length === 0 ? (
        <div className="state-msg">No corridors match this filter.</div>
      ) : (
        filtered.map((s) => {
          const key = `${s.source}-${s.sink}`;
          const isOpen = expanded === key;
          return (
            <div className="score-card" key={key}>
              <div className="score-head">
                <div>
                  <div className="score-path">
                    {s.source_name} → {s.sink_name}
                  </div>
                  <span className={`tier-chip ${s.tier.toLowerCase()}`}>{s.tier.toUpperCase()}</span>
                </div>
                <div className="score-num mono num">{s.score}</div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px 32px" }}>
                <div>
                  {Object.entries(s.factors).map(([name, f]) => (
                    <div className="factor-row" key={name}>
                      <span className="factor-label">{name}</span>
                      <div className="bar-track">
                        <div className="bar-fill" style={{ width: `${f.score}%`, background: FACTOR_COLOR[name] || "var(--cyan)" }} />
                      </div>
                      <span className="factor-val mono num">{Math.round(f.score)}</span>
                    </div>
                  ))}
                </div>
                <div>
                  {s.explanation.map((line, i) => (
                    <p className="score-explain" key={i}>
                      {line}
                    </p>
                  ))}
                </div>
              </div>

              {s.live_eligible ? (
                <>
                  <button
                    onClick={() => setExpanded(isOpen ? null : key)}
                    style={{ background: "none", border: "1px solid var(--line)", color: "var(--dim)", padding: "4px 10px", fontSize: 11.5, cursor: "pointer", borderRadius: 3, marginTop: 12 }}
                  >
                    {isOpen ? "Hide" : "Show"} real settlement price history ({currentYearJan1()} → today)
                  </button>
                  {isOpen && <SettlementChart source={s.source} sink={s.sink} />}
                </>
              ) : (
                <p className="score-explain" style={{ marginTop: 12, fontStyle: "italic" }}>
                  Real settlement price history isn't available for this corridor — {s.source_name} / {s.sink_name}
                  is one of this project's illustrative synthetic resource nodes, not a real ERCOT hub or load zone.
                </p>
              )}
            </div>
          );
        })
      )}
    </>
  );
}
```

- [ ] **Step 2: Manually verify in the browser**

Run `cd backend && uvicorn app.main:app --reload --port 8000` and, in another terminal, `cd frontend && npm run dev`, then open `http://localhost:5173/signals`:
- Confirm the subline explains the bid-price vs settlement-price distinction.
- Click "Show real settlement price history" on a hub/load-zone corridor (e.g. West Hub → Houston Hub) and confirm a real two-line chart (Obligation/Option) renders with no console errors.
- Confirm a corridor built from a `*_RN` synthetic node shows the "isn't available" message instead of a button.

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/pages/Signals.jsx
git commit -m "feat: show real ERCOT settlement price history on Opportunity Signals"
```

---

### Task 8: Frontend — rework `Participants.jsx` with filters and a winners/losers leaderboard

**Context:** Reginald: *"adding the filter stuff for the participants"* and *"here's how much [X] made... the biggest winners and losers."* Adds a corridor + auction-month picker (reusing the same `api.pairs()` list `Explorer.jsx` already uses) and a ranked leaderboard table powered by Task 5's endpoint, alongside the existing search/detail view (kept as-is — Reginald called the existing structure "good").

**Files:**
- Modify: `frontend/src/pages/Participants.jsx`

- [ ] **Step 1: Add the leaderboard section**

In `frontend/src/pages/Participants.jsx`, add these imports at the top (after the existing `api` import):

```javascript
import React, { useEffect, useMemo, useState } from "react";
```
(already present — no change to that line.) Then add a new function component in the same file, above `export default function Participants()`:

```jsx
function pairKey(p) { return `${p.source}__${p.sink}`; }
function pairLabel(p) { return `${p.source_name} → ${p.sink_name}`; }

function SettlementLeaderboard() {
  const [pairs, setPairs] = useState([]);
  const [selectedKey, setSelectedKey] = useState("");
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.pairs().then((p) => {
      const eligible = p.filter((x) => x.live_eligible);
      setPairs(eligible);
      if (eligible.length && !selectedKey) setSelectedKey(pairKey(eligible[0]));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selected = pairs.find((p) => pairKey(p) === selectedKey);

  useEffect(() => {
    if (!selected || !month) return;
    setRows(null);
    setError(null);
    api
      .settlementLeaderboard(selected.source, selected.sink, month)
      .then((body) => setRows(body.rows))
      .catch((e) => setError(e.message));
  }, [selected, month]);

  return (
    <section className="panel" style={{ marginTop: 20 }}>
      <div className="panel-head">
        <h2>Winners &amp; losers — real settlement value</h2>
      </div>
      <p className="panel-note" style={{ marginBottom: 10 }}>
        Who actually made or lost money holding this corridor this month, computed from real ERCOT
        settlement point prices × each participant's awarded MW — separate from the "notional" figure
        below, which is what they paid at auction, not what they realized.
      </p>
      <div className="field-row">
        <select value={selectedKey} onChange={(e) => setSelectedKey(e.target.value)}>
          {pairs.length === 0 && <option value="">No live-eligible corridors</option>}
          {pairs.map((p) => (
            <option key={pairKey(p)} value={pairKey(p)}>{pairLabel(p)}</option>
          ))}
        </select>
        <input
          type="month"
          value={month}
          onChange={(e) => setMonth(e.target.value)}
        />
      </div>

      {error ? (
        <div className="state-msg error">Couldn't load the leaderboard — {error}</div>
      ) : !selected ? (
        <div className="state-msg">No real ERCOT hub/load-zone corridors available for live settlement data.</div>
      ) : !rows ? (
        <div className="state-msg">Loading real settlement values…</div>
      ) : rows.length === 0 ? (
        <div className="state-msg">No auction awards on this corridor for {month}.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Participant</th>
              <th>Type</th>
              <th>Time of use</th>
              <th className="num-col">MW held</th>
              <th className="num-col">Realized ($)</th>
            </tr>
          </thead>
          <tbody className="mono">
            {rows.map((r, i) => (
              <tr key={i}>
                <td style={{ fontFamily: "Archivo, sans-serif" }}>{r.participant}</td>
                <td>{r.crr_type}</td>
                <td>{r.time_of_use}</td>
                <td className="num-col num">{r.awarded_mw}</td>
                <td
                  className="num-col num"
                  style={{ color: r.realized_value >= 0 ? "var(--green)" : "var(--red, #e0708f)" }}
                >
                  {r.realized_value.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
```

Then, inside `export default function Participants()`'s returned JSX, add `<SettlementLeaderboard />` right after the closing `</div>` of `participants-layout` (i.e. as the last element before the final `</>`):

```jsx
      <div className="participants-layout">
        {/* ... existing content unchanged ... */}
      </div>

      <SettlementLeaderboard />
    </>
```

- [ ] **Step 2: Manually verify in the browser**

With both servers running, open `http://localhost:5173/participants`:
- Confirm the existing search/detail panel still works unchanged.
- Confirm the new "Winners & losers" panel below it loads a corridor picker (real hub/load-zone pairs only) and a month picker, and renders a ranked table with green/negative-colored realized values.
- Change the month to one with no real auction awards and confirm the honest "No auction awards on this corridor for {month}" message (not a blank table or a crash).

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/pages/Participants.jsx
git commit -m "feat: add real settlement-value winners/losers leaderboard to Participants"
```

---

### Task 9: Update project docs to reflect this round

**Context:** This project has an established convention (see `README.md`, `docs/triple_check_review.md`) of documenting every feature round and every real bug found/fixed, rather than silently shipping. This task keeps that convention intact for this round.

**Files:**
- Modify: `README.md`
- Modify: `docs/triple_check_review.md`

- [ ] **Step 1: Update `README.md`**

In the "Opportunity Signals" and "Participants" bullet points under "Quick start — the console (frontend)", update the text to mention the new real settlement-price chart and leaderboard respectively (mirroring the existing bullet style for Binding Constraints).

- [ ] **Step 2: Append a new dated section to `docs/triple_check_review.md`**

Add a `## v1.6 pass (2026-09-21) -- real settlement-price signals, participant P&L` section following the exact three-persona table format already used by every prior round in that file, documenting: the real `hourEnding` parsing bug found and fixed (name it, and that the existing tests didn't catch it because their mocks encoded the old, wrong assumption), the new settlement-history and settlement-leaderboard endpoints, and the Signals/Participants UI changes — using the same "Check / Verdict / Evidence" table structure as every prior round.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/triple_check_review.md
git commit -m "docs: record the v1.6 settlement-price signals and participant P&L round"
```

---

## Self-Review Notes

- **Spec coverage:** Transcript ask → task mapping: "settlement prices, not bid prices" (Task 4/7), "mini time series plot per pair, back to Jan 1st" (Task 4/7), "keep opportunity signals or rename to path settlements" (left as user's own call — not renamed by this plan, flagged in the final chat summary instead of forced), "filter stuff for participants" (Task 8's corridor+month picker), "winners and losers, how much X made" (Task 5/8), "who owns these paths" MW context (Task 8 shows `awarded_mw` per row). The real live-API bug found while scoping (Task 1) blocks every other task, so it's first.
- **Placeholder scan:** No TBD/TODO markers; every step has runnable code or an exact command.
- **Type consistency:** `aggregate_to_daily_series`/`aggregate_to_period_settlement_value` signatures introduced in Task 2 are used identically (same param name `hourly_spreads`, same return shape) in Tasks 4 and 5; `settlement-history`/`settlement-leaderboard` route paths and response field names (`daily_series`, `rows`, `realized_value`, `live_eligible`) are used identically in the frontend tasks (6-8) that consume them.
