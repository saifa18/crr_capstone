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


def discover_top_pairs(records: list[dict], n: int = 30) -> list[dict]:
    """
    Ranks every distinct Source/Sink pair present in `records` by total
    notional (gross MW-weighted dollar activity) and returns the top `n`,
    with participant count and a recurring-congestion signal. This
    replaces a fixed, hand-curated pair list with whatever the data itself
    says is actually active -- essential once real ERCOT auction data
    brings in thousands of one-off resource-node pairs alongside the
    liquid hub/load-zone corridors.

    Notional uses abs(awarded_mw) so a participant's netted BUY/SELL
    position (see ingestion.py) doesn't understate how much gross activity
    actually happened on a path -- a path with heavy two-way trading is
    "hot" even if positions mostly cancel out.

    "recurring_months" counts, out of the pair's own trailing 12 auction
    months, how many cleared with the same sign (positive/negative) as the
    pair's all-time average -- the same directional-consistency idea
    scoring.py already uses per-pair, exposed here as a plain count rather
    than a 0-100 score.

    Real ERCOT data has ~95,000 distinct Source/Sink pairs (confirmed
    against the real bundled dataset) -- a naive "for each pair, re-scan
    all records" approach is O(pairs x records) and does not finish in
    reasonable time at that scale. This does one O(records) pass, building
    a per-pair aggregate as it goes, then ranks and slices.
    """
    by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for r in records:
        key = (r["source"], r["sink"])
        agg = by_pair.get(key)
        if agg is None:
            agg = {"notional": 0.0, "participants": set(), "monthly_prices": defaultdict(list)}
            by_pair[key] = agg
        agg["notional"] += abs(r["awarded_mw"]) * abs(r["clearing_price"])
        agg["participants"].add(r["participant"])
        agg["monthly_prices"][r["auction_month"]].append(r["clearing_price"])

    ranked = []
    for (source, sink), agg in by_pair.items():
        months_sorted = sorted(agg["monthly_prices"])
        prices = [statistics.mean(agg["monthly_prices"][m]) for m in months_sorted]
        recurring_months = 0
        if prices:
            avg = statistics.mean(prices)
            sign = 1 if avg >= 0 else -1
            trailing = prices[-12:]
            recurring_months = sum(1 for p in trailing if (p >= 0) == (sign >= 0))
        ranked.append({
            "source": source,
            "sink": sink,
            "total_notional": round(agg["notional"], 2),
            "participant_count": len(agg["participants"]),
            "recurring_months": recurring_months,
            "months_tracked": len(prices),
        })
    ranked.sort(key=lambda p: p["total_notional"], reverse=True)
    return ranked[:n]


def top_paths(records: list[dict], months_back: int = 12, n: int = 10) -> list[dict]:
    """
    Thin, UI-facing wrapper around discover_top_pairs: the "Hot Paths"
    panel's data, each with a one-line, plain-language reason -- answers
    "what are the top sourcing paths people are looking at" directly.
    """
    top = discover_top_pairs(records, n=n)
    out = []
    for p in top:
        reason = (
            f"Congested the same direction in {p['recurring_months']} of its last "
            f"{min(p['months_tracked'], months_back)} months, "
            f"{p['participant_count']} active participants."
        )
        out.append({**p, "reason": reason})
    return out


def participant_strategy(participant_name: str, records: list[dict]) -> dict:
    """
    Per-participant strategy breakdown for one CRR Account Holder: how many
    certificates, Option vs. Obligation mix, net Buy/Sell position, how
    much of their activity is pre-existing (PREAWARD) vs. freshly won in
    the standard monthly auction, and their top corridors by notional.
    Answers "who's doing what" / "what's their strategy" directly rather
    than requiring a trader to page through raw rows.
    """
    n = len(records)
    if n == 0:
        return {
            "participant": participant_name,
            "certificate_count": 0,
            "option_pct": None,
            "obligation_pct": None,
            "net_mw": 0.0,
            "preaward_pct": None,
            "top_pairs": [],
        }

    option_count = sum(1 for r in records if r["crr_type"] == "OPTION")
    obligation_count = n - option_count
    net_mw = sum(r["awarded_mw"] for r in records)
    preaward_count = sum(1 for r in records if r.get("award_type", "STANDARD") == "PREAWARD")

    by_pair: dict[tuple[str, str], float] = defaultdict(float)
    for r in records:
        by_pair[(r["source"], r["sink"])] += abs(r["awarded_mw"]) * abs(r["clearing_price"])
    top_pairs = sorted(
        ({"source": s, "sink": k, "notional": round(v, 2)} for (s, k), v in by_pair.items()),
        key=lambda d: d["notional"],
        reverse=True,
    )[:5]

    return {
        "participant": participant_name,
        "certificate_count": n,
        "option_pct": round(100 * option_count / n, 1),
        "obligation_pct": round(100 * obligation_count / n, 1),
        "net_mw": round(net_mw, 1),
        "preaward_pct": round(100 * preaward_count / n, 1),
        "top_pairs": top_pairs,
    }
