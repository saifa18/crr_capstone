from __future__ import annotations

import csv
import io
from datetime import date, timedelta
from functools import lru_cache

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

from . import analytics, scoring, db, ingestion
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


@lru_cache(maxsize=1)
def _get_data():
    records, source, warning = load_records()
    return records, source, warning


def _records():
    records, _, _ = _get_data()
    return records


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
    records = _records()
    out = []
    for source, sink in analytics.all_pairs(records):
        pair_recs = analytics.filter_records(records, source=source, sink=sink)
        m = analytics.basic_metrics([r for r in pair_recs if r["crr_type"] == "OBLIGATION"])
        out.append({
            "source": source,
            "source_name": SP_BY_CODE[source].name,
            "sink": sink,
            "sink_name": SP_BY_CODE[sink].name,
            "average_obligation_price": m["average"],
            "trend_direction": m["trend_direction"],
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
    if source not in SP_BY_CODE or sink not in SP_BY_CODE:
        raise HTTPException(404, "Unknown settlement point")
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
    if source not in SP_BY_CODE or sink not in SP_BY_CODE:
        raise HTTPException(404, "Unknown settlement point")
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
    return analytics.participant_summary(_records())


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
    records = _records()
    scores = scoring.score_all_pairs(records)
    return [
        {
            "source": s.source,
            "source_name": SP_BY_CODE[s.source].name,
            "sink": s.sink,
            "sink_name": SP_BY_CODE[s.sink].name,
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
    months = sorted({r["auction_month"] for r in records})
    latest_month = months[-1] if months else None
    latest_recs = [r for r in records if r["auction_month"] == latest_month]

    all_scores = scoring.score_all_pairs(records)
    top_scores = all_scores[:5]
    top_participants = analytics.participant_summary(records)[:5]

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
        "tracked_pair_count": len(analytics.all_pairs(records)),
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


@app.get("/api/live/binding-constraints")
def live_binding_constraints(
    date_from: str = Query(..., description="YYYY-MM-DD"),
    date_to: str = Query(..., description="YYYY-MM-DD"),
):
    """Real, live binding transmission constraints (DAM shadow prices) for
    the given window -- the actual named element(s) causing congestion,
    straight from ERCOT. This is the real "why" behind a congested path,
    not a statistical inference."""
    _require_live_api()
    try:
        client = _get_live_client()
        response = client.get_dam_shadow_prices(date_from, date_to)
    except ErcotApiError as e:
        raise HTTPException(502, str(e))

    from .live_congestion import parse_api_rows

    rows = parse_api_rows(response)
    return {"date_from": date_from, "date_to": date_to, "constraints": rows}
