from __future__ import annotations

import csv
import io
import time
from datetime import date, timedelta
from functools import lru_cache


def _ttl_cache(ttl_seconds: float):
    """Minimal TTL memoizer for functions that call a rate-limited external
    API (ERCOT's live Public API, Open-Meteo) -- lru_cache never expires,
    which is wrong for these, and both already have real, documented rate
    limits (see ercot_live.py). A failed call (a raised exception) is never
    cached, so a transient upstream error doesn't get stuck -- only real
    results are memoized."""
    def decorator(fn):
        cache: dict[tuple, tuple[float, object]] = {}

        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            now = time.monotonic()
            cached = cache.get(key)
            if cached is not None and now < cached[0]:
                return cached[1]
            value = fn(*args, **kwargs)
            cache[key] = (now + ttl_seconds, value)
            return value

        wrapper.cache_clear = cache.clear
        return wrapper

    return decorator

# Load backend/.env (if present) before anything else -- db.py, ercot_live.py,
# and ingestion.py all read connection/credential env vars, some at call
# time and some effectively at import time via module-level defaults, so
# this must run before those modules are imported. Safe no-op if no .env
# file exists (e.g. real environment variables were set another way).
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import analytics, scoring, db, ingestion, weather_zones
from .domain import SP_BY_CODE, is_live_api_eligible
from .ercot_live import ErcotApiClient, ErcotApiError
from .live_congestion import fetch_live_pair_records
from .ingestion import load_records

app = FastAPI(
    title="ERCOT CRR Market Analytics API",
    description=(
        "Prototype market-intelligence API for ERCOT Congestion Revenue "
        "Rights (CRR) markets: participant activity, Source/Sink pricing "
        "history, descriptive analytics, and an explainable opportunity "
        "signal. Analytics/market-intelligence tool only -- not trading "
        "advice, not a predictive model."
    ),
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


TOP_N_PAIRS = 30


def _settlement_point_name(code: str) -> str:
    """Real names for the curated hub/load-zone/node set this project
    already knows about; falls back to the raw settlement point code for
    the thousands of real ERCOT resource nodes the bulk MIS data brings in
    that aren't in that curated list -- never a KeyError, matching the
    Streamlit app's identical helper in lib/data_loader.py."""
    sp = SP_BY_CODE.get(code)
    return sp.name if sp else code


@lru_cache(maxsize=1)
def _get_data():
    """Real, bulk ERCOT MIS CRR auction data (the same data source and the
    same function the Streamlit app uses) joined against the real
    participant registry -- falls back to SQL/flat-CSV/synthetic tiers via
    ingestion.load_records() only if that bulk real data is unavailable.
    Keeps this API and the Streamlit app looking at identical data."""
    records, source, warning = ingestion.load_bulk_real_auction_data()
    return records, source, warning


def _records():
    records, _, _ = _get_data()
    return records


@lru_cache(maxsize=1)
def _tracked():
    """(tracked_records, top_pairs): the real dataset has ~95,000 distinct
    Source/Sink pairs, most of them one-off resource-node trades, so every
    pair-level view (corridor list, opportunity scores, participant
    summary) works off the top 30 by real notional activity instead --
    same restriction Streamlit's get_tracked_records() applies, and for
    the same reason (otherwise these endpoints return unusably large
    payloads and take far longer than a request should)."""
    records = _records()
    top_pairs = analytics.discover_top_pairs(records, n=TOP_N_PAIRS)
    tracked_keys = {(p["source"], p["sink"]) for p in top_pairs}
    tracked_records = [r for r in records if (r["source"], r["sink"]) in tracked_keys]
    return tracked_records, top_pairs


@app.get("/api/meta")
def meta():
    records, source, warning = _get_data()
    return {
        "record_count": len(records),
        "data_source": source,
        "data_source_warning": warning,
        "months_covered": sorted({r["auction_month"] for r in records})[:1] +
        sorted({r["auction_month"] for r in records})[-1:],
        "pair_count": len(analytics.all_pairs(records)),
        "participant_count": len({r["participant"] for r in records}),
    }


@app.get("/api/pairs")
def pairs():
    """The tracked corridor list (top 30 by real notional activity) used
    to populate the Explorer's corridor picker -- not every distinct pair
    in the raw dataset, see _tracked()'s docstring."""
    records = _records()
    _tracked_records, top_pairs = _tracked()
    out = []
    for p in top_pairs:
        source, sink = p["source"], p["sink"]
        pair_recs = analytics.filter_records(records, source=source, sink=sink)
        m = analytics.basic_metrics([r for r in pair_recs if r["crr_type"] == "OBLIGATION"])
        out.append({
            "source": source,
            "source_name": _settlement_point_name(source),
            "sink": sink,
            "sink_name": _settlement_point_name(sink),
            "average_obligation_price": m["average"],
            "trend_direction": m["trend_direction"],
            "total_notional": p["total_notional"],
            "participant_count": p["participant_count"],
        })
    return out


@app.get("/api/pairs/{source}/{sink}/series")
def pair_series(
    source: str,
    sink: str,
    crr_type: str | None = Query(None),
    time_of_use: str | None = Query(None),
    format: str | None = Query(None, description="Set to 'csv' to download the series as CSV"),
):
    records = _records()
    recs = analytics.filter_records(records, source=source, sink=sink,
                                     crr_type=crr_type, time_of_use=time_of_use)
    if not recs:
        raise HTTPException(404, "No records for this pair/filter combination")
    series = analytics.monthly_price_series(recs)

    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["auction_month", "avg_clearing_price"])
        for row in series:
            writer.writerow([row["auction_month"], row["avg_clearing_price"]])
        buf.seek(0)
        filename = f"{source}_{sink}_series.csv"
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return {
        "source": source,
        "sink": sink,
        "series": series,
        "metrics": analytics.basic_metrics(recs),
    }


