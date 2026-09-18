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

# Column names as published in ERCOT's CRR Auction Results reports
# (NP7-802-M Long-Term Auction Results / NP7-803-M Monthly Auction Results).
# ERCOT's exact header casing has varied slightly across format revisions,
# so we match case-insensitively and accept a couple of known aliases.
_COLUMN_ALIASES = {
    "auction_month": {"auctionid", "auction", "auctionmonth", "deliverymonth"},
    "source": {"sourcelocation", "source", "sourcesettlementpoint"},
    "sink": {"sinklocation", "sink", "sinksettlementpoint"},
    "crr_type": {"crrtype", "type"},
    "time_of_use": {"timeofuse", "tou", "hourtype"},
    "clearing_price": {"crrclearingprice", "clearingprice", "shadowpriceperm wh".replace(" ", ""),
                        "shadowpricepermwh"},
    "awarded_mw": {"mw", "awardedquantity", "crmquantity", "quantity"},
    "participant": {"crraccountholder", "accountholder", "participant", "marketparticipant"},
}


def _normalize_header(h: str) -> str:
    return h.strip().lower().replace(" ", "").replace("_", "")


def _map_row(headers: list[str], row: list[str]) -> dict | None:
    norm_headers = [_normalize_header(h) for h in headers]
    out = {}
    for field, aliases in _COLUMN_ALIASES.items():
        idx = None
        for i, h in enumerate(norm_headers):
            if h in aliases:
                idx = i
                break
        if idx is None:
            return None  # required column missing -- skip file gracefully
        out[field] = row[idx]

    try:
        out["clearing_price"] = float(out["clearing_price"])
        out["awarded_mw"] = float(out["awarded_mw"])
    except (TypeError, ValueError):
        return None

    out["crr_type"] = out["crr_type"].strip().upper()
    out["time_of_use"] = out["time_of_use"].strip().upper()
    out["is_synthetic"] = False
    return out


def _load_real_csvs() -> list[dict]:
    if not RAW_DIR.exists():
        return []
    records: list[dict] = []
    for csv_path in sorted(RAW_DIR.glob("*.csv")):
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
            except StopIteration:
                continue
            for row in reader:
                if not row:
                    continue
                mapped = _map_row(headers, row)
                if mapped:
                    records.append(mapped)
    return records


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
