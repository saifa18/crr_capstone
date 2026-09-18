"""
Pure, side-effect-free analytics functions over CRR auction records.

Every function takes plain dicts/lists (no ORM/DB coupling) so it can be
unit tested trivially and reused identically by the FastAPI layer and by
any offline notebook/analysis.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Any


def _month_key(rec: dict) -> str:
    return rec["auction_month"]


def filter_records(
    records: list[dict],
    source: str | None = None,
    sink: str | None = None,
    crr_type: str | None = None,
    time_of_use: str | None = None,
) -> list[dict]:
    out = records
    if source is not None:
        out = [r for r in out if r["source"] == source]
    if sink is not None:
        out = [r for r in out if r["sink"] == sink]
    if crr_type is not None:
        out = [r for r in out if r["crr_type"] == crr_type]
    if time_of_use is not None:
        out = [r for r in out if r["time_of_use"] == time_of_use]
    return out


def monthly_price_series(records: list[dict]) -> list[dict]:
    """
    Collapse a (possibly multi-TOU/multi-type) set of records into one
    average-clearing-price-per-month series, sorted chronologically.
    """
    by_month: dict[str, list[float]] = defaultdict(list)
    for r in records:
        by_month[_month_key(r)].append(r["clearing_price"])
    months = sorted(by_month.keys())
    return [
        {"auction_month": m, "avg_clearing_price": round(statistics.mean(by_month[m]), 3)}
        for m in months
    ]


def linear_trend_slope(series: list[float]) -> float:
    """
    Ordinary-least-squares slope of series vs. its index (0..n-1).
    Returns 0.0 for fewer than 2 points. Units: value change per month.
    """
    n = len(series)
    if n < 2:
        return 0.0
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(series) / n
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, series))
    den = sum((x - x_mean) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return num / den


def basic_metrics(records: list[dict]) -> dict[str, Any]:
    """
    Average, min, max, volatility (population std-dev of the monthly
    series), and trend (slope + direction + % change recent-vs-prior-year)
    for a Source/Sink (or any filtered) slice of records.
    """
    series = monthly_price_series(records)
    prices = [m["avg_clearing_price"] for m in series]

    if not prices:
        return {
            "n_months": 0,
            "average": None,
            "min": None,
            "max": None,
            "volatility": None,
            "trend_slope_per_month": None,
            "trend_direction": "flat",
            "recent_vs_prior_year_pct": None,
            "pct_months_negative": None,
            "trailing_12mo_average": None,
        }

    average = round(statistics.mean(prices), 3)
    minimum = round(min(prices), 3)
    maximum = round(max(prices), 3)
    volatility = round(statistics.pstdev(prices), 3) if len(prices) > 1 else 0.0
    slope = linear_trend_slope(prices)

    # Downside-risk signal: what share of months would have cost an
    # Obligation holder money (negative realized value)? An average that
    # looks attractive can still hide frequent negative months -- this
    # surfaces that directly rather than requiring the reader to infer it
    # from volatility alone.
    pct_months_negative = round(100 * sum(1 for p in prices if p < 0) / len(prices), 1)

    # A multi-year all-time average is close to useless for a forward
    # trading decision -- weight recency by also surfacing the trailing
    # 12-month average (or the full window's average if there's less than
    # 12 months of history) as its own first-class figure, not just the
    # all-time number with a YoY percentage attached.
    trailing_window = prices[-12:]
    trailing_12mo_average = round(statistics.mean(trailing_window), 3)

    if abs(slope) < 0.01 * (abs(average) + 1e-6):
        direction = "flat"
    elif slope > 0:
        direction = "rising"
    else:
        direction = "falling"

    recent_vs_prior_year_pct = None
    if len(prices) >= 24:
        recent_12 = statistics.mean(prices[-12:])
        prior_12 = statistics.mean(prices[-24:-12])
        if prior_12 != 0:
            recent_vs_prior_year_pct = round(100 * (recent_12 - prior_12) / abs(prior_12), 1)

    return {
        "n_months": len(prices),
        "average": average,
        "min": minimum,
        "max": maximum,
        "volatility": volatility,
        "trend_slope_per_month": round(slope, 4),
        "trend_direction": direction,
        "recent_vs_prior_year_pct": recent_vs_prior_year_pct,
        "pct_months_negative": pct_months_negative,
        "trailing_12mo_average": trailing_12mo_average,
    }


def participant_summary(records: list[dict]) -> list[dict]:
    """
    Aggregate awarded MW, spend, and distinct pair count per participant
    (CRR Account Holder), sorted by total notional descending.
    """
    agg: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"awarded_mw": 0.0, "notional": 0.0, "pairs": set(), "auctions": 0}
    )
    for r in records:
        a = agg[r["participant"]]
        a["awarded_mw"] += r["awarded_mw"]
        a["notional"] += r["awarded_mw"] * r["clearing_price"]
        a["pairs"].add((r["source"], r["sink"]))
        a["auctions"] += 1

    out = []
    for name, a in agg.items():
        out.append(
            {
                "participant": name,
                "total_awarded_mw": round(a["awarded_mw"], 1),
                "total_notional": round(a["notional"], 2),
                "distinct_pairs": len(a["pairs"]),
                "auction_count": a["auctions"],
            }
        )
    out.sort(key=lambda d: d["total_notional"], reverse=True)
    return out


def all_pairs(records: list[dict]) -> list[tuple[str, str]]:
    seen = []
    s = set()
    for r in records:
        key = (r["source"], r["sink"])
        if key not in s:
            s.add(key)
            seen.append(key)
    return seen


def recent_auction_month(records: list[dict]) -> str | None:
    months = {r["auction_month"] for r in records}
    return max(months) if months else None