@app.get("/api/pairs/{source}/{sink}/participants")
def pair_participants(source: str, sink: str):
    """Every participant with activity on this specific Source/Sink pair,
    ranked by notional -- lets a trader see who else is active on a path
    without leaving the pair they're looking at."""
    records = _records()
    pair_recs = analytics.filter_records(records, source=source, sink=sink)
    if not pair_recs:
        raise HTTPException(404, "No records for this pair")
    return {
        "source": source,
        "sink": sink,
        "participants": analytics.participant_summary(pair_recs),
    }


@app.get("/health")
def health():
    """Liveness/readiness probe -- returns immediately, does not touch
    ERCOT or the dataset, so it stays fast even if a data source is down."""
    return {"status": "ok"}


@app.get("/api/system/status")
def system_status():
    """Diagnostic endpoint: which data tier is actually serving requests
    right now, and whether SQL Server specifically is configured/reachable.
    Unlike /health (a fast liveness probe that deliberately never touches
    the dataset), this endpoint DOES touch it -- use this one to verify a
    SQL Server connection is actually working, not just that the process
    is up."""
    records, source, warning = _get_data()
    return {
        "active_data_source": source,
        "data_source_warning": warning,
        "record_count": len(records),
        "sql_configured": db.is_sql_configured(),
        "csv_files_present": bool(list(ingestion.RAW_DIR.glob("*.csv"))) if ingestion.RAW_DIR.exists() else False,
        "ercot_live_api_configured": ErcotApiClient.is_configured(),
    }


@app.get("/api/participants")
def participants():
    """Participants active on the tracked top-30 corridors -- matches the
    Streamlit Participants page, which applies the same restriction for
    the same reason (the raw dataset's ~95,000-pair long tail would
    otherwise drown out who's actually active where it matters)."""
    tracked_records, _ = _tracked()
    return analytics.participant_summary(tracked_records)


@app.get("/api/participants/{name}")
def participant_detail(name: str):
    records = [r for r in _records() if r["participant"] == name]
    if not records:
        raise HTTPException(404, "Unknown participant")
    return {
        "participant": name,
        "summary": analytics.participant_summary(records)[0],
        "pairs": [
            {"source": s, "sink": k} for s, k in analytics.all_pairs(records)
        ],
        "recent_activity": sorted(records, key=lambda r: r["auction_month"], reverse=True)[:25],
    }


@app.get("/api/opportunity-scores")
def opportunity_scores():
    """Scores the tracked top-30 corridors, not all ~95,000 real pairs --
    see _tracked()'s docstring."""
    tracked_records, _ = _tracked()
    scores = scoring.score_all_pairs(tracked_records)
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
        }
        for s in scores
    ]


@app.get("/api/dashboard")
def dashboard():
    records = _records()
    _, source, warning = _get_data()
    tracked_records, top_pairs = _tracked()
    months = sorted({r["auction_month"] for r in records})
    latest_month = months[-1] if months else None
    latest_recs = [r for r in records if r["auction_month"] == latest_month]

    all_scores = scoring.score_all_pairs(tracked_records)
    top_scores = all_scores[:5]
    top_participants = analytics.participant_summary(tracked_records)[:5]

    tier_distribution = {"High": 0, "Medium": 0, "Low": 0}
    for s in all_scores:
        tier_distribution[s.tier] = tier_distribution.get(s.tier, 0) + 1

    # Trailing-12-month total MW awarded across the whole tracked market --
    # a one-glance "is activity growing or shrinking" signal the dashboard
    # otherwise has no way to show (a single latest-month number alone
    # can't reveal a trend).
    trend_months = months[-12:]
    mw_by_month = {m: 0.0 for m in trend_months}
    for r in records:
        if r["auction_month"] in mw_by_month:
            mw_by_month[r["auction_month"]] += r["awarded_mw"]
    monthly_mw_trend = [{"auction_month": m, "total_mw": round(mw_by_month[m], 1)} for m in trend_months]

    return {
        "data_source": source,
        "data_source_warning": warning,
        "latest_auction_month": latest_month,
        "latest_month_mw_awarded": round(sum(r["awarded_mw"] for r in latest_recs), 1),
        "latest_month_participant_count": len({r["participant"] for r in latest_recs}),
        "active_participant_count": len({r["participant"] for r in records}),
        "tracked_pair_count": len(top_pairs),
        "tier_distribution": tier_distribution,
        "monthly_mw_trend": monthly_mw_trend,
        "top_opportunity_pairs": [
            {
                "source": s.source, "sink": s.sink, "score": s.score, "tier": s.tier,
            }
            for s in top_scores
        ],
        "top_participants": top_participants,
    }


