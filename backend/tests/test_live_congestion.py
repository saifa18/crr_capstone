from unittest.mock import MagicMock, patch

import pytest

from app.live_congestion import (
    LIVE_PARTICIPANT_TAG,
    _parse_hour_ending,
    aggregate_prices_to_daily,
    aggregate_to_daily_series,
    aggregate_to_monthly_records,
    aggregate_to_period_settlement_value,
    classify_tou,
    compute_obligation_settlement,
    compute_option_settlement,
    compute_spread_records,
    fetch_live_pair_records,
    fetch_settlement_point_hourly_prices,
    parse_api_rows,
    summarize_settlement_series,
    total_pages,
)


def test_parse_api_rows_converts_columnar_shape_to_dicts():
    response = {
        "fields": [{"name": "deliveryDate"}, {"name": "hourEnding"}, {"name": "settlementPointPrice"}],
        "data": [["2026-01-01", 8, 22.5], ["2026-01-01", 9, 24.1]],
        "_meta": {"totalPages": 1},
    }
    rows = parse_api_rows(response)
    assert rows == [
        {"deliveryDate": "2026-01-01", "hourEnding": 8, "settlementPointPrice": 22.5},
        {"deliveryDate": "2026-01-01", "hourEnding": 9, "settlementPointPrice": 24.1},
    ]


def test_total_pages_defaults_to_one():
    assert total_pages({}) == 1
    assert total_pages({"_meta": {"totalPages": 4}}) == 4


@pytest.mark.parametrize(
    "delivery_date,hour_ending,expected",
    [
        ("2026-06-01", 10, "PEAK_WD"),   # Monday, on-peak hour
        ("2026-06-06", 10, "PEAK_WE"),   # Saturday, on-peak hour
        ("2026-06-07", 10, "OFF_PEAK"),  # Sunday, on-peak hour but not Mon-Sat
        ("2026-06-01", 3, "OFF_PEAK"),   # Monday, off-peak hour (HE03)
        ("2026-06-01", 22, "PEAK_WD"),   # Monday, last on-peak hour
        ("2026-06-01", 23, "OFF_PEAK"),  # Monday, first off-peak evening hour
    ],
)
def test_classify_tou(delivery_date, hour_ending, expected):
    assert classify_tou(delivery_date, hour_ending) == expected


def test_compute_spread_records_joins_and_subtracts_correctly():
    source_prices = [
        {"delivery_date": "2026-01-01", "hour_ending": 8, "price": 20.0},
        {"delivery_date": "2026-01-01", "hour_ending": 9, "price": 21.0},
    ]
    sink_prices = [
        {"delivery_date": "2026-01-01", "hour_ending": 8, "price": 35.0},
        {"delivery_date": "2026-01-01", "hour_ending": 9, "price": 19.0},
    ]
    result = compute_spread_records(source_prices, sink_prices, "HB_WEST", "HB_HOUSTON")
    by_hour = {r["hour_ending"]: r for r in result}
    assert by_hour[8]["spread"] == pytest.approx(15.0)   # sink higher -> positive spread
    assert by_hour[8]["option_settlement"] == pytest.approx(15.0)
    assert by_hour[8]["source_price"] == pytest.approx(20.0)
    assert by_hour[8]["sink_price"] == pytest.approx(35.0)
    assert by_hour[9]["spread"] == pytest.approx(-2.0)   # sink lower -> negative spread
    assert by_hour[9]["option_settlement"] == pytest.approx(0.0)  # floored, never negative
    assert all("time_of_use" in r for r in result)


@pytest.mark.parametrize(
    "source_price,sink_price,expected_obligation,expected_option",
    [
        (40.0, 50.0, 10.0, 10.0),   # sink > source -> both positive, equal
        (50.0, 40.0, -10.0, 0.0),   # sink < source -> obligation negative, option floored to 0
        (40.0, 40.0, 0.0, 0.0),     # flat -> both zero
    ],
)
def test_settlement_formulas_match_ercot_protocol(source_price, sink_price, expected_obligation, expected_option):
    assert compute_obligation_settlement(source_price, sink_price) == pytest.approx(expected_obligation)
    assert compute_option_settlement(source_price, sink_price) == pytest.approx(expected_option)


