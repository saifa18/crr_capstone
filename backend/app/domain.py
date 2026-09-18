"""
Domain model and reference data for the ERCOT CRR Market Analytics prototype.

Reference names below (trading hubs, load zones, CRR types) match ERCOT's
public nodal market naming conventions and are drawn from ERCOT training
material (Locational Marginal Pricing WBT, Wholesale Markets 101, Congestion
Revenue Rights WBT) and the public CRR page (ercot.com/mktinfo/crr).

IMPORTANT DATA DISCLOSURE
--------------------------
ERCOT does publish real historical CRR Auction Results (NP7-802-M long-term,
NP7-803-M monthly) on the MIS Public Area, and these files do include
Source, Sink, CRR type, clearing price, and CRR Account Holder (the market
participant). However, that download center is a JavaScript-driven file
browser behind mis.ercot.com with no stable, unauthenticated direct-download
URL pattern, so it cannot be scripted from this offline environment.

This prototype therefore ships with a *synthetic* dataset generator
(`data_generator.py`) that is statistically calibrated to look and behave
like real ERCOT CRR auction results (same node names, same auction
cadence, congestion driven by simulated LMP/SPP spreads with seasonal and
locational structure). Every synthetic record is tagged `is_synthetic=True`
and the data-source banner in the UI says so explicitly.

The ingestion layer (`ingestion.py`) accepts real ERCOT auction-result CSVs
in ERCOT's published column layout, so a user with MIS access can drop real
files into `data/raw/` and the app will use them instead -- see README.
"""

from dataclasses import dataclass
from enum import Enum


class CRRType(str, Enum):
    OPTION = "OPTION"
    OBLIGATION = "OBLIGATION"


class AuctionType(str, Enum):
    MONTHLY = "MONTHLY"
    LONG_TERM = "LONG_TERM"


class TimeOfUse(str, Enum):
    PEAK_WD = "PEAK_WD"     # On-peak weekday
    PEAK_WE = "PEAK_WE"     # On-peak weekend
    OFF_PEAK = "OFF_PEAK"


@dataclass(frozen=True)
class SettlementPoint:
    code: str
    name: str
    kind: str  # "HUB", "LOAD_ZONE", "NODE"
    zone: str  # coarse ERCOT weather zone for grouping


# Trading hubs -- these are ERCOT's actual published hub codes.
HUBS = [
    SettlementPoint("HB_NORTH", "North Hub", "HUB", "North"),
    SettlementPoint("HB_SOUTH", "South Hub", "HUB", "South"),
    SettlementPoint("HB_WEST", "West Hub", "HUB", "West"),
    SettlementPoint("HB_HOUSTON", "Houston Hub", "HUB", "Coast"),
    SettlementPoint("HB_PAN", "Panhandle Hub", "HUB", "Panhandle"),
    SettlementPoint("HB_BUSAVG", "Bus Average Hub", "HUB", "System"),
]

# Load zones -- ERCOT's actual published load zone codes.
LOAD_ZONES = [
    SettlementPoint("LZ_NORTH", "North Load Zone", "LOAD_ZONE", "North"),
    SettlementPoint("LZ_SOUTH", "South Load Zone", "LOAD_ZONE", "South"),
    SettlementPoint("LZ_WEST", "West Load Zone", "LOAD_ZONE", "West"),
    SettlementPoint("LZ_HOUSTON", "Houston Load Zone", "LOAD_ZONE", "Coast"),
    SettlementPoint("LZ_AEN", "AEP Central Load Zone", "LOAD_ZONE", "South Central"),
    SettlementPoint("LZ_CPS", "CPS Energy Load Zone", "LOAD_ZONE", "South Central"),
    SettlementPoint("LZ_LCRA", "LCRA Load Zone", "LOAD_ZONE", "Central"),
    SettlementPoint("LZ_RAYBN", "Rayburn Load Zone", "LOAD_ZONE", "North"),
]

# A representative set of congestion-prone generic resource nodes, named the
# way ERCOT node IDs typically look (illustrative, not real interconnection
# points), used to give the Source/Sink explorer some node-level (not just
# hub-level) pairs typical of a CRR portfolio.
GEN_NODES = [
    SettlementPoint("PANHANDLE_WIND_RN", "Panhandle Wind Resource Node", "NODE", "Panhandle"),
    SettlementPoint("PERMIAN_SOLAR_RN", "Permian Basin Solar Resource Node", "NODE", "West"),
    SettlementPoint("COASTAL_BEND_WIND_RN", "Coastal Bend Wind Resource Node", "NODE", "South"),
    SettlementPoint("GULF_COAST_CC_RN", "Gulf Coast Combined-Cycle Resource Node", "NODE", "Coast"),
    SettlementPoint("EAGLE_FORD_GAS_RN", "Eagle Ford Gas Resource Node", "NODE", "South Central"),
]

ALL_SETTLEMENT_POINTS = HUBS + LOAD_ZONES + GEN_NODES
SP_BY_CODE = {sp.code: sp for sp in ALL_SETTLEMENT_POINTS}

# Kinds whose codes are real, ERCOT-published settlement point identifiers
# that resolve against the live ERCOT Public API (api.ercot.com). GEN_NODES
# codes are illustrative/synthetic (see their comment above) and do NOT
# resolve against the live API, so live-data fetches are restricted to pairs
# built only from these kinds.
LIVE_API_ELIGIBLE_KINDS = {"HUB", "LOAD_ZONE"}


def is_live_api_eligible(source: str, sink: str) -> bool:
    """True if both settlement points are real ERCOT codes the live Public
    API can be queried for (as opposed to this project's illustrative
    synthetic resource-node codes)."""
    src = SP_BY_CODE.get(source)
    snk = SP_BY_CODE.get(sink)
    if src is None or snk is None:
        return False
    return src.kind in LIVE_API_ELIGIBLE_KINDS and snk.kind in LIVE_API_ELIGIBLE_KINDS

# Curated Source -> Sink pairs representative of real congestion patterns:
# west/panhandle wind & solar generation (Source, price sink from generation's
# point of view) congesting into load centers (Sink) in Houston/North/South,
# which is the dominant, well-documented ERCOT congestion story (transmission
# constraints moving West/Panhandle renewable output east/south to load).
CRR_PAIRS = [
    ("HB_WEST", "HB_HOUSTON"),
    ("HB_WEST", "HB_NORTH"),
    ("HB_PAN", "HB_NORTH"),
    ("HB_PAN", "HB_HOUSTON"),
    ("HB_SOUTH", "HB_HOUSTON"),
    ("LZ_WEST", "LZ_HOUSTON"),
    ("HB_NORTH", "LZ_HOUSTON"),
    ("PANHANDLE_WIND_RN", "HB_NORTH"),
    ("PERMIAN_SOLAR_RN", "HB_WEST"),
    ("COASTAL_BEND_WIND_RN", "HB_HOUSTON"),
    ("GULF_COAST_CC_RN", "LZ_HOUSTON"),
    ("EAGLE_FORD_GAS_RN", "LZ_AEN"),
    ("HB_WEST", "LZ_AEN"),
    ("HB_SOUTH", "LZ_CPS"),
    ("HB_NORTH", "LZ_RAYBN"),
]