@app.get("/api/hot-paths")
def hot_paths(n: int = Query(10, ge=1, le=30)):
    """The most active tracked corridors with a plain-language reason each
    -- same underlying ranking as /api/pairs and /api/dashboard, exposed
    on its own so the frontend can show it without pulling the whole
    dashboard payload."""
    records = _records()
    paths = analytics.top_paths(records, months_back=12, n=n)
    return [
        {**p, "source_name": _settlement_point_name(p["source"]), "sink_name": _settlement_point_name(p["sink"])}
        for p in paths
    ]


def _settlement_point_coordinates() -> dict[str, tuple[float, float]]:
    """Same borrowed-from-weather-zone lookup as the Streamlit app's
    identical helper in lib/data_loader.py -- there's no separate lat/lon
    table to maintain."""
    coords: dict[str, tuple[float, float]] = {}
    for zone in weather_zones.WEATHER_ZONES:
        for code in zone.hubs + zone.load_zones:
            coords.setdefault(code, (zone.latitude, zone.longitude))
    return coords


@app.get("/api/corridor-map")
def corridor_map():
    """One row per real hub/load-zone code appearing in the tracked top
    30 pairs, with a map location and how many tracked pairs touch that
    point. Points with no known coordinate (e.g. a resource-node code
    with no weather-zone mapping) are omitted rather than plotted at
    (0, 0), which would be misleading."""
    _tracked_records, top_pairs = _tracked()
    coords = _settlement_point_coordinates()
    counts: dict[str, int] = {}
    for p in top_pairs:
        for code in (p["source"], p["sink"]):
            counts[code] = counts.get(code, 0) + 1

    out = []
    for code, count in counts.items():
        if code not in coords:
            continue
        lat, lon = coords[code]
        out.append({
            "code": code,
            "name": _settlement_point_name(code),
            "lat": lat,
            "lon": lon,
            "pair_count": count,
        })
    return out


@_ttl_cache(3600)
def _weather_cached():
    return weather_zones.current_conditions_by_zone()


@app.get("/api/weather")
def weather():
    """Current conditions for the four real-world regions behind the
    tracked corridors -- context only, never a scoring input. Fails open
    per-zone (see weather_zones.py), so a partial Open-Meteo outage
    returns partial data with an explicit error per zone, not a 500.
    Cached for an hour (matches the Streamlit app's identical ttl=3600 on
    get_weather_zone_snapshot) -- weather doesn't change fast enough to
    justify hitting Open-Meteo on every page load."""
    return _weather_cached()


# ---------------------------------------------------------------------
# Live ERCOT Public API integration (api.ercot.com)
#
# Separate from everything above: these endpoints call ERCOT's real,
# live Day-Ahead Market data feed instead of the auction/synthetic
# dataset. They require free ERCOT API credentials (see README and
# ercot_live.py's module docstring for registration steps) -- when not
# configured, they return 501 with instructions rather than failing
# unhelpfully or silently falling back to fake data.
# ---------------------------------------------------------------------

_live_client: ErcotApiClient | None = None


def _get_live_client() -> ErcotApiClient:
    global _live_client
    if _live_client is None:
        _live_client = ErcotApiClient()
    return _live_client


def _require_live_api() -> None:
    if not ErcotApiClient.is_configured():
        raise HTTPException(
            501,
            "Live ERCOT data is not configured on this server. Register for free at "
            "https://apiexplorer.ercot.com/, subscribe to 'Public API' for a "
            "subscription key, then set ERCOT_API_USERNAME, ERCOT_API_PASSWORD, and "
            "ERCOT_API_SUBSCRIPTION_KEY as environment variables and restart the backend.",
        )


