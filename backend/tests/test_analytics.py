import statistics

import pytest

from app import analytics


def _rec(month, price, mw=10.0, source="A", sink="B", crr_type="OBLIGATION", tou="PEAK_WD", participant="X"):
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


def test_filter_records_by_all_dimensions():
    recs = [
        _rec("2024-01", 1.0, source="A", sink="B", crr_type="OPTION", tou="PEAK_WD"),
        _rec("2024-01", 2.0, source="A", sink="B", crr_type="OBLIGATION", tou="OFF_PEAK"),
        _rec("2024-01", 3.0, source="C", sink="D", crr_type="OBLIGATION", tou="PEAK_WD"),
    ]
    out = analytics.filter_records(recs, source="A", sink="B", crr_type="OBLIGATION")
    assert len(out) == 1
    assert out[0]["clearing_price"] == 2.0


def test_monthly_price_series_averages_and_sorts():
    recs = [
        _rec("2024-02", 10.0),
        _rec("2024-01", 4.0),
        _rec("2024-01", 6.0),  # average with above -> 5.0 for Jan
    ]
    series = analytics.monthly_price_series(recs)
    assert [s["auction_month"] for s in series] == ["2024-01", "2024-02"]
    assert series[0]["avg_clearing_price"] == 5.0
    assert series[1]["avg_clearing_price"] == 10.0


def test_linear_trend_slope_rising_and_falling():
    assert analytics.linear_trend_slope([1, 2, 3, 4, 5]) == pytest.approx(1.0)
    assert analytics.linear_trend_slope([5, 4, 3, 2, 1]) == pytest.approx(-1.0)
    assert analytics.linear_trend_slope([]) == 0.0
    assert analytics.linear_trend_slope([7]) == 0.0
    # constant series -> zero slope
    assert analytics.linear_trend_slope([3, 3, 3, 3]) == pytest.approx(0.0)


def test_basic_metrics_average_min_max_volatility():
    recs = [_rec(f"2024-{m:02d}", price) for m, price in
            zip(range(1, 6), [2.0, 4.0, 6.0, 8.0, 10.0])]
    m = analytics.basic_metrics(recs)
    prices = [2.0, 4.0, 6.0, 8.0, 10.0]
    assert m["n_months"] == 5
    assert m["average"] == pytest.approx(statistics.mean(prices), abs=0.01)
    assert m["min"] == 2.0
    assert m["max"] == 10.0
    assert m["volatility"] == pytest.approx(statistics.pstdev(prices), abs=0.01)
    assert m["trend_direction"] == "rising"
    assert m["trend_slope_per_month"] > 0


def test_basic_metrics_empty_input_is_safe():
    m = analytics.basic_metrics([])
    assert m["n_months"] == 0
    assert m["average"] is None
    assert m["trend_direction"] == "flat"
    assert m["pct_months_negative"] is None
    assert m["trailing_12mo_average"] is None


def test_trailing_12mo_average_uses_last_12_months_only():
    # 18 months: first 6 at price 100 (should be excluded), last 12 at price 10
    recs = [_rec(f"2023-{m:02d}", 100.0) for m in range(1, 7)]
    recs += [_rec(f"2023-{m:02d}", 10.0) for m in range(7, 13)]
    recs += [_rec(f"2024-{m:02d}", 10.0) for m in range(1, 7)]
    m = analytics.basic_metrics(recs)
    assert m["trailing_12mo_average"] == pytest.approx(10.0)
    assert m["average"] != m["trailing_12mo_average"]  # all-time average pulled up by the 100s


def test_trailing_12mo_average_uses_full_window_when_under_12_months():
    recs = [_rec(f"2024-{m:02d}", price) for m, price in zip(range(1, 4), [2.0, 4.0, 6.0])]
    m = analytics.basic_metrics(recs)
    assert m["trailing_12mo_average"] == pytest.approx(4.0)  # mean of all 3 available months


def test_basic_metrics_pct_months_negative():
    recs = [_rec(f"2024-{m:02d}", price) for m, price in
            zip(range(1, 6), [10.0, -5.0, 3.0, -2.0, 8.0])]
    m = analytics.basic_metrics(recs)
    assert m["pct_months_negative"] == pytest.approx(40.0)  # 2 of 5 months negative

    all_positive = [_rec(f"2024-{m:02d}", 5.0) for m in range(1, 4)]
    assert analytics.basic_metrics(all_positive)["pct_months_negative"] == 0.0


def test_basic_metrics_flat_series_has_flat_trend():
    recs = [_rec(f"2024-{m:02d}", 5.0) for m in range(1, 7)]
    m = analytics.basic_metrics(recs)
    assert m["trend_direction"] == "flat"
    assert m["volatility"] == 0.0


