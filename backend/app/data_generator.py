"""
Synthetic ERCOT CRR auction data generator.

Produces monthly CRR auction records (2019-01 .. latest completed month)
for a curated set of Source/Sink pairs (see domain.CRR_PAIRS), each with:
  - CRR type (OPTION / OBLIGATION)
  - Time of use bucket (PEAK_WD / PEAK_WE / OFF_PEAK)
  - Clearing price ($/MWh)
  - Awarded MW
  - Winning participant (CRR Account Holder)

The price process is a deterministic, seeded random walk with:
  - a pair-specific base congestion level (some pairs are chronically
    congested -- e.g. West -> Houston -- others are mild),
  - seasonal shape (higher congestion value in summer peak months and
    winter cold-snap months, matching real ERCOT congestion drivers:
    summer AC load + renewable output overloading export paths, winter
    heating load + occasional generation-limited events),
  - a small number of stress months calibrated to loosely resemble known
    ERCOT system stress events (Feb 2021 winter event, summer 2023 record
    peak load) purely for illustrative shape, not as a claim of historical
    accuracy,
  - participant-level noise so different Account Holders realize modestly
    different realized values on the same Source/Sink/month.

All output is deterministic given SEED so tests and the UI snapshot are
reproducible.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, asdict, field
from datetime import date
from typing import Iterator

from .domain import CRR_PAIRS, CRRType, TimeOfUse, SP_BY_CODE

SEED = 20260826  # fixed seed -> fully reproducible synthetic dataset
START_YEAR, START_MONTH = 2019, 1
END_YEAR, END_MONTH = 2026, 7  # last fully completed month before "today"

PARTICIPANTS = [
    "Lone Star Power Trading LLC",
    "Permian Basin Energy Partners",
    "Gulf Coast Congestion Advisors",
    "Bluebonnet Risk Management LP",
    "Panhandle Wind Marketing Co",
    "Alamo Energy Trading",
    "Brazos Valley Power Fund",
    "Coastal Bend Capital Markets",
    "Hill Country Hedge Partners",
    "Piney Woods Power Trading",
    "Trinity River Trading Group",
    "Republic Grid Analytics LLC",
    "Cactus Energy Solutions",
    "Longhorn Transmission Traders",
    "Southern Cross Power Marketing",
]

# Pair-specific base congestion ($/MWh, average level a SOURCE->SINK CRR
# would be expected to be worth) and volatility multiplier. Higher values
# for well-known west/panhandle -> load-center paths, matching the real
# ERCOT congestion story of renewable-rich west/panhandle generation
# needing to move east/south to load.
_PAIR_PROFILE = {
    ("HB_WEST", "HB_HOUSTON"): (7.5, 1.35),
    ("HB_WEST", "HB_NORTH"): (4.0, 1.10),
    ("HB_PAN", "HB_NORTH"): (5.5, 1.20),
    ("HB_PAN", "HB_HOUSTON"): (8.5, 1.45),
    ("HB_SOUTH", "HB_HOUSTON"): (2.5, 0.85),
    ("LZ_WEST", "LZ_HOUSTON"): (7.0, 1.30),
    ("HB_NORTH", "LZ_HOUSTON"): (3.5, 1.00),
    ("PANHANDLE_WIND_RN", "HB_NORTH"): (6.5, 1.55),
    ("PERMIAN_SOLAR_RN", "HB_WEST"): (5.0, 1.60),
    ("COASTAL_BEND_WIND_RN", "HB_HOUSTON"): (3.0, 1.25),
    ("GULF_COAST_CC_RN", "LZ_HOUSTON"): (1.5, 0.70),
    ("EAGLE_FORD_GAS_RN", "LZ_AEN"): (1.0, 0.60),
    ("HB_WEST", "LZ_AEN"): (2.0, 0.90),
    ("HB_SOUTH", "LZ_CPS"): (0.8, 0.55),
    ("HB_NORTH", "LZ_RAYBN"): (1.2, 0.65),
}


@dataclass(frozen=True)
class AuctionRecord:
    auction_month: str            # "YYYY-MM"
    source: str
    sink: str
    crr_type: str
    time_of_use: str
    clearing_price: float         # $/MWh, can be negative
    awarded_mw: float
    participant: str
    is_synthetic: bool = True


def _month_iter(y0, m0, y1, m1) -> Iterator[tuple[int, int]]:
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        yield y, m
        m += 1
        if m == 13:
            m = 1
            y += 1


def _seasonal_factor(month: int) -> float:
    """Summer-peak and winter-cold-snap congestion bump, mild shoulder months."""
    # Summer (Jun-Sep) and Jan/Feb get a congestion premium.
    if month in (7, 8):
        return 1.6
    if month in (6, 9):
        return 1.3
    if month in (1, 2):
        return 1.25
    return 1.0


def _stress_multiplier(year: int, month: int) -> float:
    """Illustrative stress-event bumps (shape only, not historically exact)."""
    if (year, month) == (2021, 2):
        return 3.2   # winter-event-shaped spike
    if (year, month) in ((2023, 7), (2023, 8)):
        return 1.9   # summer-record-load-shaped spike
    if (year, month) in ((2024, 8),):
        return 1.6
    return 1.0


def _tou_factor(tou: TimeOfUse) -> float:
    return {
        TimeOfUse.PEAK_WD: 1.15,
        TimeOfUse.PEAK_WE: 0.85,
        TimeOfUse.OFF_PEAK: 0.55,
    }[tou]


def generate_auction_records() -> list[AuctionRecord]:
    rng = random.Random(SEED)
    records: list[AuctionRecord] = []

    for source, sink in CRR_PAIRS:
        base, vol = _PAIR_PROFILE[(source, sink)]
        # slow independent drift per pair so trends differ pair to pair
        drift = rng.uniform(-0.03, 0.05)
        level = base
        month_idx = 0
        for year, month in _month_iter(START_YEAR, START_MONTH, END_YEAR, END_MONTH):
            month_idx += 1
            level = max(0.1, level * (1 + drift * 0.05) + rng.uniform(-0.4, 0.4) * vol)
            seasonal = _seasonal_factor(month)
            stress = _stress_multiplier(year, month)

            for tou in TimeOfUse:
                for crr_type in CRRType:
                    tou_f = _tou_factor(tou)
                    noise = rng.gauss(0, 0.6 * vol)
                    price = level * seasonal * stress * tou_f + noise
                    if crr_type == CRRType.OPTION:
                        # Options never pay negative to the holder in the
                        # secondary economic sense modeled here (simplified):
                        # clearing price for the option itself is smaller
                        # (it's the cost of the right, not the flow value).
                        price = max(0.05, price * 0.35 + rng.uniform(0, 0.3))
                    else:
                        # Obligation CRRs mirror expected congestion value
                        # and can clear negative when a path is persistently
                        # counter-congested.
                        price = round(price, 2)

                    awarded_mw = round(abs(rng.gauss(35, 15)) + 5, 1)
                    participant = PARTICIPANTS[
                        (hash((source, sink, year, month, tou.value, crr_type.value))
                         + rng.randint(0, len(PARTICIPANTS) - 1)) % len(PARTICIPANTS)
                    ]

                    records.append(
                        AuctionRecord(
                            auction_month=f"{year:04d}-{month:02d}",
                            source=source,
                            sink=sink,
                            crr_type=crr_type.value,
                            time_of_use=tou.value,
                            clearing_price=round(price, 2),
                            awarded_mw=awarded_mw,
                            participant=participant,
                        )
                    )
    return records


def records_as_dicts() -> list[dict]:
    return [asdict(r) for r in generate_auction_records()]