@app.get("/api/live/status")
def live_status():
    """Whether this server has live ERCOT API credentials configured. Does
    not itself call ERCOT (so it's always fast/free) -- actual credential
    validity is only verified on first real live call."""
    configured = ErcotApiClient.is_configured()
    return {
        "configured": configured,
        "message": (
            "Live ERCOT DAM data is configured and available."
            if configured
            else "Live ERCOT DAM data is not configured. Register for free at "
                 "https://apiexplorer.ercot.com/ -- see README for setup steps."
        ),
    }


@app.get("/api/pairs/{source}/{sink}/live-lmp-spread")
def live_lmp_spread(
    source: str,
    sink: str,
    months_back: int = Query(24, ge=1, le=60),
):
    """Real, live Source/Sink congestion value computed just now from
    ERCOT's actual Day-Ahead Market settlement point prices -- see
    live_congestion.py's module docstring for why this spread is a
    legitimate, live proxy for Obligation-CRR value. Requires live API
    credentials (see /api/live/status) and real ERCOT settlement point
    codes -- this project's illustrative synthetic resource-node pairs are
    not eligible (they don't resolve against ERCOT's live systems)."""
    _require_live_api()

    if source not in SP_BY_CODE or sink not in SP_BY_CODE:
        raise HTTPException(404, "Unknown settlement point")
    if not is_live_api_eligible(source, sink):
        raise HTTPException(
            422,
            f"{source} and/or {sink} are illustrative demo settlement points, not "
            "real ERCOT codes, so they can't be queried against the live API. "
            "Live data is available for real ERCOT hub and load-zone pairs.",
        )

    date_to = date.today()
    date_from = date_to - timedelta(days=months_back * 31)

    try:
        client = _get_live_client()
        records = fetch_live_pair_records(
            client, source, sink, date_from.isoformat(), date_to.isoformat()
        )
    except ErcotApiError as e:
        raise HTTPException(502, str(e))

    if not records:
        raise HTTPException(
            404,
            f"ERCOT returned no DAM price data for {source}/{sink} in the requested "
            "window. This can happen for very new settlement points or during an "
            "ERCOT API outage -- try a shorter months_back window.",
        )

    return {
        "source": source,
        "sink": sink,
        "data_source": "ercot_live_dam_spp",
        "series": analytics.monthly_price_series(records),
        "metrics": analytics.basic_metrics(records),
    }


@_ttl_cache(900)
def _binding_constraints_cached(date_from: str, date_to: str) -> tuple[list[dict], bool]:
    """The actual ERCOT-calling work, memoized 15 minutes per (date_from,
    date_to) pair -- matches the Streamlit app's identical ttl=900 on
    get_binding_constraints. Kept out of the route function itself so the
    cache decorator never has to touch FastAPI's Query(...) signature
    inspection. A raised ErcotApiError is never cached (see _ttl_cache),
    so a transient failure -- like the real HTTP 429 this project hit
    during review -- doesn't get stuck; the next request retries clean."""
    from .live_congestion import parse_api_rows, total_pages

    raw_rows: list[dict] = []
    truncated = False
    client = _get_live_client()
    page = 1
    max_pages = 15
    while True:
        response = client.get_dam_shadow_prices(date_from, date_to, page=page, size=1000)
        raw_rows.extend(parse_api_rows(response))
        pages = total_pages(response)
        if page >= pages or page >= max_pages:
            truncated = page < pages
            break
        page += 1

    constraints = [
        {
            "delivery_date": str(r.get("deliveryDate", ""))[:10],
            "hour_ending": r.get("hourEnding"),
            "constraint_name": r.get("constraintName"),
            "contingency_name": r.get("contingencyName"),
            "shadow_price": r.get("shadowPrice"),
            "from_station": r.get("fromStation"),
            "to_station": r.get("toStation"),
        }
        for r in raw_rows
    ]
    constraints.sort(key=lambda c: (c["delivery_date"], c["hour_ending"] or 0), reverse=True)
    return constraints, truncated


@app.get("/api/live/binding-constraints")
def live_binding_constraints(
    date_from: str = Query(..., description="YYYY-MM-DD"),
    date_to: str = Query(..., description="YYYY-MM-DD"),
):
    """Real, live binding transmission constraints (DAM shadow prices) for
    the given window -- the actual named element(s) causing congestion,
    straight from ERCOT. This is the real "why" behind a congested path,
    not a statistical inference. Paginates through ERCOT's response and
    shapes each row into the same named, snake_case fields as the
    Streamlit app's identical lib/data_loader.get_binding_constraints, so
    both frontends see the exact same contract -- capped at 15 pages
    (~15,000 rows) so a wide window degrades to a truncated-but-fast
    result instead of a very slow one."""
    _require_live_api()
    try:
        constraints, truncated = _binding_constraints_cached(date_from, date_to)
    except ErcotApiError as e:
        raise HTTPException(502, str(e))

    return {"date_from": date_from, "date_to": date_to, "constraints": constraints, "truncated": truncated}
