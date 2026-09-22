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


def compute_obligation_settlement(source_price: float | None, sink_price: float | None) -> float:
    """The real CRR Obligation settlement formula, per ERCOT protocol and
    exactly as walked through in the 2026-09-21 feedback call: sink price
    minus source price. Can be negative (the holder owes ERCOT that hour).

    Raises ValueError on a missing price rather than silently treating it
    as zero -- a missing SPP is missing information, not a real $0 outcome,
    and must never be conflated with an interval that genuinely settled at
    zero. Callers that need to skip missing intervals (e.g. joining two
    real price series where an hour is absent from one side) must do that
    filtering explicitly before calling this -- see compute_spread_records.
    """
    if source_price is None or sink_price is None:
        raise ValueError(
            "Cannot compute a CRR settlement value with a missing settlement point "
            "price -- treating a missing price as $0 would misrepresent what "
            "actually happened on the grid."
        )
    return sink_price - source_price


def compute_option_settlement(source_price: float | None, sink_price: float | None) -> float:
    """The real CRR Option settlement formula: the Obligation payoff floored
    at zero. An Option holder never owes money, per ERCOT's actual CRR
    payoff rules -- they simply receive nothing in a negative-spread hour
    rather than being 'made whole' or owing the difference."""
    return max(compute_obligation_settlement(source_price, sink_price), 0.0)


def fetch_settlement_point_hourly_prices(
    client: ErcotApiClient,
    settlement_point: str,
    date_from: str,
    date_to: str,
    max_pages: int = 50,
) -> list[dict]:
    """Fetches every page of real DAM settlement point prices for one point
    over a date range, normalized to {delivery_date, hour_ending, price}.

    A row whose settlementPointPrice comes back null/missing from ERCOT is
    skipped entirely (never coerced to 0.0 or crashed on) -- a genuinely
    missing interval must stay absent from the series, not be misread as a
    real $0 settlement."""
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
            raw_price = _field(row, "settlementPointPrice", "SettlementPointPrice")
            if raw_price is None:
                continue
            out.append(
                {
                    "delivery_date": str(_field(row, "deliveryDate", "DeliveryDate"))[:10],
                    "hour_ending": _parse_hour_ending(_field(row, "hourEnding", "HourEnding")),
                    "price": float(raw_price),
                }
            )
        pages = total_pages(response)
        if page >= pages or page >= max_pages:
            break
        page += 1
    return out


def aggregate_prices_to_daily(hourly_prices: list[dict]) -> list[dict]:
    """Averages one settlement point's own hourly prices (not a spread) into
    one row per calendar day -- {"date", "price"} -- the raw per-node series
    behind the Path Detail View's "Source SPP vs Sink SPP" toggle."""
    by_day: dict[str, list[float]] = defaultdict(list)
    for row in hourly_prices:
        by_day[row["delivery_date"]].append(row["price"])
    return [
        {"date": day, "price": round(sum(prices) / len(prices), 3)}
        for day, prices in sorted(by_day.items())
    ]


def compute_spread_records(
    source_prices: list[dict],
    sink_prices: list[dict],
    source: str,
    sink: str,
) -> list[dict]:
    """Joins Source and Sink hourly price rows on (delivery_date,
    hour_ending) -- an hour present on only one side is dropped rather than
    treated as a $0 price on the missing side (see module-level formulas
    above) -- and computes, for each matched hour, the real Obligation and
    Option settlement payoffs per MWh."""
    by_key_source = {(r["delivery_date"], r["hour_ending"]): r["price"] for r in source_prices}
    by_key_sink = {(r["delivery_date"], r["hour_ending"]): r["price"] for r in sink_prices}
    common_keys = sorted(set(by_key_source) & set(by_key_sink))

    out = []
    for delivery_date, hour_ending in common_keys:
        source_price = by_key_source[(delivery_date, hour_ending)]
        sink_price = by_key_sink[(delivery_date, hour_ending)]
        out.append(
            {
                "delivery_date": delivery_date,
                "hour_ending": hour_ending,
                "source_price": source_price,
                "sink_price": sink_price,
                "spread": compute_obligation_settlement(source_price, sink_price),
                "option_settlement": compute_option_settlement(source_price, sink_price),
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


def aggregate_to_daily_series(hourly_spreads: list[dict]) -> list[dict]:
    """Averages hourly Source/Sink settlement payoffs into one row per
    calendar day, for charting a real settlement-price history -- Obligation
    is the raw average spread (can be negative: the holder owes ERCOT that
    hour); Option is the average of the already-floored option_settlement
    per hour (an Option holder never owes money, per ERCOT's actual CRR
    settlement rules)."""
    by_day: dict[str, list[dict]] = defaultdict(list)
    for row in hourly_spreads:
        by_day[row["delivery_date"]].append(row)

    out = []
    for day in sorted(by_day):
        rows = by_day[day]
        out.append(
            {
                "date": day,
                "obligation_price": round(sum(r["spread"] for r in rows) / len(rows), 3),
                "option_price": round(sum(r["option_settlement"] for r in rows) / len(rows), 3),
            }
        )
    return out


def summarize_settlement_series(hourly_spreads: list[dict]) -> dict:
    """Latest/average/min/max Obligation and Option settlement value over a
    hourly series -- the headline stats for the Path Detail View's "if I
    owned this path, how did it perform" question. `latest_*` is the most
    recent single delivery hour in the series, not a daily average, so it
    answers "right now" as precisely as the data allows."""
    if not hourly_spreads:
        return {
            "obligation": {"latest": None, "average": None, "min": None, "max": None},
            "option": {"latest": None, "average": None, "min": None, "max": None},
        }
    ordered = sorted(hourly_spreads, key=lambda r: (r["delivery_date"], r["hour_ending"]))
    obligations = [r["spread"] for r in ordered]
    options = [r["option_settlement"] for r in ordered]
    return {
        "obligation": {
            "latest": round(obligations[-1], 3),
            "average": round(sum(obligations) / len(obligations), 3),
            "min": round(min(obligations), 3),
            "max": round(max(obligations), 3),
        },
        "option": {
            "latest": round(options[-1], 3),
            "average": round(sum(options) / len(options), 3),
            "min": round(min(options), 3),
            "max": round(max(options), 3),
        },
    }


def aggregate_to_period_settlement_value(hourly_spreads: list[dict]) -> list[dict]:
    """Sums (not averages) hourly Source/Sink settlement payoffs into one
    row per (auction_month, time_of_use) bucket -- this is the real
    $/MW-held value a CRR of that type would have realized across every
    hour in that bucket, i.e. exactly the number to multiply by a
    participant's awarded_mw to get their real settlement $ for that month
    (Obligation pays sink-source every hour including negative hours;
    Option only pays the positive hours, per the module docstring above)."""
    by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in hourly_spreads:
        month = row["delivery_date"][:7]
        by_key[(month, row["time_of_use"])].append(row)

    out = []
    for (month, tou), rows in sorted(by_key.items()):
        out.append(
            {
                "auction_month": month,
                "time_of_use": tou,
                "obligation_value_per_mw": round(sum(r["spread"] for r in rows), 3),
                "option_value_per_mw": round(sum(r["option_settlement"] for r in rows), 3),
                "hours": len(rows),
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
