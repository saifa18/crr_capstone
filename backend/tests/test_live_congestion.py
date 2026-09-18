from unittest.mock import MagicMock, patch

import pytest

from app.live_congestion import (
    LIVE_PARTICIPANT_TAG,
    aggregate_to_monthly_records,
    classify_tou,
    compute_spread_records,
    fetch_live_pair_records,
    fetch_settlement_point_hourly_prices,
    parse_api_rows,
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
    by_hour = {r["hour_ending"]: r["spread"] for r in result}
    assert by_hour[8] == pytest.approx(15.0)   # sink higher -> positive spread
    assert by_hour[9] == pytest.approx(-2.0)   # sink lower -> negative spread
    assert all("time_of_use" in r for r in result)


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
