from __future__ import annotations

from unittest.mock import MagicMock

from app import weather_zones


def _mock_response(status_code=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


def test_weather_zones_cover_all_eight_official_zones():
    names = {z.name for z in weather_zones.WEATHER_ZONES}
    assert names == {
        "Coast", "East", "Far West", "North", "North Central",
        "South", "South Central", "West",
    }


def test_every_zone_maps_to_at_least_one_tracked_settlement_point():
    for zone in weather_zones.WEATHER_ZONES:
        assert zone.hubs or zone.load_zones


def test_current_conditions_success():
    session = MagicMock()
    session.get.return_value = _mock_response(200, {
        "current": {"temperature_2m": 85.0, "wind_speed_10m": 12.0,
                     "cloud_cover": 40, "weather_code": 1}
    })
    out = weather_zones.current_conditions_by_zone(session=session)
    assert len(out) == 8
    assert all(entry["error"] is None for entry in out)
    assert out[0]["temperature_f"] == 85.0


def test_current_conditions_fails_open_per_zone():
    session = MagicMock()
    session.get.return_value = _mock_response(500, text="server error")
    out = weather_zones.current_conditions_by_zone(session=session)
    assert len(out) == 8
    assert all(entry["error"] is not None for entry in out)
    assert all("temperature_f" not in entry for entry in out)


def test_monthly_averages_collapses_daily_to_calendar_month():
    dates = ["2025-01-01", "2025-01-02", "2025-02-01"]
    temps = [50.0, 60.0, 70.0]
    out = weather_zones._monthly_averages(dates, temps)
    assert out == [
        {"month": "2025-01", "avg_temperature_f": 55.0},
        {"month": "2025-02", "avg_temperature_f": 70.0},
    ]


def test_monthly_averages_skips_none_values():
    dates = ["2025-01-01", "2025-01-02"]
    temps = [50.0, None]
    out = weather_zones._monthly_averages(dates, temps)
    assert out == [{"month": "2025-01", "avg_temperature_f": 50.0}]


def test_trailing_12mo_seasonality_success():
    session = MagicMock()
    session.get.return_value = _mock_response(200, {
        "daily": {"time": ["2025-01-01"], "temperature_2m_mean": [55.0]}
    })
    out = weather_zones.trailing_12mo_seasonality_by_zone(session=session)
    assert len(out) == 8
    assert all(v == [{"month": "2025-01", "avg_temperature_f": 55.0}] for v in out.values())


def test_trailing_12mo_seasonality_fails_open_per_zone():
    session = MagicMock()
    session.get.return_value = _mock_response(500, text="server error")
    out = weather_zones.trailing_12mo_seasonality_by_zone(session=session)
    assert len(out) == 8
    assert all(v is None for v in out.values())
