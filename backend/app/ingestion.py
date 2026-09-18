"""
Data ingestion layer for the auction/participant dataset (Dashboard,
Participants, Opportunity Signals).

`load_records()` is the single entry point the rest of the app uses for
that dataset. Priority order:
  1. A real SQL Server database, if configured (see `db.py`'s module
     docstring for exactly how to point this at a database on a different
     machine -- this is the intended production path).
  2. Real ERCOT CRR Auction Results CSVs in DATA_DIR/raw/ (the layout
     ERCOT ships in NP7-802-M / NP7-803-M zip downloads -- see README for
     the exact expected columns and where to get them from mis.ercot.com
     once logged in), if no SQL database is configured or reachable.
  3. The synthetic generator, so the app is always runnable out of the box
     with neither of the above configured.

Each tier is tried in order and the first one that succeeds wins; a
configured-but-unreachable SQL database does NOT silently fall through to
CSVs/synthetic without saying so -- see `load_records()`'s `warning` return
value, surfaced by the API so a misconfigured production deployment is
visible rather than quietly serving demo data.

This keeps the analytics/scoring layers 100% agnostic to where the dicts
came from -- they only ever see the same normalized record shape, whether
that's `db.load_records_from_sql()`, this module's CSV loader, or
`data_generator.AuctionRecord`.

NOTE on the *other* live-data path: real-time Source/Sink congestion value
computed from ERCOT's actual, live Day-Ahead Market prices is a SEPARATE
capability, not part of this ingestion tier -- see `ercot_live.py` and
`live_congestion.py`, exposed via `/api/pairs/{source}/{sink}/live-lmp-spread`
and `/api/live/binding-constraints` in main.py. It is kept separate
deliberately: this module's job is participant/MW/notional data (from SQL,
CSVs, or the synthetic demo), while the live API's job is real-time
congestion value (available live, for free, once registered, with zero
participant/MW data attached). A user can have any combination configured;
each degrades independently and explains itself when unavailable rather
than silently substituting another.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from . import db
from .data_generator import records_as_dicts

DATA_DIR = Path(os.environ.get("CRR_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
RAW_DIR = DATA_DIR / "raw"

SOURCE_SQL = "sql_server_real"
SOURCE_CSV = "ercot_mis_real"
SOURCE_SYNTHETIC = "synthetic_demo"

# Column names as published in ERCOT's real CRR Auction Results reports
# (NP7-803-M Monthly Auction Results, "Common_MarketResults_*.csv" inside
# the auction zip -- see backend/scripts/fetch_real_ercot_data.py). Matched
# case-insensitively; order within each tuple is priority (first match
# wins), which matters for crr_type below.
_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    # auction_month has no reliable direct column in the real file -- see
    # _derive_auction_month(), tried only when none of these match.
    "auction_month": ("auctionid", "auction", "auctionmonth", "deliverymonth"),
    "source": ("sourcelocation", "source", "sourcesettlementpoint"),
    "sink": ("sinklocation", "sink", "sinksettlementpoint"),
    # HedgeType (OBL/OPT) is ERCOT's real Option/Obligation column. CRRType
    # in that same real file means something different (PREAWARD/STANDARD,
    # captured separately as "award_type" below) -- hedgetype is checked
    # first so a real file's CRRType column is never mistaken for it.
    "crr_type": ("hedgetype", "crrtype", "type"),
    "time_of_use": ("timeofuse", "tou", "hourtype"),
    "clearing_price": ("shadowpricepermwh", "crrclearingprice", "clearingprice"),
    "awarded_mw": ("mw", "awardedquantity", "crmquantity", "quantity"),
    "participant": ("accountholder", "crraccountholder", "participant", "marketparticipant"),
}

# Present in some real layouts, absent in others (including every existing
# synthetic/older-format record) -- missing any of these does NOT cause the
# row to be skipped, unlike _COLUMN_ALIASES above.
_OPTIONAL_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "award_type": ("crrtype",),    # PREAWARD / STANDARD, real ERCOT files only
    "bid_type": ("bidtype",),      # BUY / SELL, real ERCOT files only
    "start_date": ("startdate",),  # used to derive auction_month when needed
}

_TIME_OF_USE_MAP = {
    "PEAKWD": "PEAK_WD",
    "PEAKWE": "PEAK_WE",
    "OFFPEAK": "OFF_PEAK",
}

_CRR_TYPE_MAP = {
    "OBL": "OBLIGATION",
    "OBLIGATION": "OBLIGATION",
    "OPT": "OPTION",
    "OPTION": "OPTION",
}


def _normalize_header(h: str) -> str:
    return h.strip().lower().replace(" ", "").replace("_", "").replace("-", "")


def _normalize_tou_value(raw: str) -> str:
    key = raw.strip().upper().replace("-", "").replace("_", "").replace(" ", "")
    return _TIME_OF_USE_MAP.get(key, raw.strip().upper())


def _normalize_crr_type_value(raw: str) -> str:
    key = raw.strip().upper()
    return _CRR_TYPE_MAP.get(key, key)


def _find_column(header_index: dict[str, int], aliases: tuple[str, ...]) -> int | None:
    for alias in aliases:
        if alias in header_index:
            return header_index[alias]
    return None


def _derive_auction_month(start_date: str) -> str | None:
    """StartDate is 'MM/DD/YYYY' in ERCOT's real Monthly Auction Results
    file, which otherwise has no explicit auction/delivery-month column."""
    try:
        month, _day, year = start_date.strip().split("/")
        return f"{year}-{int(month):02d}"
    except (ValueError, AttributeError):
        return None


def _load_participant_registry(registry_path: "Path | None" = None) -> dict[str, str]:
    """Maps ERCOT's masked CRR Account Holder short codes (e.g. 'XSARAC') to
    real company names, from the real Market Participants List (NP12-215-ER,
    CRRAH sheet -- see backend/scripts/fetch_real_ercot_data.py). Returns {}
    if the registry file doesn't exist, so callers fall back to showing the
    short code as the participant name -- same as before this registry
    existed, never a crash."""
    path = registry_path or PARTICIPANT_REGISTRY_PATH
    if not path.exists():
        return {}
    registry: dict[str, str] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            short_name = (row.get("short_name") or "").strip()
            full_name = (row.get("name") or "").strip()
            if short_name and full_name:
                registry[short_name] = full_name
    return registry


def _map_row(
    headers: list[str], row: list[str], participant_registry: dict[str, str] | None = None
) -> dict | None:
    norm_headers = [_normalize_header(h) for h in headers]
    header_index = {h: i for i, h in enumerate(norm_headers)}

    out: dict[str, str] = {}
    for field, aliases in _COLUMN_ALIASES.items():
        idx = _find_column(header_index, aliases)
        if idx is None:
            if field == "auction_month":
                continue  # may still be derivable from start_date below
            return None  # required column missing -- skip row gracefully
        out[field] = row[idx]

    if "auction_month" not in out:
        start_idx = _find_column(header_index, _OPTIONAL_COLUMN_ALIASES["start_date"])
        derived = _derive_auction_month(row[start_idx]) if start_idx is not None else None
        if derived is None:
            return None
        out["auction_month"] = derived

    bid_type_idx = _find_column(header_index, _OPTIONAL_COLUMN_ALIASES["bid_type"])
    bid_type = row[bid_type_idx].strip().upper() if bid_type_idx is not None else "BUY"

    award_type_idx = _find_column(header_index, _OPTIONAL_COLUMN_ALIASES["award_type"])
    award_type = row[award_type_idx].strip().upper() if award_type_idx is not None else None

    try:
        price = float(out["clearing_price"])
        mw = float(out["awarded_mw"])
    except (TypeError, ValueError):
        return None

    out["clearing_price"] = price
    out["awarded_mw"] = -mw if bid_type == "SELL" else mw
    out["crr_type"] = _normalize_crr_type_value(out["crr_type"])
    out["time_of_use"] = _normalize_tou_value(out["time_of_use"])
    out["award_type"] = award_type if award_type in ("PREAWARD", "STANDARD") else "STANDARD"

    short_code = out["participant"].strip()
    registry = participant_registry or {}
    out["participant"] = registry.get(short_code, short_code)
    out["participant_short_code"] = short_code

    out["is_synthetic"] = False
    return out


def _load_real_csvs_from(directory: Path, participant_registry: dict[str, str] | None = None) -> list[dict]:
    if not directory.exists():
        return []
    records: list[dict] = []
    for csv_path in sorted(directory.glob("*.csv")):
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
            except StopIteration:
                continue
            for row in reader:
                if not row:
                    continue
                mapped = _map_row(headers, row, participant_registry)
                if mapped:
                    records.append(mapped)
    return records


def _load_real_csvs() -> list[dict]:
    return _load_real_csvs_from(RAW_DIR)


BULK_AUCTION_DIR = RAW_DIR / "crr_auction"
PARTICIPANT_REGISTRY_PATH = DATA_DIR / "reference" / "participants.csv"


def load_bulk_real_auction_data() -> tuple[list[dict], str, str | None]:
    """Real, bulk-downloaded ERCOT CRR Monthly Auction Results (see
    backend/scripts/fetch_real_ercot_data.py) joined against the real
    participant registry -- this is the data source the Streamlit app
    uses. Deliberately separate from load_records()'s SQL/flat-CSV/
    synthetic tiers (which read from RAW_DIR directly, not
    RAW_DIR/'crr_auction') so committing this bulk real data into the repo
    cannot change the FastAPI backend's existing, tested behavior. Falls
    back to load_records() if the bulk directory is empty or missing."""
    registry = _load_participant_registry(PARTICIPANT_REGISTRY_PATH)
    records = _load_real_csvs_from(BULK_AUCTION_DIR, registry)
    if records:
        return records, SOURCE_CSV, None
    return load_records()


def load_records() -> tuple[list[dict], str, str | None]:
    """
    Returns (records, source_label, warning).

    source_label is one of SOURCE_SQL / SOURCE_CSV / SOURCE_SYNTHETIC,
    telling the caller exactly which tier actually served the data.

    warning is None on a clean resolution, or a human-readable string if
    SQL was configured but could not be used (so a misconfigured
    production deployment is surfaced to the API/UI instead of silently
    serving demo data and looking fine).
    """
    warning = None

    if db.is_sql_configured():
        try:
            records = db.load_records_from_sql()
            if records:
                return records, SOURCE_SQL, None
            warning = (
                "SQL Server is configured and reachable, but the "
                "crr_auction_records table returned zero rows. Falling back."
            )
        except db.SqlBackendError as e:
            warning = f"SQL Server is configured but could not be used: {e}. Falling back."

    real_csv = _load_real_csvs()
    if real_csv:
        return real_csv, SOURCE_CSV, warning

    return records_as_dicts(), SOURCE_SYNTHETIC, warning
