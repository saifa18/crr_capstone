"""
Explainable Opportunity Score for a Source/Sink CRR pair.

Design goal (per project scope): "market intelligence and analytics rather
than predicting trading outcomes." This is a transparent, rule-based
composite score over historical descriptive statistics -- NOT a predictive
ML model, and NOT a recommendation to bid. Every sub-factor is computed
from `analytics.py` outputs and is shown to the user alongside the score,
so the score is fully auditable ("why did this pair score High?").

Factors (0-100 each), weighted:
  1. Value level (35%)      -- how large is the average historical
                                congestion value on this path (normalized
                                against the full pair universe)?
  2. Trend (20%)             -- is realized value rising, flat, or falling
                                (recent 12mo vs prior 12mo)?
  3. Consistency (25%)       -- what share of months cleared with the same
                                sign as the historical average (i.e. how
                                directionally reliable has the path been)?
  4. Liquidity/participation (20%) -- how many distinct participants and
                                how much MW has actually cleared on this
                                path (thin/no-bid paths are flagged, not
                                rewarded, since a signal nobody else is
                                acting on deserves more scrutiny, not less).

Bucketing: score >= 70 -> High, 40-69 -> Medium, < 40 -> Low.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from . import analytics


@dataclass
class OpportunityScore:
    source: str
    sink: str
    score: float
    tier: str
    factors: dict[str, dict[str, Any]] = field(default_factory=dict)
    explanation: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _value_score(avg_abs_price: float, universe_max_abs_avg: float) -> float:
    if universe_max_abs_avg <= 0:
        return 0.0
    return _clamp(100 * avg_abs_price / universe_max_abs_avg)


def _trend_score(recent_vs_prior_year_pct: float | None, direction: str) -> float:
    if recent_vs_prior_year_pct is None:
        return 50.0  # not enough history -- neutral, flagged in explanation
    # Map a +/-50% swing to the 0-100 range, centered at 50.
    return _clamp(50 + recent_vs_prior_year_pct)


def _consistency_score(monthly_prices: list[float]) -> float:
    if not monthly_prices:
        return 0.0
    avg = statistics.mean(monthly_prices)
    sign = 1 if avg >= 0 else -1
    same_sign = sum(1 for p in monthly_prices if (p >= 0) == (sign >= 0))
    return _clamp(100 * same_sign / len(monthly_prices))


def _liquidity_score(distinct_participants: int, total_mw: float,
                      max_participants_universe: int, max_mw_universe: float) -> float:
    if max_participants_universe <= 0 or max_mw_universe <= 0:
        return 0.0
    p_score = 100 * distinct_participants / max_participants_universe
    mw_score = 100 * total_mw / max_mw_universe
    return _clamp((p_score + mw_score) / 2)


def _tier_for(score: float) -> str:
    if score >= 70:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"


def score_all_pairs(records: list[dict]) -> list[OpportunityScore]:
    """
    Score every Source/Sink pair present in `records` using OBLIGATION,
    all-time-of-use records as the economic-value signal (Obligation CRRs
    directly mirror realized congestion value; Options are priced off the
    same congestion but compressed by optionality, so Obligation is the
    cleaner signal for "how much has this path actually been worth").
    """
    pairs = analytics.all_pairs(records)
    obligation_records = [r for r in records if r["crr_type"] == "OBLIGATION"]

    per_pair_stats = []
    for source, sink in pairs:
        pair_recs = analytics.filter_records(obligation_records, source=source, sink=sink)
        metrics = analytics.basic_metrics(pair_recs)
        pstats = analytics.participant_summary(pair_recs)
        series = analytics.monthly_price_series(pair_recs)
        per_pair_stats.append(
            {
                "source": source,
                "sink": sink,
                "metrics": metrics,
                "distinct_participants": len(pstats),
                "total_mw": sum(p["total_awarded_mw"] for p in pstats),
                "monthly_prices": [m["avg_clearing_price"] for m in series],
            }
        )

    universe_max_abs_avg = max(
        (abs(p["metrics"]["average"]) for p in per_pair_stats if p["metrics"]["average"] is not None),
        default=1.0,
    )
    universe_max_participants = max((p["distinct_participants"] for p in per_pair_stats), default=1)
    universe_max_mw = max((p["total_mw"] for p in per_pair_stats), default=1.0)

    results = []
    for p in per_pair_stats:
        m = p["metrics"]
        if m["average"] is None:
            continue

        value_s = _value_score(abs(m["average"]), universe_max_abs_avg)
        trend_s = _trend_score(m["recent_vs_prior_year_pct"], m["trend_direction"])
        consistency_s = _consistency_score(p["monthly_prices"])
        liquidity_s = _liquidity_score(
            p["distinct_participants"], p["total_mw"], universe_max_participants, universe_max_mw
        )

        weights = {"value": 0.35, "trend": 0.20, "consistency": 0.25, "liquidity": 0.20}
        composite = (
            weights["value"] * value_s
            + weights["trend"] * trend_s
            + weights["consistency"] * consistency_s
            + weights["liquidity"] * liquidity_s
        )
        composite = round(composite, 1)
        tier = _tier_for(composite)

        explanation = []
        explanation.append(
            f"Average historical congestion value of ${m['average']}/MWh "
            f"ranks this path at {round(value_s)}/100 on value versus all tracked pairs."
        )
        if m["recent_vs_prior_year_pct"] is not None:
            explanation.append(
                f"Value is {m['trend_direction']} -- last 12 months vs. prior 12 months "
                f"changed {m['recent_vs_prior_year_pct']}%."
            )
        else:
            explanation.append("Not enough history yet for a reliable year-over-year trend read.")
        explanation.append(
            f"{round(consistency_s)}% of months cleared on the same side (positive/negative) "
            f"as the historical average, indicating {'high' if consistency_s >= 70 else 'moderate' if consistency_s >= 40 else 'low'} "
            f"directional consistency."
        )
        explanation.append(
            f"{p['distinct_participants']} distinct participants and "
            f"{round(p['total_mw'])} MW have cleared on this path historically "
            f"({'well-established' if liquidity_s >= 60 else 'thin' if liquidity_s < 30 else 'moderate'} liquidity)."
        )

        results.append(
            OpportunityScore(
                source=p["source"],
                sink=p["sink"],
                score=composite,
                tier=tier,
                factors={
                    "value": {"score": round(value_s, 1), "weight": weights["value"]},
                    "trend": {"score": round(trend_s, 1), "weight": weights["trend"]},
                    "consistency": {"score": round(consistency_s, 1), "weight": weights["consistency"]},
                    "liquidity": {"score": round(liquidity_s, 1), "weight": weights["liquidity"]},
                },
                explanation=explanation,
                metrics=m,
            )
        )

    results.sort(key=lambda r: r.score, reverse=True)
    return results
