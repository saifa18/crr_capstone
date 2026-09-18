"""
Computes real, live Source/Sink congestion value from ERCOT's actual
Day-Ahead Market settlement point prices, fetched via ercot_live.py.

Why this is a legitimate stand-in for CRR value, not a hack:
A Point-To-Point (PTP) Obligation CRR from Source to Sink pays its holder
exactly (DAM_LMP[Sink] - DAM_LMP[Source]) per MWh, per hour. That is the
literal settlement formula in ERCOT protocol, not an approximation this
project invented. So the live DAM price spread between two real settlement
points *is* real, realized Obligation-CRR value -- just computed directly
from the live price feed instead of waited-for auction results. For a
trader, this is arguably the more useful number: it is available same-day
instead of once a month at auction, and it is what actually got realized on
the grid rather than what a competing bidder paid weeks or months earlier.

This module intentionally does NOT try to produce participant, MW-awarded,
or notional data -- the live Public API has no such endpoint (see
ercot_live.py's module docstring). Those fields stay sourced from real
auction CSVs or the synthetic demo generator (see ingestion.py). Records
this module produces are tagged crr_type="OBLIGATION" (an accurate
description of the payoff being measured), participant=LIVE_PARTICIPANT_TAG,
and awarded_mw=0.0 as an explicit sentinel meaning "no award data available
from this source" -- callers must not treat that 0.0 as a real MW figure.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from .domain import TimeOfUse
from .ercot_live import ErcotApiClient

LIVE_PARTICIPANT_TAG = "(ERCOT live DAM -- no participant data)"

# ERCOT's own definition (from the Wholesale Markets 101 / CRR training
# material) of On-Peak hours is HE0700-HE2200 (hour-ending 7 through 22),
# Monday-Saturday, excluding NERC holidays; Off-Peak is all other hours.
# This module approximates that as weekday/Saturday HE07-HE22 without a
# holiday calendar -- close enough for descriptive analytics, but flag it
# if you need protocol-exact TOU bucketing (e.g. for actual settlement).
_ON_PEAK_HOURS = set(range(7, 23))  # hour-ending 7..22 inclusive


def _field(row: dict, *names: str) -> Any:
    """Case-insensitive lookup across possible ERCOT field-name casings."""
    lowered = {k.lower(): v for k, v in row.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    raise KeyError(f"None of {names} found in row with keys {list(row.keys())}")


def parse_api_rows(response: dict) -> list[dict]:
    """ERCOT's Public API returns a columnar shape:
        {"fields": [{"name": "deliveryDate"}, ...], "data": [[...], [...]], "_meta": {...}}
    Converts that into a list of plain dicts keyed by field name.
    """
    fields = [f["name"] for f in response.get("fields", [])]
    rows = response.get("data", [])
    return [dict(zip(fields, row)) for row in rows]


def total_pages(response: dict) -> int:
    return int(response.get("_meta", {}).get("totalPages", 1))


def classify_tou(delivery_date: str, hour_ending: int) -> str:
    """Approximate ERCOT On-Peak/Off-Peak classification (see module
    docstring for the exact-vs-approximate caveat)."""
    d = datetime.strptime(delivery_date[:10], "%Y-%m-%d").date()
    is_weekday = d.weekday() < 5  # Mon-Fri
    is_saturday = d.weekday() == 5
    on_peak_hour = hour_ending in _ON_PEAK_HOURS
    if on_peak_hour and is_weekday:
        return TimeOfUse.PEAK_WD.value
    if on_peak_hour and is_saturday:
        return TimeOfUse.PEAK_WE.value
    return TimeOfUse.OFF_PEAK.value


def fetch_settlement_point_hourly_prices(
    client: ErcotApiClient,
    settlement_point: str,
    date_from: str,
    date_to: str,
    max_pages: int = 50,
) -> list[dict]:
    """Fetches every page of real DAM settlement point prices for one point
    over a date range, normalized to {delivery_date, hour_ending, price}."""
    out: list[dict] = []
    page = 1
    while True:
        response = client.get_dam_settlement_point_prices(
            settlement_point=settlement_point,
            delivery_date_from=date_from,
            delivery_date_to=date_to,
            page=page,
        )
        for row in parse_api_rows(response):
            out.append(
                {
                    "delivery_date": str(_field(row, "deliveryDate", "DeliveryDate"))[:10],
                    "hour_ending": int(float(_field(row, "hourEnding", "HourEnding"))),
                    "price": float(_field(row, "settlementPointPrice", "SettlementPointPrice")),
                }
            )
        pages = total_pages(response)
        if page >= pages or page >= max_pages:
            break
        page += 1
    return out


def compute_spread_records(
    source_prices: list[dict],
    sink_prices: list[dict],
    source: str,
    sink: str,
) -> list[dict]:
    """Joins Source and Sink hourly price rows on (delivery_date,
    hour_ending) and computes the hourly spread = Sink price - Source
    price -- the real, live Obligation-CRR payoff per MWh for that hour."""
    by_key_source = {(r["delivery_date"], r["hour_ending"]): r["price"] for r in source_prices}
    by_key_sink = {(r["delivery_date"], r["hour_ending"]): r["price"] for r in sink_prices}
    common_keys = sorted(set(by_key_source) & set(by_key_sink))

    out = []
    for delivery_date, hour_ending in common_keys:
        spread = by_key_sink[(delivery_date, hour_ending)] - by_key_source[(delivery_date, hour_ending)]
        out.append(
            {
                "delivery_date": delivery_date,
                "hour_ending": hour_ending,
                "spread": spread,
                "time_of_use": classify_tou(delivery_date, hour_ending),
            }
        )
    return out


def aggregate_to_monthly_records(hourly_spreads: list[dict], source: str, sink: str) -> list[dict]:
    """Averages hourly spreads into (auction_month, time_of_use) buckets and
    emits records in the exact same shape analytics.py/scoring.py already
    consume -- so the tested, pure analytics/scoring functions apply to live
    data with zero changes."""
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in hourly_spreads:
        month = row["delivery_date"][:7]  # "YYYY-MM"
        buckets[(month, row["time_of_use"])].append(row["spread"])

    out = []
    for (month, tou), spreads in sorted(buckets.items()):
        avg = sum(spreads) / len(spreads)
        out.append(
            {
                "auction_month": month,
                "source": source,
                "sink": sink,
                "crr_type": "OBLIGATION",
                "time_of_use": tou,
                "clearing_price": round(avg, 2),
                "awarded_mw": 0.0,  # sentinel: no award data from this source, see module docstring
                "participant": LIVE_PARTICIPANT_TAG,
                "is_synthetic": False,
                "source_system": "ercot_live_dam_spp",
            }
        )
    return out


def fetch_live_pair_records(
    client: ErcotApiClient,
    source: str,
    sink: str,
    date_from: str,
    date_to: str,
) -> list[dict]:
    """End-to-end: real DAM prices for both settlement points -> hourly
    spread -> monthly/TOU-aggregated records ready for analytics.py."""
    source_prices = fetch_settlement_point_hourly_prices(client, source, date_from, date_to)
    sink_prices = fetch_settlement_point_hourly_prices(client, sink, date_from, date_to)
    hourly = compute_spread_records(source_prices, sink_prices, source, sink)
    return aggregate_to_monthly_records(hourly, source, sink)