@pytest.mark.parametrize(
    "source_price,sink_price",
    [(None, 50.0), (40.0, None), (None, None)],
)
def test_settlement_formulas_reject_missing_prices_instead_of_defaulting_to_zero(source_price, sink_price):
    with pytest.raises(ValueError):
        compute_obligation_settlement(source_price, sink_price)
    with pytest.raises(ValueError):
        compute_option_settlement(source_price, sink_price)


def test_aggregate_prices_to_daily_averages_one_nodes_own_prices():
    hourly = [
        {"delivery_date": "2026-01-01", "hour_ending": 1, "price": 10.0},
        {"delivery_date": "2026-01-01", "hour_ending": 2, "price": 20.0},
        {"delivery_date": "2026-01-02", "hour_ending": 1, "price": 5.0},
    ]
    assert aggregate_prices_to_daily(hourly) == [
        {"date": "2026-01-01", "price": 15.0},
        {"date": "2026-01-02", "price": 5.0},
    ]


def test_aggregate_prices_to_daily_empty_input():
    assert aggregate_prices_to_daily([]) == []


def test_summarize_settlement_series_reports_latest_average_min_max():
    hourly = [
        {"delivery_date": "2026-01-01", "hour_ending": 1, "spread": 10.0, "option_settlement": 10.0},
        {"delivery_date": "2026-01-02", "hour_ending": 1, "spread": -4.0, "option_settlement": 0.0},
        {"delivery_date": "2026-01-03", "hour_ending": 1, "spread": 6.0, "option_settlement": 6.0},
    ]
    summary = summarize_settlement_series(hourly)
    assert summary["obligation"] == {"latest": 6.0, "average": pytest.approx(4.0), "min": -4.0, "max": 10.0}
    assert summary["option"] == {"latest": 6.0, "average": round(16 / 3, 3), "min": 0.0, "max": 10.0}


def test_summarize_settlement_series_empty_input():
    summary = summarize_settlement_series([])
    assert summary["obligation"] == {"latest": None, "average": None, "min": None, "max": None}
    assert summary["option"] == {"latest": None, "average": None, "min": None, "max": None}


def test_compute_spread_records_skips_unmatched_hours():
    source_prices = [{"delivery_date": "2026-01-01", "hour_ending": 8, "price": 20.0}]
    sink_prices = [{"delivery_date": "2026-01-01", "hour_ending": 9, "price": 30.0}]  # different hour
    result = compute_spread_records(source_prices, sink_prices, "A", "B")
    assert result == []


def test_aggregate_to_monthly_records_averages_correctly_by_month_and_tou():
    hourly = [
        {"delivery_date": "2026-01-05", "hour_ending": 8, "spread": 10.0, "time_of_use": "PEAK_WD"},
        {"delivery_date": "2026-01-12", "hour_ending": 9, "spread": 20.0, "time_of_use": "PEAK_WD"},
        {"delivery_date": "2026-01-05", "hour_ending": 2, "spread": 4.0, "time_of_use": "OFF_PEAK"},
        {"delivery_date": "2026-02-05", "hour_ending": 8, "spread": 100.0, "time_of_use": "PEAK_WD"},
    ]
    records = aggregate_to_monthly_records(hourly, "HB_WEST", "HB_HOUSTON")
    by_key = {(r["auction_month"], r["time_of_use"]): r for r in records}

    jan_peak = by_key[("2026-01", "PEAK_WD")]
    assert jan_peak["clearing_price"] == pytest.approx(15.0)  # avg(10, 20)
    assert jan_peak["source"] == "HB_WEST"
    assert jan_peak["sink"] == "HB_HOUSTON"
    assert jan_peak["crr_type"] == "OBLIGATION"
    assert jan_peak["participant"] == LIVE_PARTICIPANT_TAG
    assert jan_peak["awarded_mw"] == 0.0
    assert jan_peak["is_synthetic"] is False

    jan_off = by_key[("2026-01", "OFF_PEAK")]
    assert jan_off["clearing_price"] == pytest.approx(4.0)

    feb_peak = by_key[("2026-02", "PEAK_WD")]
    assert feb_peak["clearing_price"] == pytest.approx(100.0)


