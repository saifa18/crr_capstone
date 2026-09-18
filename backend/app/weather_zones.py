"""
ERCOT weather-zone reference data and Open-Meteo-backed current/seasonal
weather context.

ERCOT publishes 8 official weather zones (Coast, East, Far West, North,
North Central, South, South Central, West) -- these are the exact names
Reggie Wade read off ERCOT's own public weather-zone map
(ercot.com/news/mediakit/maps) during the 2026-09 review call.
Weather-zone and load-zone/hub boundaries are NOT congruent (they're drawn
for different purposes -- climate similarity vs. electrical topology), so
each zone below is mapped to its *closest* tracked hub/load zone rather
than a precise electrical boundary -- flagged in `mapping_note` where it's
a real stretch, not hidden, matching this project's honesty policy for
synthetic data and live-integration limits elsewhere.

Data flow: one representative city per zone (lat/lon) is queried against
Open-Meteo's free, keyless, CORS-open APIs -- current conditions from
`api.open-meteo.com/v1/forecast`, and a trailing-12-month monthly-average
temperature (for seasonality) from `archive-api.open-meteo.com/v1/archive`.
Both were verified reachable and working, unauthenticated, during this
project's 2026-09 real-data investigation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
REQUEST_TIMEOUT = (10, 20)  # (connect, read) seconds


@dataclass(frozen=True)
class WeatherZone:
    name: str
    city: str
    latitude: float
    longitude: float
    hubs: tuple[str, ...]
    load_zones: tuple[str, ...]
    mapping_note: str = ""


WEATHER_ZONES: list[WeatherZone] = [
    WeatherZone("Coast", "Houston", 29.7604, -95.3698, ("HB_HOUSTON",), ("LZ_HOUSTON",)),
    WeatherZone(
        "East", "Tyler", 32.3513, -95.3011, ("HB_HOUSTON",), ("LZ_HOUSTON",),
        mapping_note="East Texas load has no dedicated ERCOT hub/load zone in this "
                     "project's tracked set; Houston is the closest tracked point.",
    ),
    WeatherZone("Far West", "Midland", 31.9973, -102.0779, ("HB_WEST", "HB_PAN"), ("LZ_WEST",)),
    WeatherZone("North", "Wichita Falls", 33.9137, -98.4934, ("HB_NORTH",), ("LZ_NORTH", "LZ_RAYBN")),
    WeatherZone(
        "North Central", "Dallas-Fort Worth", 32.7767, -96.7970, ("HB_NORTH",), ("LZ_NORTH",),
        mapping_note="ERCOT's North and North Central weather zones both map to "
                     "HB_NORTH/LZ_NORTH here -- there is no separate 'North Central' "
                     "settlement point in this project's tracked set.",
    ),
    WeatherZone("South", "Corpus Christi", 27.8006, -97.3964, ("HB_SOUTH",), ("LZ_AEN",)),
    WeatherZone("South Central", "Austin", 30.2672, -97.7431, ("HB_SOUTH",), ("LZ_CPS", "LZ_LCRA")),
    WeatherZone("West", "San Angelo", 31.4638, -100.4370, ("HB_WEST", "HB_PAN"), ("LZ_WEST",)),
]


class WeatherFetchError(RuntimeError):
    """Raised for any failure talking to Open-Meteo, with a human-readable
    message -- callers show this, never a blank panel or raw traceback."""


def _get(url: str, params: dict, session: Any = None) -> dict:
    sess = session or requests
    try:
        response = sess.get(url, params=params, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as e:
        raise WeatherFetchError(f"Could not reach Open-Meteo: {e}") from e
    if response.status_code != 200:
        raise WeatherFetchError(f"Open-Meteo returned HTTP {response.status_code}: {response.text[:200]}")
    return response.json()


def current_conditions_by_zone(session: Any = None) -> list[dict[str, Any]]:
    """Current temperature/wind/cloud-cover for every WEATHER_ZONES entry.
    Fails per-zone, not all-or-nothing: one zone's fetch failing doesn't
    blank out the other seven -- each entry carries its own 'error' key
    (None on success) so the caller can render a partial, honest panel."""
    out = []
    for zone in WEATHER_ZONES:
        entry: dict[str, Any] = {"zone": zone.name, "city": zone.city, "error": None}
        try:
            data = _get(
                FORECAST_URL,
                {
                    "latitude": zone.latitude,
                    "longitude": zone.longitude,
                    "current": "temperature_2m,wind_speed_10m,cloud_cover,weather_code",
                    "temperature_unit": "fahrenheit",
                    "wind_speed_unit": "mph",
                    "timezone": "America/Chicago",
                },
                session,
            )
            current = data["current"]
            entry.update(
                temperature_f=current["temperature_2m"],
                wind_mph=current["wind_speed_10m"],
                cloud_cover_pct=current["cloud_cover"],
                weather_code=current["weather_code"],
            )
        except (WeatherFetchError, KeyError) as e:
            entry["error"] = str(e)
        out.append(entry)
    return out


def _monthly_averages(dates: list[str], temps: list[float]) -> list[dict[str, Any]]:
    """Collapses daily (date, mean-temp) pairs into one
    average-temperature-per-calendar-month series, sorted chronologically."""
    by_month: dict[str, list[float]] = {}
    for d, t in zip(dates, temps):
        if t is None:
            continue
        month = d[:7]  # "YYYY-MM-DD" -> "YYYY-MM"
        by_month.setdefault(month, []).append(t)
    months = sorted(by_month)
    return [
        {"month": m, "avg_temperature_f": round(sum(by_month[m]) / len(by_month[m]), 1)}
        for m in months
    ]


def trailing_12mo_seasonality_by_zone(
    session: Any = None, today: date | None = None
) -> dict[str, list[dict[str, Any]] | None]:
    """Trailing-12-month monthly-average-temperature series per weather
    zone, from Open-Meteo's free historical archive -- the seasonality
    view Reggie asked for on the review call ("take an average across each
    zone and maybe even make a time series... you'll see some of the
    seasonality"). Returns None for a zone whose fetch failed, rather than
    raising and blanking every other zone's chart."""
    end = today or date.today()
    start = end - timedelta(days=366)
    out: dict[str, list[dict[str, Any]] | None] = {}
    for zone in WEATHER_ZONES:
        try:
            data = _get(
                ARCHIVE_URL,
                {
                    "latitude": zone.latitude,
                    "longitude": zone.longitude,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "daily": "temperature_2m_mean",
                    "temperature_unit": "fahrenheit",
                    "timezone": "America/Chicago",
                },
                session,
            )
            daily = data["daily"]
            out[zone.name] = _monthly_averages(daily["time"], daily["temperature_2m_mean"])
        except (WeatherFetchError, KeyError):
            out[zone.name] = None
    return out
