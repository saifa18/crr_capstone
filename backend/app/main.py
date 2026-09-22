from __future__ import annotations

import csv
import io
import re
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
from .live_congestion import (
    aggregate_prices_to_daily,
    aggregate_to_daily_series,
    aggregate_to_period_settlement_value,
    compute_spread_records,
    fetch_live_pair_records,
    fetch_settlement_point_hourly_prices,
    summarize_settlement_series,
)
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
    auction_months = sorted({r["auction_month"] for r in records})
    return {
        "record_count": len(records),
        "data_source": source,
        "data_source_warning": warning,
        "months_covered": auction_months[:1] + auction_months[-1:],
        # Every distinct real auction_month present in the data, oldest
        # first -- lets the Participants page build a data-aware "auction
        # period" filter (exact YYYY-MM options) instead of a hardcoded
        # Jan-Dec list that would be ambiguous once the data spans more
        # than one calendar year for the same month name.
        "auction_months": auction_months,
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
def pair_participants(source: str, sink: str, crr_type: str | None = Query(None)):
    """Every participant with activity on this specific Source/Sink pair,
    ranked by notional -- lets a trader see who else is active on a path
    without leaving the pair they're looking at. Optional crr_type filter
    (OBLIGATION/OPTION) narrows this to just that instrument type -- a real
    field already present on every record, not an invented one."""
    records = _records()
    pair_recs = analytics.filter_records(records, source=source, sink=sink, crr_type=crr_type)
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


def _filter_by_auction_period(records: list[dict], period: str | None) -> list[dict]:
    """Filters records by auction_month per `period`:
    - None/"all" (default): every record, unfiltered.
    - "ytd": auction_month falls in the same calendar year as the LATEST
      auction_month present in the full dataset -- this is auction data,
      not wall-clock activity, so "year to date" means this dataset's own
      most recent year, not the real-world current year.
    - an exact "YYYY-MM" string: only that auction month.
    Raises HTTPException(422) for anything else, rather than silently
    matching nothing."""
    if not period or period == "all":
        return records
    if period == "ytd":
        all_months = sorted({r["auction_month"] for r in _records()})
        if not all_months:
            return records
        latest_year = all_months[-1][:4]
        return [r for r in records if r["auction_month"].startswith(latest_year)]
    if re.fullmatch(r"\d{4}-\d{2}", period):
        return [r for r in records if r["auction_month"] == period]
    raise HTTPException(422, "period must be 'all', 'ytd', or an exact 'YYYY-MM' auction month")


def _paginate_activity(filtered: list[dict], page: int, page_size: int) -> dict:
    """True server-side pagination over an already-filtered record set --
    filters (participant, auction period, path) are always applied BEFORE
    this, never after, so page 1 of a filtered view is page 1 of exactly
    that filtered set, not a slice of the unfiltered "all time, all paths"
    list. Sort is deterministic and stable (auction_month, source, sink,
    all descending) so a record never jumps between pages across requests
    for the same filters. An out-of-range `page` yields an empty `items`
    list rather than an error, so a stale page number after a filter
    change degrades safely."""
    total = len(filtered)
    total_pages = (total + page_size - 1) // page_size if total else 0
    ordered = sorted(filtered, key=lambda r: (r["auction_month"], r["source"], r["sink"]), reverse=True)
    start = (page - 1) * page_size
    return {
        "items": ordered[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }


@app.get("/api/participants/{name}")
def participant_detail(
    name: str,
    period: str | None = Query(None, description="'all' (default), 'ytd', or an exact 'YYYY-MM' auction month"),
    source: str | None = Query(None, description="Optional: scope to just this path's source (requires sink too)"),
    sink: str | None = Query(None, description="Optional: scope to just this path's sink (requires source too)"),
    crr_type: str | None = Query(None, description="Optional: 'OBLIGATION' or 'OPTION' -- strict, applied before pagination"),
    page: int = Query(1, ge=1, description="Certificate page number, 1-indexed"),
    page_size: int = Query(25, ge=1, le=500, description="Certificates per page"),
):
    """Everything about one participant, optionally scoped to an auction
    period, a specific path, and/or a CRR type: the summary metrics (net
    MW, notional, distinct paths, certificate count) and the
    certificate/activity page are ALL computed from the SAME filtered
    record set, so changing a filter changes every number on the page
    consistently -- never a certificate table that's filtered while the
    summary above it silently stays unfiltered. `crr_type` is matched by
    strict equality against the real `crr_type` field on each record
    (normalized to uppercase so 'obligation'/'Obligation'/'OBLIGATION' all
    match the same way) -- an Option record is never returned when
    OBLIGATION is requested, and vice versa. Filtering (participant,
    period, path, type) always happens BEFORE pagination, never after, so
    `total`/`total_pages` on `recent_activity` reflect the fully filtered
    set, not a slice of the unfiltered one. `recent_activity` is
    server-side paginated ({items, page, page_size, total, total_pages})
    so a participant with thousands of certificates never has all of them
    serialized/sent for one page. This does not touch the separate,
    live-ERCOT-settlement "Path settlement value" feature
    (settlement-leaderboard), which has its own month selector over a
    different data source (real-time SPP, not auction awards) -- the two
    are deliberately independent, not silently linked."""
    if crr_type:
        crr_type = crr_type.upper()
        if crr_type not in ("OBLIGATION", "OPTION"):
            raise HTTPException(422, "crr_type must be 'OBLIGATION' or 'OPTION'")

    records = [r for r in _records() if r["participant"] == name]
    if not records:
        raise HTTPException(404, "Unknown participant")

    if source and sink:
        records = analytics.filter_records(records, source=source, sink=sink)
    if crr_type:
        records = analytics.filter_records(records, crr_type=crr_type)

    filtered = _filter_by_auction_period(records, period)
    if not filtered:
        return {
            "participant": name,
            "period": period or "all",
            "crr_type": crr_type,
            "summary": {
                "participant": name, "total_awarded_mw": 0.0, "total_notional": 0.0,
                "distinct_pairs": 0, "auction_count": 0,
            },
            "pairs": [],
            "recent_activity": {"items": [], "page": page, "page_size": page_size, "total": 0, "total_pages": 0},
        }
    return {
        "participant": name,
        "period": period or "all",
        "crr_type": crr_type,
        "summary": analytics.participant_summary(filtered)[0],
        "pairs": [
            {"source": s, "sink": k} for s, k in analytics.all_pairs(filtered)
        ],
        "recent_activity": _paginate_activity(filtered, page, page_size),
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
    """The Overview page's data. Does NOT include an opportunity-tier
    distribution or top-scored-pairs list -- those were computed here
    through v1.x for an earlier Streamlit dashboard chart that the React
    rebuild never ported over, confirmed unused by any current frontend
    page before removing. The opportunity score itself is not gone: it's
    still real, tested, and used as Path Settlements' demoted secondary
    signal (see /api/opportunity-scores and Signals.jsx's `legacyScore`)."""
    records = _records()
    _, source, warning = _get_data()
    tracked_records, top_pairs = _tracked()
    months = sorted({r["auction_month"] for r in records})
    latest_month = months[-1] if months else None
    latest_recs = [r for r in records if r["auction_month"] == latest_month]

    top_participants = analytics.participant_summary(tracked_records)[:5]

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
        "monthly_mw_trend": monthly_mw_trend,
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


@_ttl_cache(900)
def _cached_node_hourly_prices(settlement_point: str, date_from: str, date_to: str) -> list[dict]:
    """Real DAM hourly settlement point prices for ONE node, cached 15
    minutes per (node, date_from, date_to). Every settlement-price feature
    below (path detail, the bulk summary powering every path's mini
    sparkline, the participant leaderboard) calls this instead of
    ercot_live directly -- when many tracked paths share a node (HB_WEST
    alone appears in 6+ of the 30 tracked corridors), this means ERCOT is
    only actually called once per node per cache window, not once per
    path. A raised ErcotApiError is never cached (see _ttl_cache), so a
    transient ERCOT failure doesn't get stuck."""
    client = _get_live_client()
    return fetch_settlement_point_hourly_prices(client, settlement_point, date_from, date_to)


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


def _require_real_nonsynthetic_pair(source: str, sink: str) -> None:
    """The ONLY pre-flight gate a Path Settlements corridor has to pass: it
    must be backed by this project's real, non-synthetic CRR auction
    records. This replaced a static hub/load-zone name whitelist
    (SP_BY_CODE / is_live_api_eligible) that incorrectly excluded real
    ERCOT resource-node corridors -- confirmed live: MERCURY_ALL,
    RAMBLER_UNIT, B_DAVIS_3, TORR_ALL, PENA_ALL, and others all returned
    real hourly DAM settlement point prices from ERCOT's actual API, and
    were wrongly labeled "illustrative synthetic" purely because they
    weren't in that small curated dict, not because they aren't real. Real
    ERCOT-ness is not name-inferred here or anywhere below -- it's
    established by (a) this check, that the pair's records are genuinely
    non-synthetic, and (b) actually querying ERCOT's live API and
    requiring real data back (see the 404s below, which fire only when
    ERCOT itself returns nothing -- never a fabricated substitute)."""
    pair_recs = analytics.filter_records(_records(), source=source, sink=sink)
    if not pair_recs:
        raise HTTPException(404, f"No real ERCOT CRR auction record found for {source}/{sink}")
    if any(r.get("is_synthetic") for r in pair_recs):
        raise HTTPException(
            422,
            f"{source}/{sink} is backed by this project's synthetic demo data "
            "(the bundled real ERCOT dataset is unavailable and the app has fallen back to "
            "the demo generator -- see /api/system/status), not real ERCOT records, so it's "
            "excluded from live Path Settlements.",
        )


def _resolve_ytd_date_range(date_from: str | None, date_to: str | None) -> tuple[date, date]:
    """Shared default for every settlement-price feature: January 1st of
    the current year through today, per the explicit "just go back to
    January 1st" guidance -- capped at 400 days so a wide explicit range
    still degrades to a bounded number of ERCOT API calls rather than
    hanging or exhausting the live API's rate limit."""
    resolved_date_to = date.fromisoformat(date_to) if date_to else date.today()
    resolved_date_from = (
        date.fromisoformat(date_from) if date_from else date(resolved_date_to.year, 1, 1)
    )
    if (resolved_date_to - resolved_date_from).days > 400:
        resolved_date_from = resolved_date_to - timedelta(days=400)
    return resolved_date_from, resolved_date_to


def _fetch_pair_hourly_settlement(source: str, sink: str, date_from: str, date_to: str) -> list[dict]:
    """Real hourly Obligation/Option settlement rows for one Source/Sink
    pair over a date range, built on top of _cached_node_hourly_prices so
    that any node shared by multiple tracked paths (HB_WEST, say, appears
    in 6+ of the 30 tracked corridors) is only ever fetched from ERCOT
    once per 15-minute cache window, no matter how many paths use it --
    the single place every settlement endpoint below should go through
    rather than calling ercot_live directly."""
    try:
        source_prices = _cached_node_hourly_prices(source, date_from, date_to)
        sink_prices = _cached_node_hourly_prices(sink, date_from, date_to)
    except ErcotApiError as e:
        raise HTTPException(502, str(e))
    return compute_spread_records(source_prices, sink_prices, source, sink)


@app.get("/api/pairs/{source}/{sink}/settlement-history")
def settlement_history(
    source: str,
    sink: str,
    date_from: str | None = Query(None, description="YYYY-MM-DD, defaults to Jan 1 of the current year"),
    date_to: str | None = Query(None, description="YYYY-MM-DD, defaults to today"),
):
    """Real, live day-by-day Source/Sink settlement-price history for the
    Path Detail View: a time series of the *real settlement point price*
    spread (not the CRR auction bid price shown in
    opportunity-scores/pair_series), with both the Obligation payoff (raw
    spread, can be negative) and Option payoff (floored at zero) shown
    side by side, plus each node's own raw daily price series (for the
    "Source SPP vs Sink SPP" toggle view) and latest/average/min/max
    summary stats for both instrument types."""
    _require_live_api()
    _require_real_nonsynthetic_pair(source, sink)

    resolved_date_from, resolved_date_to = _resolve_ytd_date_range(date_from, date_to)
    date_from_iso, date_to_iso = resolved_date_from.isoformat(), resolved_date_to.isoformat()

    try:
        source_prices = _cached_node_hourly_prices(source, date_from_iso, date_to_iso)
        sink_prices = _cached_node_hourly_prices(sink, date_from_iso, date_to_iso)
    except ErcotApiError as e:
        raise HTTPException(502, str(e))

    hourly = compute_spread_records(source_prices, sink_prices, source, sink)
    if not hourly:
        raise HTTPException(
            404,
            f"ERCOT returned no live DAM settlement point price data for {source} and/or "
            f"{sink} in the requested window. This can happen for a retired/very new "
            "settlement point or during an ERCOT API outage -- try a narrower date range. "
            "No fallback or fabricated data is substituted.",
        )

    return {
        "source": source,
        "sink": sink,
        "source_name": _settlement_point_name(source),
        "sink_name": _settlement_point_name(sink),
        "data_source": "ercot_live_dam_spp",
        "date_from": date_from_iso,
        "date_to": date_to_iso,
        "daily_series": aggregate_to_daily_series(hourly),
        "source_daily": aggregate_prices_to_daily(source_prices),
        "sink_daily": aggregate_prices_to_daily(sink_prices),
        "summary": summarize_settlement_series(hourly),
    }


@app.get("/api/pairs/settlement-summary")
def pairs_settlement_summary(
    date_from: str | None = Query(None, description="YYYY-MM-DD, defaults to Jan 1 of the current year"),
    date_to: str | None = Query(None, description="YYYY-MM-DD, defaults to today"),
):
    """Real settlement-price daily series + summary stats for EVERY
    tracked corridor backed by real, non-synthetic auction data, in one
    request -- this is what powers an always-visible mini settlement
    sparkline per path on the Path Settlements page without the browser
    making one request per path. Every node is fetched at most once via
    _cached_node_hourly_prices, then reused for however many tracked pairs
    share it.

    Eligibility is decided ONLY by (a) the pair coming from real
    non-synthetic CRR auction records, and (b) ERCOT's live API actually
    returning real hourly data for both nodes -- never by matching the
    settlement point's name against a static hub/load-zone whitelist. That
    whitelist approach was tried first and was wrong: real ERCOT resource
    nodes from the bundled auction data (e.g. MERCURY_ALL, RAMBLER_UNIT,
    B_DAVIS_3) all have real, live-queryable DAM settlement point prices
    (confirmed directly against ERCOT's API) despite not being hubs or
    load zones, so excluding them by name was a false negative, not a
    real synthetic-data problem. A pair only lands in `unavailable_pairs`
    now because it's genuinely backed by synthetic demo data, or because
    ERCOT's live API itself returned no data / errored for it -- reported
    honestly, never papered over with a fabricated number."""
    _require_live_api()
    resolved_date_from, resolved_date_to = _resolve_ytd_date_range(date_from, date_to)
    date_from_iso, date_to_iso = resolved_date_from.isoformat(), resolved_date_to.isoformat()

    _tracked_records, top_pairs = _tracked()

    node_prices: dict[str, list[dict]] = {}
    node_errors: dict[str, str] = {}

    def _node_prices(node: str) -> list[dict] | None:
        if node in node_prices:
            return node_prices[node]
        if node in node_errors:
            return None
        try:
            node_prices[node] = _cached_node_hourly_prices(node, date_from_iso, date_to_iso)
            return node_prices[node]
        except ErcotApiError as e:
            node_errors[node] = str(e)
            return None

    pairs_out = []
    unavailable = []
    for p in top_pairs:
        source, sink = p["source"], p["sink"]
        source_name, sink_name = _settlement_point_name(source), _settlement_point_name(sink)
        pair_recs = analytics.filter_records(_records(), source=source, sink=sink)

        if any(r.get("is_synthetic") for r in pair_recs):
            unavailable.append({
                "source": source, "sink": sink, "source_name": source_name, "sink_name": sink_name,
                "reason": "backed by this project's synthetic demo data, not real ERCOT records",
            })
            continue

        source_prices, sink_prices = _node_prices(source), _node_prices(sink)
        if source_prices is None or sink_prices is None:
            err = node_errors.get(source) or node_errors.get(sink)
            unavailable.append({
                "source": source, "sink": sink, "source_name": source_name, "sink_name": sink_name,
                "reason": f"ERCOT's live API returned an error for this corridor: {err}",
            })
            continue

        hourly = compute_spread_records(source_prices, sink_prices, source, sink)
        if not hourly:
            unavailable.append({
                "source": source, "sink": sink, "source_name": source_name, "sink_name": sink_name,
                "reason": "ERCOT returned no live settlement point price data for this corridor in this window",
            })
            continue

        pairs_out.append(
            {
                "source": source,
                "sink": sink,
                "source_name": source_name,
                "sink_name": sink_name,
                "daily_series": aggregate_to_daily_series(hourly),
                "summary": summarize_settlement_series(hourly),
            }
        )

    return {
        "data_source": "ercot_live_dam_spp",
        "date_from": date_from_iso,
        "date_to": date_to_iso,
        "pairs": pairs_out,
        "unavailable_pairs": unavailable,
    }


def _parse_auction_month_range(auction_month: str) -> tuple[str, str]:
    """Validates 'YYYY-MM' and returns the (first day, last day) ISO dates
    of that month -- shared by the single-corridor and bulk settlement
    leaderboard endpoints so the format check and month-boundary math
    exist in exactly one place."""
    try:
        year, month_num = auction_month.split("-")
        month_start = date(int(year), int(month_num), 1)
    except (ValueError, IndexError):
        raise HTTPException(422, "auction_month must be in YYYY-MM format")
    month_end = (date(month_start.year + (month_start.month == 12), (month_start.month % 12) + 1, 1)
                 - timedelta(days=1))
    return month_start.isoformat(), month_end.isoformat()


def _settlement_leaderboard_rows(source: str, sink: str, auction_month: str) -> list[dict]:
    """Real winners-and-losers rows for one corridor/month: joins each
    participant's already-known awarded_mw (from the real CRR auction
    records) against the real settlement value per MW for that exact
    (month, time_of_use) bucket -- i.e. literally the by-hand calculation
    walked through in the 2026-09-21 feedback call (sink SPP minus source
    SPP, summed over the hours held, times MW). Obligation awards are
    valued off the raw (possibly negative) spread sum; Option awards off
    the floored-at-zero spread sum, matching ERCOT's actual CRR payoff
    rules for each type. `settlement_value` is labeled "settlement value,"
    not "profit" -- acquisition cost/fees aren't in this dataset, see the
    module docstring in live_congestion.py. Shared by the single-corridor
    endpoint and the cross-corridor bulk endpoint below -- the settlement
    math itself is not duplicated between them."""
    month_start_iso, month_end_iso = _parse_auction_month_range(auction_month)
    hourly = _fetch_pair_hourly_settlement(source, sink, month_start_iso, month_end_iso)
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
                "source": source,
                "sink": sink,
                "crr_type": r["crr_type"],
                "time_of_use": r["time_of_use"],
                "awarded_mw": r["awarded_mw"],
                "settlement_value_per_mw": round(per_mw, 4),
                # Path Settlement Value: awarded MW x real settlement $/MW for
                # this exact month/TOU bucket. Deliberately NOT called "profit"
                # -- this dataset has no acquisition cost/fees, so it's the CRR
                # settlement value only, not total realized trading P&L.
                "settlement_value": round(r["awarded_mw"] * per_mw, 2),
            }
        )
    return rows


@app.get("/api/pairs/{source}/{sink}/settlement-leaderboard")
def settlement_leaderboard(source: str, sink: str, auction_month: str = Query(..., description="YYYY-MM")):
    """Real winners-and-losers board for one corridor/month -- see
    _settlement_leaderboard_rows for the settlement math itself."""
    _require_live_api()
    _require_real_nonsynthetic_pair(source, sink)

    rows = _settlement_leaderboard_rows(source, sink, auction_month)
    rows.sort(key=lambda row: row["settlement_value"], reverse=True)

    return {
        "source": source,
        "sink": sink,
        "auction_month": auction_month,
        "data_source": "ercot_live_dam_spp",
        "rows": rows,
    }


@app.get("/api/settlement-leaderboard")
def settlement_leaderboard_bulk(
    auction_month: str = Query(..., description="YYYY-MM"),
    source: str | None = Query(None, description="Optional: scope to one path's source (requires sink too)"),
    sink: str | None = Query(None, description="Optional: scope to one path's sink (requires source too)"),
    participant: str | None = Query(None, description="Optional: exact participant name -- narrows to just their rows"),
    crr_type: str | None = Query(None, description="Optional: 'OBLIGATION' or 'OPTION' -- strict, applied before pagination"),
    page: int = Query(1, ge=1, description="Result page number, 1-indexed"),
    page_size: int = Query(25, ge=1, le=500, description="Rows per page"),
):
    """Cross-corridor version of the settlement leaderboard above: 'who
    settled what, on which path' across every tracked corridor at once
    (or one specific corridor, if source+sink are given), optionally
    narrowed to one participant and/or one CRR type. This is what powers
    the Participants page's "Path settlement value by participant"
    section once it isn't scoped to a single pre-selected path -- e.g.
    "show me everyone active on HB_WEST -> LZ_WEST" (source+sink given, no
    participant) or "show me this one participant across every path they
    hold this month" (participant given, no source/sink).

    Every filter (participant, path, CRR type) is applied to the full
    cross-corridor row set BEFORE pagination, so `total`/`total_pages`
    always reflect the fully filtered result -- the same contract as
    /api/participants/{name}'s recent_activity pagination, not a slice of
    an unfiltered page. Rows are sorted by settlement_value descending
    (highest winners first) before slicing into a page, so a row never
    jumps pages across requests for the same filters.

    Uses the exact same real, live ERCOT settlement math as the
    single-corridor endpoint (see _settlement_leaderboard_rows) -- this is
    a fan-out over corridors, not a different calculation. A corridor
    genuinely backed by synthetic demo data, or one ERCOT's live API
    errors/returns nothing for, is skipped and reported in
    `unavailable_pairs` (same honest-degrade pattern as
    /api/pairs/settlement-summary), never silently zeroed or substituted."""
    _require_live_api()

    if (source is None) != (sink is None):
        raise HTTPException(422, "source and sink must be given together")

    if crr_type:
        crr_type = crr_type.upper()
        if crr_type not in ("OBLIGATION", "OPTION"):
            raise HTTPException(422, "crr_type must be 'OBLIGATION' or 'OPTION'")

    # Fail fast on a malformed month before touching ERCOT for any pair.
    _parse_auction_month_range(auction_month)

    if source and sink:
        _require_real_nonsynthetic_pair(source, sink)
        candidate_pairs = [{"source": source, "sink": sink}]
    else:
        _tracked_records, top_pairs = _tracked()
        candidate_pairs = [{"source": p["source"], "sink": p["sink"]} for p in top_pairs]

    all_rows: list[dict] = []
    unavailable: list[dict] = []
    for p in candidate_pairs:
        s, k = p["source"], p["sink"]
        pair_recs = analytics.filter_records(_records(), source=s, sink=k)
        if any(r.get("is_synthetic") for r in pair_recs):
            unavailable.append({
                "source": s, "sink": k,
                "reason": "backed by this project's synthetic demo data, not real ERCOT records",
            })
            continue
        try:
            all_rows.extend(_settlement_leaderboard_rows(s, k, auction_month))
        except HTTPException as e:
            if e.status_code != 502:
                raise
            unavailable.append({"source": s, "sink": k, "reason": str(e.detail)})
            continue

    if participant:
        all_rows = [r for r in all_rows if r["participant"] == participant]
    if crr_type:
        all_rows = [r for r in all_rows if r["crr_type"] == crr_type]

    all_rows.sort(key=lambda row: row["settlement_value"], reverse=True)

    total = len(all_rows)
    total_pages = (total + page_size - 1) // page_size if total else 0
    start = (page - 1) * page_size

    return {
        "auction_month": auction_month,
        "data_source": "ercot_live_dam_spp",
        "source": source,
        "sink": sink,
        "participant": participant,
        "crr_type": crr_type,
        "items": all_rows[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "unavailable_pairs": unavailable,
    }


@_ttl_cache(900)
def _binding_constraints_cached(date_from: str, date_to: str) -> tuple[list[dict], bool]:
    """The actual ERCOT-calling work, memoized 15 minutes per (date_from,
    date_to) pair -- matches the Streamlit app's identical ttl=900 on
    get_binding_constraints. Kept out of the route function itself so the
    cache decorator never has to touch FastAPI's Query(...) signature
    inspection. A raised ErcotApiError is never cached (see _ttl_cache),
    so a transient failure -- like the real HTTP 429 this project hit
    during review -- doesn't get stuck; the next request retries clean.

    Two real data-quality issues in ERCOT's raw NP4-191-CD rows, confirmed
    by inspecting a live, credentialed response directly (not assumed):
    (1) `hourEnding` is a zero-padded "HH:00" string (e.g. "24:00"), the
    exact same shape already discovered and fixed for the DAM settlement-
    point-price endpoint (see live_congestion._parse_hour_ending) -- this
    endpoint just hadn't been updated to use that same parser yet, so the
    UI was showing the raw "24:00" string as "Hour" instead of a plain
    hour number. (2) every string field (`constraintName`,
    `contingencyName`, `fromStation`, `toStation`) comes back with leading
    whitespace baked in (e.g. " 6437__F", "  BASE CASE") -- ERCOT's own
    fixed-width-style text formatting, not anything this project's parsing
    introduced. Both are normalized here, once, at the source, rather than
    leaving every consumer (dropdown de-dup, table cells, sort/filter) to
    each work around raw ERCOT formatting independently."""
    from .live_congestion import _parse_hour_ending, parse_api_rows, total_pages

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

    def _clean_str(v) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    constraints = [
        {
            "delivery_date": str(r.get("deliveryDate", ""))[:10],
            "hour_ending": _parse_hour_ending(r["hourEnding"]) if r.get("hourEnding") is not None else None,
            "constraint_name": _clean_str(r.get("constraintName")),
            "contingency_name": _clean_str(r.get("contingencyName")),
            "shadow_price": r.get("shadowPrice"),
            "from_station": _clean_str(r.get("fromStation")),
            "to_station": _clean_str(r.get("toStation")),
        }
        for r in raw_rows
    ]
    constraints.sort(key=lambda c: (c["delivery_date"], c["hour_ending"] or 0), reverse=True)
    return constraints, truncated


def _summarize_constraints(constraints: list[dict], top_n: int = 5) -> list[dict]:
    """Ranks constraints by how many hourly intervals they were reported
    binding in, within whatever window `constraints` covers -- the exact
    logic the frontend's `summarize()` used to run client-side over the
    full unpaginated list, ported here so it stays correct (and possible
    at all) once the table itself is paginated server-side. Independent of
    the current constraint-name filter or page -- always ranks the
    full window, matching the existing "Most active constraints" panel's
    job of surfacing the worst offenders regardless of what's currently
    selected below it."""
    by_name: dict[str, dict] = {}
    for c in constraints:
        name = c["constraint_name"] or "—"
        entry = by_name.setdefault(name, {"name": name, "count": 0, "max_shadow": 0.0})
        entry["count"] += 1
        mag = abs(c["shadow_price"] or 0)
        if mag > entry["max_shadow"]:
            entry["max_shadow"] = mag
    ranked = sorted(by_name.values(), key=lambda e: e["count"], reverse=True)
    return ranked[:top_n]


_CONSTRAINT_SORT_KEYS = {
    "delivery_date", "hour_ending", "constraint_name", "contingency_name", "from_station", "shadow_price",
}


def _sort_constraints(constraints: list[dict], sort_key: str, sort_dir: str) -> list[dict]:
    reverse = sort_dir == "desc"
    if sort_key == "from_station":
        key_fn = lambda c: (c["from_station"] or "", c["to_station"] or "")
    elif sort_key in ("constraint_name", "contingency_name", "delivery_date"):
        key_fn = lambda c: c[sort_key] or ""
    else:
        key_fn = lambda c: c[sort_key] if c[sort_key] is not None else 0
    return sorted(constraints, key=key_fn, reverse=reverse)


@app.get("/api/live/binding-constraints")
def live_binding_constraints(
    date_from: str = Query(..., description="YYYY-MM-DD"),
    date_to: str = Query(..., description="YYYY-MM-DD"),
    constraint_name: str | None = Query(None, description="Optional: exact constraint_name, applied before pagination"),
    sort_key: str = Query("delivery_date", description="One of: " + ", ".join(sorted(_CONSTRAINT_SORT_KEYS))),
    sort_dir: str = Query("desc", description="'asc' or 'desc'"),
    page: int = Query(1, ge=1, description="Page number, 1-indexed"),
    page_size: int = Query(25, ge=1, le=500, description="Rows per page"),
):
    """Real, live binding transmission constraints (DAM shadow prices) for
    the given window -- the actual named element(s) causing congestion,
    straight from ERCOT. This is the real "why" behind a congested path,
    not a statistical inference. Paginates through ERCOT's response and
    shapes each row into the same named, snake_case fields as the
    Streamlit app's identical lib/data_loader.get_binding_constraints, so
    both frontends see the exact same contract -- capped at 15 ERCOT pages
    (~15,000 rows) fetched per window so a wide window degrades to a
    truncated-but-fast result instead of a very slow one.

    `items` is server-side paginated (25/page by default) over the FULL
    window's constraints -- `constraint_name` is applied to that full set
    BEFORE pagination (never paginate-then-filter), and `total`/
    `total_pages` reflect the fully filtered count. `constraint_options`
    (every distinct real constraint_name in the window) and `summary`
    (top 5 most active) are both computed from the full, unfiltered
    window too, independent of the current page/filter/sort -- the
    constraint search dropdown must never be limited to whatever page
    happens to be loaded.

    No severity/tier classification is computed or returned here --
    this endpoint reports the real shadow price for each row and lets
    that number speak for itself, rather than layering an arbitrary
    High/Medium/Low bucketing on top of it."""
    if sort_key not in _CONSTRAINT_SORT_KEYS:
        raise HTTPException(422, f"sort_key must be one of: {', '.join(sorted(_CONSTRAINT_SORT_KEYS))}")
    if sort_dir not in ("asc", "desc"):
        raise HTTPException(422, "sort_dir must be 'asc' or 'desc'")
    _require_live_api()

    try:
        constraints, truncated = _binding_constraints_cached(date_from, date_to)
    except ErcotApiError as e:
        raise HTTPException(502, str(e))

    constraint_options = sorted({c["constraint_name"] for c in constraints if c["constraint_name"]})
    summary = _summarize_constraints(constraints)

    filtered = constraints
    if constraint_name:
        filtered = [c for c in filtered if c["constraint_name"] == constraint_name]

    ordered = _sort_constraints(filtered, sort_key, sort_dir)
    total = len(ordered)
    total_pages = (total + page_size - 1) // page_size if total else 0
    start = (page - 1) * page_size

    return {
        "date_from": date_from,
        "date_to": date_to,
        "truncated": truncated,
        "items": ordered[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "constraint_options": constraint_options,
        "summary": summary,
    }