def test_aggregate_to_monthly_records_empty_input():
    assert aggregate_to_monthly_records([], "A", "B") == []


def test_fetch_settlement_point_hourly_prices_paginates(monkeypatch):
    client = MagicMock()
    page1 = {
        "fields": [{"name": "deliveryDate"}, {"name": "hourEnding"}, {"name": "settlementPointPrice"}],
        "data": [["2026-01-01", 1, 10.0]],
        "_meta": {"totalPages": 2},
    }
    page2 = {
        "fields": [{"name": "deliveryDate"}, {"name": "hourEnding"}, {"name": "settlementPointPrice"}],
        "data": [["2026-01-01", 2, 11.0]],
        "_meta": {"totalPages": 2},
    }
    client.get_dam_settlement_point_prices.side_effect = [page1, page2]

    result = fetch_settlement_point_hourly_prices(client, "HB_WEST", "2026-01-01", "2026-01-02")

    assert result == [
        {"delivery_date": "2026-01-01", "hour_ending": 1, "price": 10.0},
        {"delivery_date": "2026-01-01", "hour_ending": 2, "price": 11.0},
    ]
    assert client.get_dam_settlement_point_prices.call_count == 2


def test_fetch_live_pair_records_end_to_end_with_mocked_client():
    client = MagicMock()

    def fake_spp(settlement_point, delivery_date_from, delivery_date_to, page=1, size=1000):
        fields = [{"name": "deliveryDate"}, {"name": "hourEnding"}, {"name": "settlementPointPrice"}]
        if settlement_point == "HB_WEST":
            data = [["2026-03-01", 8, 20.0], ["2026-03-01", 9, 22.0]]
        else:
            data = [["2026-03-01", 8, 30.0], ["2026-03-01", 9, 21.0]]
        return {"fields": fields, "data": data, "_meta": {"totalPages": 1}}

    client.get_dam_settlement_point_prices.side_effect = fake_spp

    records = fetch_live_pair_records(client, "HB_WEST", "HB_HOUSTON", "2026-03-01", "2026-03-02")

    assert len(records) >= 1
    for r in records:
        assert r["source"] == "HB_WEST"
        assert r["sink"] == "HB_HOUSTON"
        assert r["crr_type"] == "OBLIGATION"
        # matches the exact shape analytics.py/scoring.py expect
        assert set(r.keys()) >= {
            "auction_month", "source", "sink", "crr_type", "time_of_use",
            "clearing_price", "awarded_mw", "participant",
        }


@pytest.mark.parametrize(
    "raw,expected",
    [
        (8, 8),
        (8.0, 8),
        ("8", 8),
        ("08", 8),
        ("01:00", 1),
        ("24:00", 24),
        ("14:00", 14),
    ],
)
def test_parse_hour_ending_handles_int_and_real_api_hhmm_string(raw, expected):
    # ERCOT's real live API returns hourEnding as "01:00"-style strings, not
    # bare integers -- confirmed 2026-09-21 against the actual credentialed
    # API, which raised ValueError under the old int(float(x)) parsing.
    assert _parse_hour_ending(raw) == expected


