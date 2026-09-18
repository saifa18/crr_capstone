import pytest

from app import scoring


def _rec(month, price, mw, source, sink, participant, crr_type="OBLIGATION", tou="PEAK_WD"):
    return {
        "auction_month": month,
        "source": source,
        "sink": sink,
        "crr_type": crr_type,
        "time_of_use": tou,
        "clearing_price": price,
        "awarded_mw": mw,
        "participant": participant,
    }


def _months(n, start_year=2023, start_month=1):
    out = []
    y, m = start_year, start_month
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def test_score_all_pairs_ranks_strong_pair_above_weak_pair():
    strong_months = _months(24)
    weak_months = _months(24)

    records = []
    # Strong pair: high, rising, consistent, liquid
    for i, mo in enumerate(strong_months):
        price = 5.0 + i * 0.3  # clearly rising
        for p_idx, participant in enumerate(["P1", "P2", "P3", "P4"]):
            records.append(_rec(mo, price + p_idx * 0.1, 40.0, "STRONG_SRC", "STRONG_SINK", participant))

    # Weak pair: low, flat/falling, inconsistent, thin
    for i, mo in enumerate(weak_months):
        price = 0.5 if i % 2 == 0 else -0.5  # flips sign -> inconsistent, near zero -> low value
        records.append(_rec(mo, price, 2.0, "WEAK_SRC", "WEAK_SINK", "P1"))

    results = scoring.score_all_pairs(records)
    by_pair = {(r.source, r.sink): r for r in results}

    strong = by_pair[("STRONG_SRC", "STRONG_SINK")]
    weak = by_pair[("WEAK_SRC", "WEAK_SINK")]

    assert strong.score > weak.score
    assert strong.tier in ("High", "Medium")
    assert weak.tier in ("Low", "Medium")
    # results are sorted descending by score
    assert results[0].score == max(r.score for r in results)


def test_every_score_has_explanation_and_valid_tier():
    records = []
    for i, mo in enumerate(_months(6)):
        records.append(_rec(mo, 3.0 + i, 15.0, "A", "B", "P1"))
    results = scoring.score_all_pairs(records)
    assert len(results) == 1
    r = results[0]
    assert r.tier in ("Low", "Medium", "High")
    assert len(r.explanation) >= 3
    assert 0 <= r.score <= 100
    assert set(r.factors.keys()) == {"value", "trend", "consistency", "liquidity"}
    weight_sum = sum(f["weight"] for f in r.factors.values())
    assert weight_sum == pytest.approx(1.0)


def test_score_all_pairs_empty_input():
    assert scoring.score_all_pairs([]) == []


def test_scoring_ignores_option_records_for_value_signal():
    # Only OPTION records present for a pair -> no OBLIGATION metrics -> excluded
    records = [_rec("2024-01", 100.0, 10.0, "A", "B", "P1", crr_type="OPTION")]
    results = scoring.score_all_pairs(records)
    assert results == []