def test_recent_vs_prior_year_requires_24_months():
    short_recs = [_rec(f"2024-{m:02d}", 5.0) for m in range(1, 13)]
    m = analytics.basic_metrics(short_recs)
    assert m["recent_vs_prior_year_pct"] is None

    months = []
    y, mo = 2023, 1
    for i in range(24):
        months.append(f"{y}-{mo:02d}")
        mo += 1
        if mo == 13:
            mo = 1
            y += 1
    # prior 12 months average 4.0, recent 12 months average 8.0 -> +100%
    prices = [4.0] * 12 + [8.0] * 12
    long_recs = [_rec(mm, p) for mm, p in zip(months, prices)]
    m2 = analytics.basic_metrics(long_recs)
    assert m2["recent_vs_prior_year_pct"] == pytest.approx(100.0, abs=0.5)


def test_participant_summary_aggregates_correctly():
    recs = [
        _rec("2024-01", 2.0, mw=10.0, participant="X", source="A", sink="B"),
        _rec("2024-02", 3.0, mw=5.0, participant="X", source="A", sink="B"),
        _rec("2024-01", 1.0, mw=20.0, participant="Y", source="C", sink="D"),
    ]
    summary = analytics.participant_summary(recs)
    by_name = {s["participant"]: s for s in summary}
    assert by_name["X"]["total_awarded_mw"] == 15.0
    assert by_name["X"]["total_notional"] == pytest.approx(10.0 * 2.0 + 5.0 * 3.0)
    assert by_name["X"]["distinct_pairs"] == 1
    assert by_name["X"]["auction_count"] == 2
    # sorted descending by notional
    assert summary[0]["total_notional"] >= summary[-1]["total_notional"]


def test_all_pairs_preserves_first_seen_order_and_dedupes():
    recs = [
        _rec("2024-01", 1.0, source="A", sink="B"),
        _rec("2024-02", 1.0, source="A", sink="B"),
        _rec("2024-01", 1.0, source="C", sink="D"),
    ]
    assert analytics.all_pairs(recs) == [("A", "B"), ("C", "D")]


def test_recent_auction_month():
    recs = [_rec("2024-01", 1.0), _rec("2025-06", 1.0), _rec("2023-12", 1.0)]
    assert analytics.recent_auction_month(recs) == "2025-06"
    assert analytics.recent_auction_month([]) is None


def test_discover_top_pairs_ranks_by_notional_and_caps_at_n():
    recs = [_rec(f"2024-{m:02d}", 10.0, mw=100.0, source="A", sink="B") for m in (1, 2)]
    recs += [_rec("2024-01", 1.0, mw=5.0, source="C", sink="D")]
    top = analytics.discover_top_pairs(recs, n=1)
    assert len(top) == 1
    assert top[0]["source"] == "A" and top[0]["sink"] == "B"
    assert top[0]["total_notional"] == pytest.approx(2000.0)


def test_discover_top_pairs_uses_absolute_value_for_netted_sell_rows():
    recs = [
        _rec("2024-01", 5.0, mw=50.0, source="A", sink="B"),
        _rec("2024-01", 5.0, mw=-20.0, source="A", sink="B"),
    ]
    top = analytics.discover_top_pairs(recs, n=5)
    assert top[0]["total_notional"] == pytest.approx((50 + 20) * 5.0)


def test_discover_top_pairs_counts_distinct_participants():
    recs = [
        _rec("2024-01", 5.0, source="A", sink="B", participant="X"),
        _rec("2024-01", 5.0, source="A", sink="B", participant="Y"),
        _rec("2024-01", 5.0, source="A", sink="B", participant="X"),
    ]
    top = analytics.discover_top_pairs(recs, n=5)
    assert top[0]["participant_count"] == 2


def test_top_paths_includes_plain_language_reason():
    recs = [_rec(f"2024-{m:02d}", 10.0, mw=50.0, source="A", sink="B") for m in range(1, 13)]
    paths = analytics.top_paths(recs, n=5)
    assert len(paths) == 1
    assert "months" in paths[0]["reason"]
    assert "participants" in paths[0]["reason"]


def test_participant_strategy_nets_buy_and_sell_mw():
    recs = [
        _rec("2024-01", 5.0, mw=50.0, source="A", sink="B", crr_type="OBLIGATION"),
        _rec("2024-01", 5.0, mw=-20.0, source="A", sink="B", crr_type="OBLIGATION"),
    ]
    strat = analytics.participant_strategy("X", recs)
    assert strat["net_mw"] == 30.0
    assert strat["certificate_count"] == 2


def test_participant_strategy_option_obligation_split():
    recs = [
        _rec("2024-01", 1.0, crr_type="OPTION"),
        _rec("2024-01", 1.0, crr_type="OPTION"),
        _rec("2024-01", 1.0, crr_type="OBLIGATION"),
    ]
    strat = analytics.participant_strategy("X", recs)
    assert strat["option_pct"] == pytest.approx(66.7, abs=0.1)
    assert strat["obligation_pct"] == pytest.approx(33.3, abs=0.1)


def test_participant_strategy_preaward_pct_defaults_when_missing():
    recs = [_rec("2024-01", 1.0), _rec("2024-02", 1.0)]
    strat = analytics.participant_strategy("X", recs)
    assert strat["preaward_pct"] == 0.0


def test_participant_strategy_empty_records_is_safe():
    strat = analytics.participant_strategy("Nobody", [])
    assert strat["certificate_count"] == 0
    assert strat["top_pairs"] == []