def test_fetch_settlement_point_hourly_prices_parses_real_hhmm_hour_ending(monkeypatch):
    client = MagicMock()
    page = {
        "fields": [{"name": "deliveryDate"}, {"name": "hourEnding"}, {"name": "settlementPointPrice"}],
        "data": [["2026-09-02", "01:00", 28.46], ["2026-09-02", "02:00", 25.92]],
        "_meta": {"totalPages": 1},
    }
    client.get_dam_settlement_point_prices.return_value = page

    result = fetch_settlement_point_hourly_prices(client, "HB_WEST", "2026-09-01", "2026-09-02")

    assert result == [
        {"delivery_date": "2026-09-02", "hour_ending": 1, "price": 28.46},
        {"delivery_date": "2026-09-02", "hour_ending": 2, "price": 25.92},
    ]


def test_fetch_settlement_point_hourly_prices_skips_null_price_rows_instead_of_defaulting_to_zero():
    client = MagicMock()
    page = {
        "fields": [{"name": "deliveryDate"}, {"name": "hourEnding"}, {"name": "settlementPointPrice"}],
        "data": [
            ["2026-09-02", "01:00", 28.46],
            ["2026-09-02", "02:00", None],  # ERCOT returned no price for this hour
        ],
        "_meta": {"totalPages": 1},
    }
    client.get_dam_settlement_point_prices.return_value = page

    result = fetch_settlement_point_hourly_prices(client, "HB_WEST", "2026-09-01", "2026-09-02")

    # The null-price hour is dropped entirely, never coerced to 0.0
    assert result == [{"delivery_date": "2026-09-02", "hour_ending": 1, "price": 28.46}]


def test_aggregate_to_daily_series_averages_per_day_and_computes_option_floor():
    hourly = [
        {"delivery_date": "2026-01-01", "hour_ending": 1, "spread": 10.0, "option_settlement": 10.0, "time_of_use": "OFF_PEAK"},
        {"delivery_date": "2026-01-01", "hour_ending": 2, "spread": -4.0, "option_settlement": 0.0, "time_of_use": "OFF_PEAK"},
        {"delivery_date": "2026-01-02", "hour_ending": 1, "spread": 6.0, "option_settlement": 6.0, "time_of_use": "OFF_PEAK"},
    ]
    series = aggregate_to_daily_series(hourly)
    assert series == [
        {"date": "2026-01-01", "obligation_price": 3.0, "option_price": 5.0},  # avg(10,-4)=3; avg(10,0)=5
        {"date": "2026-01-02", "obligation_price": 6.0, "option_price": 6.0},
    ]


def test_aggregate_to_daily_series_empty_input():
    assert aggregate_to_daily_series([]) == []


def test_aggregate_to_period_settlement_value_sums_not_averages_and_floors_option():
    hourly = [
        {"delivery_date": "2026-01-05", "hour_ending": 8, "spread": 10.0, "option_settlement": 10.0, "time_of_use": "PEAK_WD"},
        {"delivery_date": "2026-01-12", "hour_ending": 9, "spread": -3.0, "option_settlement": 0.0, "time_of_use": "PEAK_WD"},
        {"delivery_date": "2026-02-05", "hour_ending": 8, "spread": 100.0, "option_settlement": 100.0, "time_of_use": "PEAK_WD"},
    ]
    result = aggregate_to_period_settlement_value(hourly)
    by_key = {(r["auction_month"], r["time_of_use"]): r for r in result}

    jan = by_key[("2026-01", "PEAK_WD")]
    assert jan["obligation_value_per_mw"] == pytest.approx(7.0)   # 10 + (-3)
    assert jan["option_value_per_mw"] == pytest.approx(10.0)      # max(10,0) + max(-3,0)
    assert jan["hours"] == 2

    feb = by_key[("2026-02", "PEAK_WD")]
    assert feb["obligation_value_per_mw"] == pytest.approx(100.0)
    assert feb["option_value_per_mw"] == pytest.approx(100.0)
    assert feb["hours"] == 1


def test_aggregate_to_period_settlement_value_empty_input():
    assert aggregate_to_period_settlement_value([]) == []
