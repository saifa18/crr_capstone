"""
Shared, cached data-loading layer for the Streamlit app.

Imports the tested backend/app/*.py modules directly (no HTTP hop) -- this
is what makes the Streamlit app a single process that works the moment the
whole project folder is copied/zipped elsewhere, with no second server to
boot. Uses the same sys.path pattern as backend/scripts/export_snapshot.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app import analytics, domain, scoring, weather_zones  # noqa: E402
from app.ingestion import load_bulk_real_auction_data  # noqa: E402

TOP_N_PAIRS = 30


def _settlement_point_name(code: str) -> str:
    sp = domain.SP_BY_CODE.get(code)
    return sp.name if sp else code


@st.cache_data(ttl=3600, show_spinner="Loading CRR auction dataset...")
def get_dataset() -> tuple[list[dict], str, str | None]:
    return load_bulk_real_auction_data()


@st.cache_data(ttl=3600)
def get_tracked_records() -> tuple[list[dict], list[dict]]:
    """Returns (records_for_tracked_pairs, top_pairs) -- every downstream
    view works off this filtered set so a handful of one-off resource-node
    trades don't drown out the pairs that actually have recurring
    activity. See analytics.discover_top_pairs."""
    records, _source, _warning = get_dataset()
    top_pairs = analytics.discover_top_pairs(records, n=TOP_N_PAIRS)
    tracked_keys = {(p["source"], p["sink"]) for p in top_pairs}
    tracked_records = [r for r in records if (r["source"], r["sink"]) in tracked_keys]
    return tracked_records, top_pairs


@st.cache_data(ttl=3600)
def get_scores() -> list[dict]:
    tracked_records, _ = get_tracked_records()
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


@st.cache_data(ttl=3600)
def get_hot_paths(n: int = 10) -> list[dict]:
    records, _source, _warning = get_dataset()
    return analytics.top_paths(records, months_back=12, n=n)


@st.cache_data(ttl=3600)
def get_participants() -> list[dict]:
    tracked_records, _ = get_tracked_records()
    return analytics.participant_summary(tracked_records)


@st.cache_data(ttl=3600)
def get_participant_strategy(name: str) -> dict:
    records, _source, _warning = get_dataset()
    participant_records = [r for r in records if r["participant"] == name]
    return analytics.participant_strategy(name, participant_records)


@st.cache_data(ttl=3600)
def get_weather_zone_snapshot() -> list[dict]:
    return weather_zones.current_conditions_by_zone()


@st.cache_data(ttl=86400)
def get_weather_zone_seasonality() -> dict[str, list[dict] | None]:
    return weather_zones.trailing_12mo_seasonality_by_zone()


def _settlement_point_coordinates() -> dict[str, tuple[float, float]]:
    """Borrows each real hub/load-zone code's map location from the
    weather zone it's associated with in weather_zones.py -- there's no
    separate lat/lon table to maintain, and it stays consistent with
    whatever zone mapping that module already documents."""
    coords: dict[str, tuple[float, float]] = {}
    for zone in weather_zones.WEATHER_ZONES:
        for code in zone.hubs + zone.load_zones:
            coords.setdefault(code, (zone.latitude, zone.longitude))
    return coords


@st.cache_data(ttl=3600)
def get_corridor_map_points() -> list[dict]:
    """One row per real hub/load-zone code appearing in the tracked top
    pairs, with a map location and how many tracked pairs touch that
    point. Points with no known coordinate (e.g. a resource-node code with
    no weather-zone mapping) are omitted entirely rather than plotted at
    (0, 0), which would be misleading."""
    _, top_pairs = get_tracked_records()
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
