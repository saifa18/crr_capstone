# Real ERCOT Data + Market Intelligence + Streamlit Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace synthetic CRR auction/participant data with real, bulk-downloaded ERCOT data; add data-driven "hot paths" and participant-strategy market intelligence; add real ERCOT weather-zone mapping with seasonality; and rebuild the shareable web app on Streamlit, reading the bundled real data directly so the whole project folder works standalone when zipped and moved elsewhere.

**Architecture:** Backend stays Python-pure (`backend/app/*.py`: domain, ingestion, analytics, scoring, weather_zones) with zero web-framework coupling. Two consumers sit on top, unchanged relative to each other: the existing FastAPI app (`backend/app/main.py`, untouched, still serves SQL/flat-CSV/synthetic tiers exactly as before) and a new Streamlit app (`streamlit_app/`) that imports the same backend modules directly (no HTTP hop) and reads a separately-committed bulk real dataset (`data/raw/crr_auction/`, `data/reference/participants.csv`). The two consumers never share a data directory, so enabling real bulk data for Streamlit cannot change FastAPI's existing (tested) behavior.

**Tech Stack:** Python 3.11+, FastAPI (existing, untouched), Streamlit, pytest, `requests`, `openpyxl` (new backend dep, for reading the real ERCOT participant-list `.xlsx`).

## Global Constraints

- Every existing FastAPI test (93 tests) must keep passing unmodified — real bulk data lives in a directory FastAPI's ingestion tier never reads.
- Every new/changed function is a pure, dict-in/dict-out function, testable without I/O (per this project's existing architecture rule — see `docs/lessons_learned_and_future_work.md` lesson 4).
- No unverified claims: every module docstring states plainly what was and wasn't verified, matching this project's existing honesty policy for synthetic data and live integrations.
- Commit after every task.
- React frontend (`frontend/`) is not touched in this plan (kept as an untouched reference, per explicit decision).
- `backend/app/main.py` is not modified in this plan (kept as-is, per explicit decision) — new analytics functions are consumed by Streamlit only.

---

### Task 1: Initialize git and establish a baseline commit

**Files:**
- Create: `.git/` (via `git init`)
- Modify: none

**Interfaces:** None — this task has no code interfaces, it just makes every later task's "commit" step possible.

- [ ] **Step 1: Initialize the repository**

```bash
cd /Users/saif_ansari/Downloads/ercot-crr-analytics
git init
git add -A
git status
```

Expected: a new `.git/` directory, and `git status` lists the existing project files as staged (backend/, frontend/, data/, docs/, presentation/, README.md, .gitignore).

- [ ] **Step 2: Commit the baseline**

```bash
git commit -m "chore: initial commit of ercot-crr-analytics v1.3 baseline"
git log --oneline
```

Expected: one commit, `git log` shows it.

---

### Task 2: Make `backend/app/db.py` importable without SQLAlchemy/pyodbc installed

**Why this task exists:** `db.py` currently does `from sqlalchemy import (...)` and `metadata = MetaData()` at module scope (`backend/app/db.py:72-86`). `ingestion.py` does `from . import db` at module scope too. That means simply importing `app.ingestion` (which the new Streamlit app needs to do) requires `sqlalchemy` AND its `pyodbc` driver to be installed — and `pyodbc` needs a system-level ODBC driver to even build, which Streamlit Community Cloud's minimal container doesn't have. Making the SQLAlchemy imports lazy (only imported inside the functions that use them) keeps the FastAPI/SQL Server path working exactly as before while letting Streamlit run with zero SQL dependencies.

**Files:**
- Modify: `backend/app/db.py:67-108, 169-232`
- Test: `backend/tests/test_db.py` (add one test)

**Interfaces:**
- Consumes: nothing new
- Produces: `db.is_sql_configured()`, `db.get_engine()`, `db.init_db()`, `db.load_records_from_sql()` — same names/signatures/behavior as before, just lazy-imported internally. `ingestion.py` and everything downstream is unaffected.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_db.py`:

```python
def test_db_module_importable_without_sqlalchemy(monkeypatch):
    """Simulates sqlalchemy not being installed at all (as on a minimal
    Streamlit Cloud container) and verifies `app.db` still imports and its
    is_sql_configured() check still works -- this is what lets the
    Streamlit app import app.ingestion without needing sqlalchemy/pyodbc."""
    import importlib
    import sys

    monkeypatch.setitem(sys.modules, "sqlalchemy", None)
    monkeypatch.setitem(sys.modules, "sqlalchemy.exc", None)
    monkeypatch.delitem(sys.modules, "app.db", raising=False)

    reloaded = importlib.import_module("app.db")
    assert reloaded.is_sql_configured() in (True, False)

    monkeypatch.delitem(sys.modules, "app.db", raising=False)
    importlib.import_module("app.db")  # restore a normal import for later tests
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_db.py::test_db_module_importable_without_sqlalchemy -v`
Expected: FAIL — `ModuleNotFoundError` or `ImportError` raised while importing `app.db`, because the current module-level `from sqlalchemy import (...)` executes immediately.

- [ ] **Step 3: Move SQLAlchemy imports inside the functions that use them**

In `backend/app/db.py`, replace lines 67-108:

```python
from __future__ import annotations

import os
from typing import Any

DEFAULT_TABLE_NAME = "crr_auction_records"

metadata = None


def _get_metadata():
    global metadata
    if metadata is None:
        from sqlalchemy import MetaData
        metadata = MetaData()
    return metadata


def _table(name: str):
    """Builds (or returns the already-built) Table object for a given
    table name. `extend_existing=True` makes repeated calls with the same
    name safe (e.g. across multiple requests) rather than raising on a
    duplicate definition."""
    from sqlalchemy import Column, Float, String, Table

    md = _get_metadata()
    if name in md.tables:
        return md.tables[name]
    return Table(
        name,
        md,
        Column("auction_month", String(7)),
        Column("source", String(50)),
        Column("sink", String(50)),
        Column("crr_type", String(20)),
        Column("time_of_use", String(20)),
        Column("clearing_price", Float),
        Column("awarded_mw", Float),
        Column("participant", String(200)),
        extend_existing=True,
    )
```

(This replaces the old module-level `from sqlalchemy import (...)`, `from sqlalchemy.exc import SQLAlchemyError`, `metadata = MetaData()`, and `_table()` — everything up to and including the old `_table` function's closing line, right before `class SqlBackendError(RuntimeError):`. The docstring at the top of the file, lines 1-65, is unchanged — leave it as-is.)

Then replace `get_engine` (old lines 169-189):

```python
def get_engine(url: str | None = None):
    """Creates a SQLAlchemy engine for the configured (or given) database.
    Does not connect yet -- SQLAlchemy engines are lazy; the first real
    query is what actually opens a connection and is where a bad
    host/credentials/driver surfaces.

    Sets an explicit short connect timeout (SQL_SERVER_CONNECT_TIMEOUT_SECONDS,
    default 10) so an unreachable or misconfigured server fails fast with a
    clear error instead of hanging a request for the OS-level default
    (which can be 60+ seconds) -- this matters a lot in a web API, where a
    hung connection attempt blocks a request thread, not just an
    interactive script."""
    from sqlalchemy import create_engine

    resolved_url = url or _build_connection_url()
    timeout_seconds = int(os.environ.get("SQL_SERVER_CONNECT_TIMEOUT_SECONDS", "10"))
    try:
        connect_args = {"timeout": timeout_seconds} if resolved_url.startswith("mssql+pyodbc") else {}
        return create_engine(resolved_url, pool_pre_ping=True, connect_args=connect_args)
    except SqlBackendError:
        raise
    except Exception as e:  # pragma: no cover - defensive, e.g. malformed URL
        raise SqlBackendError(f"Could not build a database engine: {e}") from e


def init_db(engine, table_name: str | None = None) -> None:
    """Creates the expected table if it doesn't exist yet. Safe to call
    against an existing, already-populated table (no-op in that case).
    Mainly useful for a quick local smoke test against SQLite -- against a
    real production SQL Server, a DBA-managed schema
    (see scripts/create_sql_server_schema.sql) is usually preferred."""
    from sqlalchemy.exc import SQLAlchemyError

    table_name = table_name or os.environ.get("SQL_SERVER_TABLE", DEFAULT_TABLE_NAME)
    table = _table(table_name)
    try:
        table.metadata.create_all(engine, tables=[table], checkfirst=True)
    except SQLAlchemyError as e:
        raise SqlBackendError(f"Could not create/verify table '{table_name}': {e}") from e


def load_records_from_sql(engine=None, table_name: str | None = None) -> list[dict[str, Any]]:
    """Queries every row from the CRR auction records table and returns
    them in the exact dict shape analytics.py/scoring.py already expect --
    so once this succeeds, the rest of the backend needs zero changes.

    Raises SqlBackendError with a clear, actionable message on any
    connection or query failure -- a bad host, bad credentials, a missing
    table, a missing ODBC driver, etc. all get a specific, readable
    explanation rather than a raw driver traceback.
    """
    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError

    table_name = table_name or os.environ.get("SQL_SERVER_TABLE", DEFAULT_TABLE_NAME)
    eng = engine or get_engine()
    table = _table(table_name)

    try:
        with eng.connect() as conn:
            rows = conn.execute(select(table)).mappings().all()
    except SQLAlchemyError as e:
        raise SqlBackendError(
            f"Could not query table '{table_name}' from the configured SQL "
            f"database. Common causes: the server is unreachable (check "
            f"SQL_SERVER_HOST/port and that the machine running this backend "
            f"can reach it over the network), the table doesn't exist yet "
            f"(see scripts/create_sql_server_schema.sql), credentials are "
            f"wrong, or the ODBC driver named in SQL_SERVER_DRIVER isn't "
            f"installed on this machine. Underlying error: {e}"
        ) from e

    records = []
    for row in rows:
        records.append({
            "auction_month": row["auction_month"],
            "source": row["source"],
            "sink": row["sink"],
            "crr_type": str(row["crr_type"]).strip().upper(),
            "time_of_use": str(row["time_of_use"]).strip().upper(),
            "clearing_price": float(row["clearing_price"]),
            "awarded_mw": float(row["awarded_mw"]),
            "participant": row["participant"],
            "is_synthetic": False,
        })
    return records
```

Note: `Engine` type hints are removed from signatures (`engine: Engine | None = None` → `engine=None`) since `Engine` is no longer imported at module scope — the docstrings already say what these are. Everything between `_table` and `get_engine` (i.e. `SqlBackendError`, `is_sql_configured`, `_build_connection_url`) is unchanged; leave those exactly as they are today.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_db.py -v`
Expected: PASS, all tests including the new one.

- [ ] **Step 5: Run the full existing suite to confirm no regression**

Run: `cd backend && python -m pytest -q`
Expected: PASS, same test count as before this task (93+1 new = 94).

- [ ] **Step 6: Commit**

```bash
git add backend/app/db.py backend/tests/test_db.py
git commit -m "refactor: lazy-import sqlalchemy in db.py so app.ingestion is importable without it"
```

---

### Task 3: Fix real-ERCOT-column parsing bugs in `backend/app/ingestion.py`

**Why this task exists:** downloading and parsing a real ERCOT Monthly Auction Results file during design (`Common_MarketResults_*.csv`) found that the current `_COLUMN_ALIASES`/`_map_row` logic would misparse it: it has both `HedgeType` (OBL/OPT — the real Option/Obligation column) and `CRRType` (PREAWARD/STANDARD — an unrelated field) and the current code's `crr_type` alias points at `CRRType`, so it would end up storing "PREAWARD"/"STANDARD" as if it were "OBLIGATION"/"OPTION". There's also no `auction_month` column at all (must derive from `StartDate`), `TimeOfUse` values are `PeakWD`/`PeakWE`/`Off-peak` (not the app's `PEAK_WD`/`PEAK_WE`/`OFF_PEAK`), `HedgeType` values are `OBL`/`OPT` abbreviations, and a `BidType` column (`BUY`/`SELL`) needs to sign `awarded_mw` so a participant's net position (not gross double-counted MW) flows through every existing sum-based aggregation with no changes to those functions.

**Files:**
- Modify: `backend/app/ingestion.py:57-120`
- Test: `backend/tests/test_ingestion.py` (new file)

**Interfaces:**
- Consumes: nothing new
- Produces: `ingestion._map_row(headers, row, participant_registry=None) -> dict | None` (now takes an optional third arg), `ingestion._load_real_csvs_from(directory, participant_registry=None) -> list[dict]` (new, generalizes the old `_load_real_csvs`), `ingestion._load_participant_registry(path=None) -> dict[str, str]` (new), `ingestion.load_bulk_real_auction_data() -> tuple[list[dict], str, str | None]` (new — this is what Task 8's Streamlit `data_loader.py` calls), `ingestion.BULK_AUCTION_DIR` and `ingestion.PARTICIPANT_REGISTRY_PATH` (new module-level `Path` constants). `ingestion.load_records()` keeps its exact existing signature/behavior (flat `RAW_DIR`, SQL→CSV→synthetic tiers) — untouched.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_ingestion.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from app import ingestion


REAL_HEADERS = [
    "CRR_ID", "OriginalCRR_ID", "AccountHolder", "HedgeType", "BidType",
    "CRRType", "Source", "Sink", "StartDate", "EndDate", "TimeOfUse",
    "Bid24Hour", "MW", "ShadowPricePerMWH",
]


def _real_row(
    account_holder="XSARAC", hedge_type="OPT", bid_type="BUY", crr_type="PREAWARD",
    source="LONEWOLF_ALL", sink="PIONR_DJ_RN", start_date="10/01/2026",
    end_date="10/31/2026", tou="PeakWD", mw="5.8", price="2.727068",
):
    return [
        "225506479", "", account_holder, hedge_type, bid_type, crr_type,
        source, sink, start_date, end_date, tou, "No", mw, price,
    ]


def test_map_row_reads_hedgetype_not_crrtype_for_crr_type():
    mapped = ingestion._map_row(REAL_HEADERS, _real_row(hedge_type="OBL", crr_type="STANDARD"))
    assert mapped["crr_type"] == "OBLIGATION"
    assert mapped["award_type"] == "STANDARD"


def test_map_row_normalizes_hedgetype_abbreviations():
    assert ingestion._map_row(REAL_HEADERS, _real_row(hedge_type="OPT"))["crr_type"] == "OPTION"
    assert ingestion._map_row(REAL_HEADERS, _real_row(hedge_type="OBL"))["crr_type"] == "OBLIGATION"


def test_map_row_normalizes_time_of_use_values():
    assert ingestion._map_row(REAL_HEADERS, _real_row(tou="PeakWD"))["time_of_use"] == "PEAK_WD"
    assert ingestion._map_row(REAL_HEADERS, _real_row(tou="PeakWE"))["time_of_use"] == "PEAK_WE"
    assert ingestion._map_row(REAL_HEADERS, _real_row(tou="Off-peak"))["time_of_use"] == "OFF_PEAK"


def test_map_row_derives_auction_month_from_start_date():
    mapped = ingestion._map_row(REAL_HEADERS, _real_row(start_date="10/01/2026"))
    assert mapped["auction_month"] == "2026-10"


def test_map_row_signs_awarded_mw_by_bid_type():
    buy = ingestion._map_row(REAL_HEADERS, _real_row(bid_type="BUY", mw="5.8"))
    sell = ingestion._map_row(REAL_HEADERS, _real_row(bid_type="SELL", mw="5.8"))
    assert buy["awarded_mw"] == 5.8
    assert sell["awarded_mw"] == -5.8


def test_map_row_preserves_price_sign_regardless_of_bid_type():
    buy = ingestion._map_row(REAL_HEADERS, _real_row(bid_type="BUY", price="-1.5"))
    sell = ingestion._map_row(REAL_HEADERS, _real_row(bid_type="SELL", price="-1.5"))
    assert buy["clearing_price"] == -1.5
    assert sell["clearing_price"] == -1.5


def test_map_row_joins_participant_registry_for_real_name():
    registry = {"XSARAC": "SOME REAL COMPANY LLC (CRRAH)"}
    mapped = ingestion._map_row(REAL_HEADERS, _real_row(account_holder="XSARAC"), registry)
    assert mapped["participant"] == "SOME REAL COMPANY LLC (CRRAH)"
    assert mapped["participant_short_code"] == "XSARAC"


def test_map_row_falls_back_to_short_code_when_registry_missing_entry():
    mapped = ingestion._map_row(REAL_HEADERS, _real_row(account_holder="XUNKNOWN"), {})
    assert mapped["participant"] == "XUNKNOWN"
    assert mapped["participant_short_code"] == "XUNKNOWN"


def test_map_row_award_type_defaults_to_standard_when_column_absent():
    old_headers = ["Source", "Sink", "CRRType", "TimeOfUse", "MW", "ClearingPrice",
                   "AccountHolder", "AuctionMonth"]
    old_row = ["HB_WEST", "HB_HOUSTON", "OBLIGATION", "PEAK_WD", "10.0", "5.0", "X", "2024-01"]
    mapped = ingestion._map_row(old_headers, old_row)
    assert mapped["crr_type"] == "OBLIGATION"
    assert mapped["award_type"] == "STANDARD"


def test_load_participant_registry_reads_short_name_to_name(tmp_path):
    path = tmp_path / "participants.csv"
    path.write_text("short_name,name,duns_number\nXAESMT,AES MARKETING AND TRADING LLC (CRRAH),1187367255000\n")
    registry = ingestion._load_participant_registry(path)
    assert registry["XAESMT"] == "AES MARKETING AND TRADING LLC (CRRAH)"


def test_load_participant_registry_returns_empty_dict_when_missing(tmp_path):
    assert ingestion._load_participant_registry(tmp_path / "nope.csv") == {}


def test_load_real_csvs_from_reads_all_csvs_in_directory(tmp_path):
    (tmp_path / "a.csv").write_text(
        ",".join(REAL_HEADERS) + "\n" + ",".join(_real_row(source="HB_WEST", sink="HB_HOUSTON"))
    )
    records = ingestion._load_real_csvs_from(tmp_path)
    assert len(records) == 1
    assert records[0]["source"] == "HB_WEST"
    assert records[0]["is_synthetic"] is False


def test_load_bulk_real_auction_data_falls_back_to_load_records_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(ingestion, "BULK_AUCTION_DIR", tmp_path / "does_not_exist")
    monkeypatch.setattr(ingestion, "PARTICIPANT_REGISTRY_PATH", tmp_path / "no_registry.csv")
    records, source, warning = ingestion.load_bulk_real_auction_data()
    assert source == ingestion.SOURCE_SYNTHETIC
    assert len(records) > 0


def test_load_bulk_real_auction_data_uses_real_files_when_present(tmp_path, monkeypatch):
    bulk_dir = tmp_path / "crr_auction"
    bulk_dir.mkdir()
    (bulk_dir / "2026-10_MarketResults.csv").write_text(
        ",".join(REAL_HEADERS) + "\n" + ",".join(_real_row())
    )
    registry_path = tmp_path / "participants.csv"
    registry_path.write_text("short_name,name,duns_number\nXSARAC,REAL NAME LLC,123\n")

    monkeypatch.setattr(ingestion, "BULK_AUCTION_DIR", bulk_dir)
    monkeypatch.setattr(ingestion, "PARTICIPANT_REGISTRY_PATH", registry_path)

    records, source, warning = ingestion.load_bulk_real_auction_data()
    assert source == ingestion.SOURCE_CSV
    assert len(records) == 1
    assert records[0]["participant"] == "REAL NAME LLC"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_ingestion.py -v`
Expected: FAIL — `_map_row` doesn't accept a third argument, doesn't derive `auction_month`, doesn't sign MW, etc; `_load_real_csvs_from`, `_load_participant_registry`, `load_bulk_real_auction_data`, `BULK_AUCTION_DIR`, `PARTICIPANT_REGISTRY_PATH` don't exist yet.

- [ ] **Step 3: Replace the column-mapping section of `ingestion.py`**

In `backend/app/ingestion.py`, replace lines 57-120 (from `# Column names as published...` through the end of `_load_real_csvs`) with:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_ingestion.py -v`
Expected: PASS, all new tests.

- [ ] **Step 5: Run the full existing suite to confirm no regression**

Run: `cd backend && python -m pytest -q`
Expected: PASS, same behavior as before for every existing test (flat `RAW_DIR` is still empty in the test environment, so `load_records()` still returns synthetic data exactly as before).

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingestion.py backend/tests/test_ingestion.py
git commit -m "fix: parse real ERCOT auction column layout correctly (HedgeType, BUY/SELL netting, TOU normalization, participant registry join)"
```

---

### Task 4: Write the real-data fetch script

**Files:**
- Create: `backend/scripts/fetch_real_ercot_data.py`
- Create: `backend/scripts/__init__.py` (empty — makes the script importable from tests)
- Modify: `backend/requirements.txt` (add `openpyxl`)
- Test: `backend/tests/test_fetch_real_ercot_data.py` (new file)

**Interfaces:**
- Consumes: nothing from earlier tasks (standalone script)
- Produces: `fetch_real_ercot_data.list_documents(report_type_id, session) -> list[dict]`, `.month_key_from_friendly_name(name) -> str | None`, `.download_document(doc_id, session) -> bytes`, `.extract_market_results_csv(zip_bytes) -> bytes`, `.extract_crrah_participants(xlsx_bytes) -> list[dict]`, `.fetch_auction_results(session=None) -> list[Path]`, `.fetch_participant_registry(session=None) -> Path`, `.AUCTION_OUT_DIR`, `.PARTICIPANTS_OUT_PATH` (module-level `Path` constants — Task 5 runs this for real and Task 3's `ingestion.BULK_AUCTION_DIR`/`PARTICIPANT_REGISTRY_PATH` must point at the same paths).

- [ ] **Step 1: Add the new dependency**

In `backend/requirements.txt`, add a new line:

```
openpyxl==3.1.5
```

- [ ] **Step 2: Install it**

```bash
cd backend && pip install -r requirements.txt
```

Expected: `openpyxl` installs successfully (pure-Python, no system deps).

- [ ] **Step 3: Write the failing tests**

Create `backend/scripts/__init__.py` (empty file).

Create `backend/tests/test_fetch_real_ercot_data.py`:

```python
from __future__ import annotations

import io
import zipfile
from unittest.mock import MagicMock

import pytest

from scripts import fetch_real_ercot_data as fetch


def test_month_key_from_friendly_name_parses_standard_pattern():
    assert fetch.month_key_from_friendly_name("OCT2026MonthlyCRRAuctionResults") == "2026-10"
    assert fetch.month_key_from_friendly_name("JAN2025MonthlyCRRAuctionResults") == "2025-01"


def test_month_key_from_friendly_name_returns_none_for_unrecognized_pattern():
    assert fetch.month_key_from_friendly_name("SomeOtherReport") is None


def _make_zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_extract_market_results_csv_finds_the_right_member():
    zip_bytes = _make_zip({
        "Common_AuctionBidsAndOffers_2026.OCT.Monthly.Auction_AUCTION.csv": b"irrelevant",
        "Common_MarketResults_2026.OCT.Monthly.Auction_AUCTION.csv": b"CRR_ID,Source\n1,HB_WEST\n",
    })
    csv_bytes = fetch.extract_market_results_csv(zip_bytes)
    assert csv_bytes == b"CRR_ID,Source\n1,HB_WEST\n"


def test_extract_market_results_csv_raises_if_missing():
    zip_bytes = _make_zip({"SomethingElse.csv": b"data"})
    with pytest.raises(ValueError, match="Common_MarketResults"):
        fetch.extract_market_results_csv(zip_bytes)


def test_list_documents_calls_correct_endpoint_and_parses_response():
    session = MagicMock()
    session.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"ListDocsByRptTypeRes": {"DocumentList": [
            {"Document": {"DocID": "123", "FriendlyName": "OCT2026MonthlyCRRAuctionResults",
                          "PublishDate": "2026-09-17T08:00:00-05:00"}}
        ]}},
    )
    docs = fetch.list_documents(11201, session)
    assert docs == [{"DocID": "123", "FriendlyName": "OCT2026MonthlyCRRAuctionResults",
                     "PublishDate": "2026-09-17T08:00:00-05:00"}]
    assert session.get.call_args.kwargs["params"] == {"reportTypeId": 11201}


def test_fetch_auction_results_skips_already_downloaded_months(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "AUCTION_OUT_DIR", tmp_path)
    existing = tmp_path / "2026-10_MarketResults.csv"
    existing.write_text("already here")

    session = MagicMock()
    session.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"ListDocsByRptTypeRes": {"DocumentList": [
            {"Document": {"DocID": "999", "FriendlyName": "OCT2026MonthlyCRRAuctionResults",
                          "PublishDate": "2026-09-17T08:00:00-05:00"}}
        ]}},
    )
    written = fetch.fetch_auction_results(session=session)
    assert written == []
    assert existing.read_text() == "already here"


def test_extract_crrah_participants_parses_sheet():
    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.title = "Sheet1"
    crrah = wb.create_sheet("CRRAH")
    crrah.append(["Some", "Header", "Junk"])
    crrah.append(["NAME", "SHORT NAME", "DUNS NUMBER"])
    crrah.append(["AES MARKETING AND TRADING LLC (CRRAH)", "XAESMT", "1187367255000"])
    buf = io.BytesIO()
    wb.save(buf)

    rows = fetch.extract_crrah_participants(buf.getvalue())
    assert rows == [{
        "name": "AES MARKETING AND TRADING LLC (CRRAH)",
        "short_name": "XAESMT",
        "duns_number": "1187367255000",
    }]
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_fetch_real_ercot_data.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.fetch_real_ercot_data'`.

- [ ] **Step 5: Write the script**

Create `backend/scripts/fetch_real_ercot_data.py`:

```python
"""
Downloads real ERCOT CRR Monthly Auction Results (NP7-803-M) and the real
Market Participants List (NP12-215-ER) directly from ERCOT's public MIS
legacy servlet endpoints -- confirmed reachable and unauthenticated during
this project's 2026-09 real-data investigation, contradicting this
project's own earlier assumption (see domain.py's original docstring and
lessons_learned_and_future_work.md) that CRR auction data required a
browser session. Lesson 6 already in this project applies again: "an
earlier no is worth re-checking."

Run from backend/: `python scripts/fetch_real_ercot_data.py`

Idempotent: re-running only downloads auction months not already present
in data/raw/crr_auction/, so this is safe to run again next month after a
new auction posts. The participant registry is always re-downloaded and
overwritten (it's a single small file, refreshed daily by ERCOT).

Writes:
  data/raw/crr_auction/<YYYY-MM>_MarketResults.csv  (one per auction month)
  data/reference/participants.csv                    (short_name,name,duns_number)

Deliberately separate from ingestion.py's flat data/raw/*.csv tier (used by
the FastAPI backend's SQL->CSV->synthetic priority) -- see
ingestion.load_bulk_real_auction_data()'s docstring for why.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path

import requests

DOC_LIST_URL = "https://www.ercot.com/misapp/servlets/IceDocListJsonWS"
DOWNLOAD_URL = "https://www.ercot.com/misdownload/servlets/mirDownload"
AUCTION_REPORT_TYPE_ID = 11201       # NP7-803-M, Monthly Auction Results
PARTICIPANT_REPORT_TYPE_ID = 21129   # NP12-215-ER, List of Market Participants
REQUEST_TIMEOUT = 60

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
AUCTION_OUT_DIR = DATA_DIR / "raw" / "crr_auction"
PARTICIPANTS_OUT_PATH = DATA_DIR / "reference" / "participants.csv"

_MONTH_NAME_RE = re.compile(r"^([A-Z]{3})(\d{4})MonthlyCRRAuctionResults$")
_MONTH_NUMBERS = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
    "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}


def list_documents(report_type_id: int, session: requests.Session) -> list[dict]:
    """Real, public, unauthenticated ERCOT MIS document list for a report
    type -- e.g. every currently-retained Monthly Auction Results zip."""
    resp = session.get(DOC_LIST_URL, params={"reportTypeId": report_type_id}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return [d["Document"] for d in data["ListDocsByRptTypeRes"]["DocumentList"]]


def month_key_from_friendly_name(friendly_name: str) -> str | None:
    """'OCT2026MonthlyCRRAuctionResults' -> '2026-10'. Returns None for any
    name that doesn't match this exact pattern (defensive against ERCOT
    changing its naming convention without notice)."""
    match = _MONTH_NAME_RE.match(friendly_name)
    if not match:
        return None
    month_abbr, year = match.groups()
    month_num = _MONTH_NUMBERS.get(month_abbr)
    if month_num is None:
        return None
    return f"{year}-{month_num}"


def download_document(doc_id: str, session: requests.Session) -> bytes:
    resp = session.get(DOWNLOAD_URL, params={"doclookupId": doc_id}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.content


def extract_market_results_csv(zip_bytes: bytes) -> bytes:
    """Pulls just the Common_MarketResults_*.csv member out of a Monthly
    Auction Results zip -- the awarded-results file this project needs.
    The zip also contains AuctionBidsAndOffers/BaseLoading/
    BindingConstraint/SourceAndSinkShadowPrices files (and XML duplicates
    of everything), multiple times larger and not needed here, so they're
    never extracted to disk at all."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if name.startswith("Common_MarketResults_") and name.endswith(".csv"):
                return zf.read(name)
    raise ValueError("No Common_MarketResults_*.csv member found in this zip")


def extract_crrah_participants(xlsx_bytes: bytes) -> list[dict[str, str]]:
    """Pulls the CRRAH sheet (NAME, SHORT NAME, DUNS NUMBER columns) out of
    the real Market Participants List workbook."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True)
    ws = wb["CRRAH"]
    out = []
    header_seen = False
    for row in ws.iter_rows(values_only=True):
        if not header_seen:
            if row and row[0] == "NAME":
                header_seen = True
            continue
        if not row or not row[0]:
            continue
        name, short_name, duns = row[0], row[1], row[2]
        out.append({
            "name": str(name).strip(),
            "short_name": str(short_name).strip(),
            "duns_number": str(duns).strip() if duns is not None else "",
        })
    return out


def fetch_auction_results(session: requests.Session | None = None) -> list[Path]:
    """Downloads every currently-retained real Monthly Auction Results file
    not already present locally. Returns the list of newly-written paths
    (empty if everything was already up to date)."""
    sess = session or requests.Session()
    AUCTION_OUT_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for doc in list_documents(AUCTION_REPORT_TYPE_ID, sess):
        month_key = month_key_from_friendly_name(doc["FriendlyName"])
        if month_key is None:
            continue
        out_path = AUCTION_OUT_DIR / f"{month_key}_MarketResults.csv"
        if out_path.exists():
            continue
        zip_bytes = download_document(doc["DocID"], sess)
        csv_bytes = extract_market_results_csv(zip_bytes)
        out_path.write_bytes(csv_bytes)
        written.append(out_path)
        print(f"wrote {out_path} ({len(csv_bytes):,} bytes)")
    return written


def fetch_participant_registry(session: requests.Session | None = None) -> Path:
    """Downloads the current real Market Participants List and writes the
    CRRAH sheet as a small, plain CSV (short_name -> real company name)."""
    sess = session or requests.Session()
    docs = list_documents(PARTICIPANT_REPORT_TYPE_ID, sess)
    if not docs:
        raise RuntimeError("ERCOT returned no Market Participants List documents")
    latest = max(docs, key=lambda d: d["PublishDate"])
    xlsx_bytes = download_document(latest["DocID"], sess)
    rows = extract_crrah_participants(xlsx_bytes)

    PARTICIPANTS_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PARTICIPANTS_OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["short_name", "name", "duns_number"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {PARTICIPANTS_OUT_PATH} ({len(rows)} participants)")
    return PARTICIPANTS_OUT_PATH


def main() -> None:
    fetch_auction_results()
    fetch_participant_registry()


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_fetch_real_ercot_data.py -v`
Expected: PASS, all tests.

- [ ] **Step 7: Run the full suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS (99+ tests now).

- [ ] **Step 8: Commit**

```bash
git add backend/scripts/fetch_real_ercot_data.py backend/scripts/__init__.py backend/tests/test_fetch_real_ercot_data.py backend/requirements.txt
git commit -m "feat: add script to fetch real ERCOT CRR auction results and participant registry"
```

---

### Task 5: Run the fetch script for real and commit the real data

**Files:**
- Create: `data/raw/crr_auction/*.csv` (approx. 13 files, one per real auction month)
- Create: `data/reference/participants.csv`

**Interfaces:** None — this is a data-only task, no new code.

- [ ] **Step 1: Run the script against real ERCOT servers**

```bash
cd backend
python scripts/fetch_real_ercot_data.py
```

Expected output: one `wrote data/raw/crr_auction/<month>_MarketResults.csv (N bytes)` line per currently-retained auction month (ERCOT retains roughly the trailing 13 months, so expect around 13 files), followed by `wrote data/reference/participants.csv (N participants)`.

- [ ] **Step 2: Verify the real data landed correctly**

```bash
ls -la ../data/raw/crr_auction/
wc -l ../data/reference/participants.csv
head -3 ../data/raw/crr_auction/*.csv | head -20
```

Expected: multiple real CSV files with headers matching `CRR_ID,OriginalCRR_ID,AccountHolder,HedgeType,BidType,CRRType,Source,Sink,StartDate,EndDate,TimeOfUse,Bid24Hour,MW,ShadowPricePerMWH`; `participants.csv` has several hundred rows.

- [ ] **Step 3: Sanity-check end-to-end through the ingestion layer**

```bash
python -c "
from app.ingestion import load_bulk_real_auction_data
records, source, warning = load_bulk_real_auction_data()
print('source:', source)
print('record count:', len(records))
print('sample:', records[0])
names = {r['participant'] for r in records}
print('distinct participants:', len(names))
print('a real-looking name present:', any('LLC' in n or 'LP' in n for n in names))
"
```

Expected: `source: ercot_mis_real`, a record count in the hundreds of thousands, a sample record with a real-looking `participant` name (not a bare short code like `XSARAC`), and `a real-looking name present: True`.

- [ ] **Step 4: Commit the real data**

```bash
cd /Users/saif_ansari/Downloads/ercot-crr-analytics
git add data/raw/crr_auction data/reference
git commit -m "data: add real ERCOT CRR auction results (13 months) and participant registry"
```

---

### Task 6: Add `discover_top_pairs`, `top_paths`, `participant_strategy` to `backend/app/analytics.py`

**Files:**
- Modify: `backend/app/analytics.py` (append new functions after `recent_auction_month`)
- Test: `backend/tests/test_analytics.py` (append new tests)

**Interfaces:**
- Consumes: `filter_records`, `all_pairs`, `monthly_price_series` (all already in `analytics.py`)
- Produces: `analytics.discover_top_pairs(records, n=30) -> list[dict]` (each dict: `source`, `sink`, `total_notional`, `participant_count`, `recurring_months`, `months_tracked`), `analytics.top_paths(records, months_back=12, n=10) -> list[dict]` (same shape plus `reason: str`), `analytics.participant_strategy(participant_name, records) -> dict` (`participant`, `certificate_count`, `option_pct`, `obligation_pct`, `net_mw`, `preaward_pct`, `top_pairs`) — these three are consumed by Task 8's `streamlit_app/lib/data_loader.py`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_analytics.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_analytics.py -v -k "discover_top_pairs or top_paths or participant_strategy"`
Expected: FAIL — `AttributeError: module 'app.analytics' has no attribute 'discover_top_pairs'` etc.

- [ ] **Step 3: Implement the functions**

Append to `backend/app/analytics.py` (after `recent_auction_month`, keeping existing `import statistics` and `from collections import defaultdict` at the top of the file — both already present):

```python
def discover_top_pairs(records: list[dict], n: int = 30) -> list[dict]:
    """
    Ranks every distinct Source/Sink pair present in `records` by total
    notional (gross MW-weighted dollar activity) and returns the top `n`,
    with participant count and a recurring-congestion signal. This
    replaces a fixed, hand-curated pair list with whatever the data itself
    says is actually active -- essential once real ERCOT auction data
    brings in thousands of one-off resource-node pairs alongside the
    liquid hub/load-zone corridors.

    Notional uses abs(awarded_mw) so a participant's netted BUY/SELL
    position (see ingestion.py) doesn't understate how much gross activity
    actually happened on a path -- a path with heavy two-way trading is
    "hot" even if positions mostly cancel out.

    "recurring_months" counts, out of the pair's own trailing 12 auction
    months, how many cleared with the same sign (positive/negative) as the
    pair's all-time average -- the same directional-consistency idea
    scoring.py already uses per-pair, exposed here as a plain count rather
    than a 0-100 score.
    """
    pairs = all_pairs(records)
    ranked = []
    for source, sink in pairs:
        pair_recs = filter_records(records, source=source, sink=sink)
        notional = sum(abs(r["awarded_mw"]) * abs(r["clearing_price"]) for r in pair_recs)
        participants = {r["participant"] for r in pair_recs}
        series = monthly_price_series(pair_recs)
        prices = [m["avg_clearing_price"] for m in series]
        recurring_months = 0
        if prices:
            avg = statistics.mean(prices)
            sign = 1 if avg >= 0 else -1
            trailing = prices[-12:]
            recurring_months = sum(1 for p in trailing if (p >= 0) == (sign >= 0))
        ranked.append({
            "source": source,
            "sink": sink,
            "total_notional": round(notional, 2),
            "participant_count": len(participants),
            "recurring_months": recurring_months,
            "months_tracked": len(prices),
        })
    ranked.sort(key=lambda p: p["total_notional"], reverse=True)
    return ranked[:n]


def top_paths(records: list[dict], months_back: int = 12, n: int = 10) -> list[dict]:
    """
    Thin, UI-facing wrapper around discover_top_pairs: the "Hot Paths"
    panel's data, each with a one-line, plain-language reason -- answers
    "what are the top sourcing paths people are looking at" directly.
    """
    top = discover_top_pairs(records, n=n)
    out = []
    for p in top:
        reason = (
            f"Congested the same direction in {p['recurring_months']} of its last "
            f"{min(p['months_tracked'], months_back)} months, "
            f"{p['participant_count']} active participants."
        )
        out.append({**p, "reason": reason})
    return out


def participant_strategy(participant_name: str, records: list[dict]) -> dict:
    """
    Per-participant strategy breakdown for one CRR Account Holder: how many
    certificates, Option vs. Obligation mix, net Buy/Sell position, how
    much of their activity is pre-existing (PREAWARD) vs. freshly won in
    the standard monthly auction, and their top corridors by notional.
    Answers "who's doing what" / "what's their strategy" directly rather
    than requiring a trader to page through raw rows.
    """
    n = len(records)
    if n == 0:
        return {
            "participant": participant_name,
            "certificate_count": 0,
            "option_pct": None,
            "obligation_pct": None,
            "net_mw": 0.0,
            "preaward_pct": None,
            "top_pairs": [],
        }

    option_count = sum(1 for r in records if r["crr_type"] == "OPTION")
    obligation_count = n - option_count
    net_mw = sum(r["awarded_mw"] for r in records)
    preaward_count = sum(1 for r in records if r.get("award_type", "STANDARD") == "PREAWARD")

    by_pair: dict[tuple[str, str], float] = defaultdict(float)
    for r in records:
        by_pair[(r["source"], r["sink"])] += abs(r["awarded_mw"]) * abs(r["clearing_price"])
    top_pairs = sorted(
        ({"source": s, "sink": k, "notional": round(v, 2)} for (s, k), v in by_pair.items()),
        key=lambda d: d["notional"],
        reverse=True,
    )[:5]

    return {
        "participant": participant_name,
        "certificate_count": n,
        "option_pct": round(100 * option_count / n, 1),
        "obligation_pct": round(100 * obligation_count / n, 1),
        "net_mw": round(net_mw, 1),
        "preaward_pct": round(100 * preaward_count / n, 1),
        "top_pairs": top_pairs,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_analytics.py -v`
Expected: PASS, all tests in the file.

- [ ] **Step 5: Run the full suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/analytics.py backend/tests/test_analytics.py
git commit -m "feat: add discover_top_pairs, top_paths, and participant_strategy analytics"
```

---

### Task 7: Add `backend/app/weather_zones.py` (real ERCOT weather-zone mapping + seasonality)

**Files:**
- Create: `backend/app/weather_zones.py`
- Test: `backend/tests/test_weather_zones.py` (new file)

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `weather_zones.WEATHER_ZONES: list[WeatherZone]`, `weather_zones.current_conditions_by_zone(session=None) -> list[dict]`, `weather_zones.trailing_12mo_seasonality_by_zone(session=None, today=None) -> dict[str, list[dict] | None]` — consumed by Task 8's `data_loader.py` and Task 9's Overview page.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_weather_zones.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_weather_zones.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.weather_zones'`.

- [ ] **Step 3: Implement the module**

Create `backend/app/weather_zones.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_weather_zones.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/weather_zones.py backend/tests/test_weather_zones.py
git commit -m "feat: add ERCOT weather-zone mapping and Open-Meteo seasonality"
```

---

### Task 8: Scaffold the Streamlit app

**Files:**
- Create: `streamlit_app/requirements.txt`
- Create: `streamlit_app/lib/__init__.py`
- Create: `streamlit_app/lib/theme.py`
- Create: `streamlit_app/lib/data_loader.py`

**Interfaces:**
- Consumes: `app.ingestion.load_bulk_real_auction_data`, `app.analytics.{discover_top_pairs,top_paths,participant_summary,participant_strategy,filter_records,monthly_price_series,basic_metrics}`, `app.scoring.score_all_pairs`, `app.domain.SP_BY_CODE`, `app.weather_zones.{current_conditions_by_zone,trailing_12mo_seasonality_by_zone}` (all from Tasks 2, 3, 6, 7)
- Produces: `data_loader.get_dataset()`, `.get_tracked_records()`, `.get_scores()`, `.get_hot_paths(n=10)`, `.get_participants()`, `.get_participant_strategy(name)`, `.get_weather_zone_snapshot()`, `.get_weather_zone_seasonality()`, `.TOP_N_PAIRS` — consumed by every page in Tasks 9-11. `theme.configure_page(title)`, `theme.render_data_source_banner(source, warning)` — consumed by every page.

- [ ] **Step 1: Create the Streamlit requirements file**

Create `streamlit_app/requirements.txt`:

```
streamlit==1.38.0
requests==2.32.3
```

- [ ] **Step 2: Create the lib package**

Create `streamlit_app/lib/__init__.py` (empty file).

- [ ] **Step 3: Create the shared theme module**

Create `streamlit_app/lib/theme.py`:

```python
"""Shared page chrome for every Streamlit page: page config, a consistent
dark trading-terminal look, and the data-source banner every page shows so
nobody mistakes which tier (real bulk data / SQL / dropped CSV /
synthetic) is currently on screen."""

from __future__ import annotations

import streamlit as st

PAGE_ICON = "⚡"

_CSS = """
<style>
.crr-banner {
    padding: 0.6rem 1rem;
    border-radius: 6px;
    margin-bottom: 1rem;
    font-size: 0.9rem;
}
.crr-banner-real { background-color: #113322; border: 1px solid #1f6f43; color: #b7f0cf; }
.crr-banner-synthetic { background-color: #332a11; border: 1px solid #8a6d1f; color: #f0dfae; }
.crr-banner-warning { background-color: #3a1414; border: 1px solid #8a2f2f; color: #f5b8b8; }
</style>
"""


def configure_page(title: str) -> None:
    st.set_page_config(page_title=f"{title} | ERCOT CRR Analytics", page_icon=PAGE_ICON, layout="wide")
    st.markdown(_CSS, unsafe_allow_html=True)


def render_data_source_banner(source: str, warning: str | None) -> None:
    if warning:
        st.markdown(f'<div class="crr-banner crr-banner-warning">⚠ {warning}</div>', unsafe_allow_html=True)
    if source == "synthetic_demo":
        st.markdown(
            '<div class="crr-banner crr-banner-synthetic">'
            "Showing <b>synthetic demo data</b> — no real ERCOT auction files were found. "
            "Run <code>python backend/scripts/fetch_real_ercot_data.py</code> to pull real data."
            "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="crr-banner crr-banner-real">'
            f"Showing <b>real ERCOT data</b> (source: <code>{source}</code>)."
            "</div>",
            unsafe_allow_html=True,
        )
```

- [ ] **Step 4: Create the cached data-loading layer**

Create `streamlit_app/lib/data_loader.py`:

```python
"""
Shared, cached data-loading layer for the Streamlit app.

Imports the tested backend/app/*.py modules directly (no HTTP hop) -- this
is what makes the Streamlit app a single process that works the moment the
whole project folder is copied/zipped elsewhere, with no second server to
boot. Uses the same sys.path pattern as backend/scripts/export_snapshot.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app import analytics, domain, scoring, weather_zones  # noqa: E402
from app.ingestion import load_bulk_real_auction_data  # noqa: E402

TOP_N_PAIRS = 30


def _settlement_point_name(code: str) -> str:
    sp = domain.SP_BY_CODE.get(code)
    return sp.name if sp else code


@st.cache_data(ttl=3600, show_spinner="Loading CRR auction dataset...")
def get_dataset() -> tuple[list[dict], str, str | None]:
    return load_bulk_real_auction_data()


@st.cache_data(ttl=3600)
def get_tracked_records() -> tuple[list[dict], list[dict]]:
    """Returns (records_for_tracked_pairs, top_pairs) -- every downstream
    view works off this filtered set so a handful of one-off resource-node
    trades don't drown out the pairs that actually have recurring
    activity. See analytics.discover_top_pairs."""
    records, _source, _warning = get_dataset()
    top_pairs = analytics.discover_top_pairs(records, n=TOP_N_PAIRS)
    tracked_keys = {(p["source"], p["sink"]) for p in top_pairs}
    tracked_records = [r for r in records if (r["source"], r["sink"]) in tracked_keys]
    return tracked_records, top_pairs


@st.cache_data(ttl=3600)
def get_scores() -> list[dict]:
    tracked_records, _ = get_tracked_records()
    scores = scoring.score_all_pairs(tracked_records)
    return [
        {
            "source": s.source,
            "source_name": _settlement_point_name(s.source),
            "sink": s.sink,
            "sink_name": _settlement_point_name(s.sink),
            "score": s.score,
            "tier": s.tier,
            "factors": s.factors,
            "explanation": s.explanation,
            "metrics": s.metrics,
        }
        for s in scores
    ]


@st.cache_data(ttl=3600)
def get_hot_paths(n: int = 10) -> list[dict]:
    records, _source, _warning = get_dataset()
    return analytics.top_paths(records, months_back=12, n=n)


@st.cache_data(ttl=3600)
def get_participants() -> list[dict]:
    tracked_records, _ = get_tracked_records()
    return analytics.participant_summary(tracked_records)


@st.cache_data(ttl=3600)
def get_participant_strategy(name: str) -> dict:
    records, _source, _warning = get_dataset()
    participant_records = [r for r in records if r["participant"] == name]
    return analytics.participant_strategy(name, participant_records)


@st.cache_data(ttl=3600)
def get_weather_zone_snapshot() -> list[dict]:
    return weather_zones.current_conditions_by_zone()


@st.cache_data(ttl=86400)
def get_weather_zone_seasonality() -> dict[str, list[dict] | None]:
    return weather_zones.trailing_12mo_seasonality_by_zone()
```

- [ ] **Step 5: Manually verify the scaffold imports cleanly**

```bash
cd /Users/saif_ansari/Downloads/ercot-crr-analytics
python3 -c "
import sys
sys.path.insert(0, 'streamlit_app')
import streamlit  # confirms streamlit is installed (pip install -r streamlit_app/requirements.txt first if not)
from lib import data_loader
records, source, warning = data_loader.get_dataset.__wrapped__()
print('source:', source, 'records:', len(records))
"
```

(If `streamlit` isn't installed yet: `pip install -r streamlit_app/requirements.txt` first.) Expected: prints `source: ercot_mis_real records: <a large number>` with no import errors. (`.__wrapped__()` calls through Streamlit's cache decorator directly since there's no active Streamlit runtime in this plain-Python smoke test.)

- [ ] **Step 6: Commit**

```bash
git add streamlit_app/requirements.txt streamlit_app/lib
git commit -m "feat: scaffold Streamlit app with shared theme and cached data-loading layer"
```

---

### Task 9: Streamlit Overview page (`streamlit_app/app.py`)

**Files:**
- Create: `streamlit_app/app.py`

**Interfaces:**
- Consumes: everything from `streamlit_app/lib/data_loader.py` and `streamlit_app/lib/theme.py` (Task 8)
- Produces: nothing consumed by later tasks (this is a leaf UI page)

- [ ] **Step 1: Write the Overview page**

Create `streamlit_app/app.py`:

```python
"""ERCOT CRR Market Analytics -- Overview (Streamlit entry point).

Run with: `streamlit run streamlit_app/app.py` from the project root.
"""

from __future__ import annotations

import streamlit as st

from lib import data_loader
from lib.theme import configure_page, render_data_source_banner

configure_page("Overview")

st.title("ERCOT CRR Market Analytics")
st.caption(
    "Market intelligence for ERCOT Congestion Revenue Rights — participant "
    "activity, Source/Sink pricing history, and an explainable opportunity "
    "signal. This is analytics tooling, not trading advice."
)

records, source, warning = data_loader.get_dataset()
render_data_source_banner(source, warning)

tracked_records, top_pairs = data_loader.get_tracked_records()
scores = data_loader.get_scores()
participants = data_loader.get_participants()
hot_paths = data_loader.get_hot_paths()

months = sorted({r["auction_month"] for r in records})
latest_month = months[-1] if months else "n/a"
latest_records = [r for r in records if r["auction_month"] == latest_month]

col1, col2, col3, col4 = st.columns(4)
col1.metric("Latest Auction Month", latest_month)
col2.metric("Active Participants", len({r["participant"] for r in records}))
col3.metric("Tracked Pairs", len(top_pairs))
col4.metric("Latest Month MW Awarded", f"{sum(r['awarded_mw'] for r in latest_records):,.0f}")

st.divider()

left, right = st.columns([3, 2])

with left:
    st.subheader("Hot Paths")
    st.caption("The most active Source/Sink corridors, ranked by gross notional activity.")
    for p in hot_paths:
        st.markdown(f"**{p['source']} → {p['sink']}** — {p['reason']}")

with right:
    st.subheader("Opportunity Tier Distribution")
    tier_counts = {"High": 0, "Medium": 0, "Low": 0}
    for s in scores:
        tier_counts[s["tier"]] = tier_counts.get(s["tier"], 0) + 1
    st.bar_chart(tier_counts)

st.divider()
st.subheader("Top Participants by Notional")
st.dataframe(
    [
        {
            "Participant": p["participant"],
            "Net MW": p["total_awarded_mw"],
            "Notional ($)": p["total_notional"],
            "Distinct Pairs": p["distinct_pairs"],
            "Certificates": p["auction_count"],
        }
        for p in participants[:10]
    ],
    hide_index=True,
    use_container_width=True,
)

st.divider()
st.subheader("Weather Context by ERCOT Zone")
st.caption(
    "Wind at West Texas/Panhandle and temperature-driven load at Coast/North "
    "are physical drivers of the congestion these corridors measure — shown "
    "as context, not a forecast of CRR value or a scoring input."
)
weather = data_loader.get_weather_zone_snapshot()
cols = st.columns(4)
for i, entry in enumerate(weather):
    with cols[i % 4]:
        if entry["error"]:
            st.error(f"{entry['zone']}: couldn't reach Open-Meteo")
        else:
            st.metric(
                f"{entry['zone']} ({entry['city']})",
                f"{entry['temperature_f']:.0f}°F",
                f"wind {entry['wind_mph']:.0f} mph",
            )
```

- [ ] **Step 2: Commit**

```bash
git add streamlit_app/app.py
git commit -m "feat: add Streamlit Overview page with hot paths, tiers, participants, weather"
```

(Visual verification of this page happens in Task 12, once all pages exist.)

---

### Task 10: Streamlit Source/Sink Explorer page

**Files:**
- Create: `streamlit_app/pages/1_Source_Sink_Explorer.py`

**Interfaces:**
- Consumes: `data_loader.get_dataset`, `.get_tracked_records`; `app.analytics.{filter_records,monthly_price_series,basic_metrics,participant_summary}` directly (backend already on `sys.path` once `lib.data_loader` has been imported once in the process)

- [ ] **Step 1: Write the Explorer page**

Create `streamlit_app/pages/1_Source_Sink_Explorer.py`:

```python
"""Source/Sink Explorer -- historical pricing, congestion trends, and
active participants for one tracked CRR corridor at a time."""

from __future__ import annotations

import csv
import io

import streamlit as st

from lib import data_loader
from lib.theme import configure_page, render_data_source_banner

configure_page("Source/Sink Explorer")
st.title("Source/Sink Explorer")

records, source, warning = data_loader.get_dataset()
render_data_source_banner(source, warning)

from app import analytics  # noqa: E402  (backend path already on sys.path via data_loader import)

tracked_records, top_pairs = data_loader.get_tracked_records()
pair_labels = [f"{p['source']} → {p['sink']}" for p in top_pairs]
choice = st.selectbox("Corridor", pair_labels)
selected = top_pairs[pair_labels.index(choice)]
src, snk = selected["source"], selected["sink"]

tou_choice = st.radio("Time of Use", ["ALL", "PEAK_WD", "PEAK_WE", "OFF_PEAK"], horizontal=True)
crr_type_choice = st.radio("CRR Type", ["OBLIGATION", "OPTION"], horizontal=True)

pair_records = analytics.filter_records(
    tracked_records,
    source=src,
    sink=snk,
    crr_type=crr_type_choice,
    time_of_use=None if tou_choice == "ALL" else tou_choice,
)

series = analytics.monthly_price_series(pair_records)
metrics = analytics.basic_metrics(pair_records)

st.subheader(f"{src} → {snk} ({crr_type_choice}, {tou_choice})")
if series:
    st.line_chart({s["auction_month"]: s["avg_clearing_price"] for s in series})
else:
    st.info("No records for this pair/filter combination.")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Average", metrics["average"])
m2.metric("Trailing 12mo Avg", metrics["trailing_12mo_average"])
m3.metric("Volatility", metrics["volatility"])
m4.metric("% Months Negative", metrics["pct_months_negative"])

st.divider()
st.subheader("Active Participants on This Pair")
pair_all_records = analytics.filter_records(tracked_records, source=src, sink=snk)
pair_participants = analytics.participant_summary(pair_all_records)
st.dataframe(
    [
        {
            "Participant": p["participant"],
            "Net MW": p["total_awarded_mw"],
            "Notional ($)": p["total_notional"],
            "Certificates": p["auction_count"],
        }
        for p in pair_participants[:15]
    ],
    hide_index=True,
    use_container_width=True,
)

if series:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["auction_month", "avg_clearing_price"])
    for row in series:
        writer.writerow([row["auction_month"], row["avg_clearing_price"]])
    st.download_button("Download CSV", buf.getvalue(), file_name=f"{src}_{snk}_series.csv")
```

- [ ] **Step 2: Commit**

```bash
git add streamlit_app/pages/1_Source_Sink_Explorer.py
git commit -m "feat: add Streamlit Source/Sink Explorer page"
```

---

### Task 11: Streamlit Participants page (with Strategy section) and Opportunity Signals page

**Files:**
- Create: `streamlit_app/pages/2_Participants.py`
- Create: `streamlit_app/pages/3_Opportunity_Signals.py`

**Interfaces:**
- Consumes: `data_loader.{get_dataset,get_participants,get_participant_strategy,get_scores}` (Task 8)

- [ ] **Step 1: Write the Participants page**

Create `streamlit_app/pages/2_Participants.py`:

```python
"""Participant analysis: activity ranking plus a per-participant strategy
breakdown (Option/Obligation mix, net Buy/Sell position, top corridors)."""

from __future__ import annotations

import streamlit as st

from lib import data_loader
from lib.theme import configure_page, render_data_source_banner

configure_page("Participants")
st.title("Participants")

records, source, warning = data_loader.get_dataset()
render_data_source_banner(source, warning)

participants = data_loader.get_participants()

st.subheader("All Tracked-Pair Participants")
search = st.text_input("Search by name")
filtered = [p for p in participants if search.lower() in p["participant"].lower()] if search else participants
st.dataframe(
    [
        {
            "Participant": p["participant"],
            "Net MW": p["total_awarded_mw"],
            "Notional ($)": p["total_notional"],
            "Distinct Pairs": p["distinct_pairs"],
            "Certificates": p["auction_count"],
        }
        for p in filtered
    ],
    hide_index=True,
    use_container_width=True,
)

st.divider()
st.subheader("Participant Strategy")
names = [p["participant"] for p in participants]
if names:
    selected_name = st.selectbox("Participant", names)
    strategy = data_loader.get_participant_strategy(selected_name)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Certificates", strategy["certificate_count"])
    c2.metric("Option / Obligation", f"{strategy['option_pct']}% / {strategy['obligation_pct']}%")
    c3.metric("Net MW Position", strategy["net_mw"])
    c4.metric("Pre-Award Share", f"{strategy['preaward_pct']}%")

    st.caption(
        "Pre-Award share is the portion of this participant's certificates "
        "that were already-held rights carried into this auction rather than "
        "freshly won bids — a high share suggests a buy-and-hold strategy, "
        "a low share suggests active monthly re-bidding."
    )

    st.markdown("**Top Corridors by Notional**")
    st.dataframe(
        [
            {"Source": p["source"], "Sink": p["sink"], "Notional ($)": p["notional"]}
            for p in strategy["top_pairs"]
        ],
        hide_index=True,
        use_container_width=True,
    )
else:
    st.info("No participants in the tracked-pair universe yet.")
```

- [ ] **Step 2: Write the Opportunity Signals page**

Create `streamlit_app/pages/3_Opportunity_Signals.py`:

```python
"""Explainable Low/Medium/High opportunity score for every tracked
Source/Sink pair -- a transparent composite of historical descriptive
statistics, not a prediction or a bidding recommendation."""

from __future__ import annotations

import streamlit as st

from lib import data_loader
from lib.theme import configure_page, render_data_source_banner

configure_page("Opportunity Signals")
st.title("Opportunity Signals")
st.caption(
    "Market intelligence, not trading advice — every score below is a "
    "transparent composite of four named, weighted historical factors."
)

records, source, warning = data_loader.get_dataset()
render_data_source_banner(source, warning)

scores = data_loader.get_scores()

tier_filter = st.radio("Tier", ["All", "High", "Medium", "Low"], horizontal=True)
search = st.text_input("Search by hub/zone name or code")

filtered = scores
if tier_filter != "All":
    filtered = [s for s in filtered if s["tier"] == tier_filter]
if search:
    q = search.lower()
    filtered = [
        s for s in filtered
        if q in s["source"].lower() or q in s["sink"].lower()
        or q in s["source_name"].lower() or q in s["sink_name"].lower()
    ]

st.write(f"{len(filtered)} of {len(scores)} tracked pairs")

for s in filtered:
    with st.expander(f"{s['source']} → {s['sink']}  —  {s['tier']} ({s['score']})"):
        f1, f2, f3, f4 = st.columns(4)
        f1.metric("Value", s["factors"]["value"]["score"])
        f2.metric("Trend", s["factors"]["trend"]["score"])
        f3.metric("Consistency", s["factors"]["consistency"]["score"])
        f4.metric("Liquidity", s["factors"]["liquidity"]["score"])
        for line in s["explanation"]:
            st.write(f"- {line}")
```

- [ ] **Step 3: Commit**

```bash
git add streamlit_app/pages/2_Participants.py streamlit_app/pages/3_Opportunity_Signals.py
git commit -m "feat: add Streamlit Participants (with strategy) and Opportunity Signals pages"
```

---

### Task 12: Live QA pass on the running Streamlit app

**Files:** none created/modified — verification only. If this task finds bugs, fix them in the relevant file from Tasks 8-11 and re-run this task's steps before committing the fix.

- [ ] **Step 1: Install Streamlit app dependencies**

```bash
cd /Users/saif_ansari/Downloads/ercot-crr-analytics
pip install -r streamlit_app/requirements.txt
```

- [ ] **Step 2: Start the app**

Using your available preview/browser tooling (e.g. a `preview_start` tool backed by a `.claude/launch.json` entry with `runtimeExecutable: "streamlit"`, `runtimeArgs: ["run", "streamlit_app/app.py", "--server.headless", "true"]`, `port: 8501`), or directly:

```bash
streamlit run streamlit_app/app.py --server.headless true --server.port 8501
```

Expected: server starts, logs show "You can now view your Streamlit app in your browser" with no tracebacks.

- [ ] **Step 3: Verify the Overview page**

Load `http://localhost:8501`. Verify: the real-data banner shows (not the synthetic one, given Task 5's real data is present), all four top metrics show non-zero/non-"n/a" values, Hot Paths lists real Source/Sink codes with a reason line, the tier-distribution bar chart renders, Top Participants shows real company names (not fictional ones like "Lone Star Power Trading LLC" and not bare short codes like "XSARAC"), and the Weather panel shows either a temperature or a clear per-zone error for all 8 zones.

- [ ] **Step 4: Verify Source/Sink Explorer**

Navigate to the page. Select a corridor, toggle Time of Use and CRR Type, confirm the line chart and metrics update, confirm the participants table populates, confirm the CSV download button appears when a series exists.

- [ ] **Step 5: Verify Participants**

Search for a partial real participant name, confirm the table filters. Select a participant from the Strategy dropdown, confirm all four strategy metrics render (not crashing on `None`/missing keys) and the top-corridors table populates.

- [ ] **Step 6: Verify Opportunity Signals**

Toggle each tier filter, confirm counts change and match "N of M tracked pairs." Search a hub code, confirm filtering. Expand a couple of pair cards, confirm the four factor scores and explanation lines render.

- [ ] **Step 7: Check logs/console for errors**

Check the running server's stdout/stderr and (if using a browser preview tool) the browser console for any exceptions or Python tracebacks surfaced as a Streamlit error box. Fix any found before proceeding — do not report this task done with an unresolved error on screen.

- [ ] **Step 8: Stop the server**

Stop the Streamlit process (or the preview server) once verification is complete.

- [ ] **Step 9: Commit any fixes made during this task**

If Step 7 required fixes:

```bash
git add streamlit_app
git commit -m "fix: resolve issues found during live Streamlit QA pass"
```

If no fixes were needed, skip this step (nothing to commit).

---

### Task 13: Update project documentation

**Files:**
- Modify: `docs/requirements.md`
- Modify: `docs/triple_check_review.md`
- Modify: `docs/lessons_learned_and_future_work.md`
- Modify: `docs/prompt_journal.md`
- Modify: `README.md`

**Interfaces:** None — documentation only.

- [ ] **Step 1: Add a new requirements section**

Append to `docs/requirements.md` (after its existing content):

```markdown
## v1.4 additions (2026-09) -- real data, market intelligence, Streamlit

Driven directly by Reggie Wade's review call (see `docs/prompt_journal.md`
for the prompt-evolution entry) and a re-investigation of ERCOT's MIS data
access (see `lessons_learned_and_future_work.md`).

- FR-17: Real CRR Auction Results (13 months) and a real participant
  registry are bundled in the repo (`data/raw/crr_auction/`,
  `data/reference/participants.csv`), fetched via
  `backend/scripts/fetch_real_ercot_data.py` from ERCOT's public,
  unauthenticated legacy MIS servlet endpoints.
- FR-18: Tracked Source/Sink pairs are data-driven (top 30 by notional,
  `analytics.discover_top_pairs`), not a fixed hand-curated list, since
  real data contains far more distinct pairs than the synthetic universe.
- FR-19: A "Hot Paths" panel (`analytics.top_paths`) surfaces the most
  active, most recurringly-congested corridors on the Overview page.
- FR-20: A per-participant "Strategy" view (`analytics.participant_strategy`)
  shows certificate count, Option/Obligation split, net Buy/Sell position,
  Pre-Award vs. Standard-auction share, and top corridors.
- FR-21: Real ERCOT weather-zone mapping (8 official zones) replaces the
  earlier 4 ad hoc regions, with a trailing-12-month seasonality time
  series per zone (`backend/app/weather_zones.py`).
- FR-22: The primary, shareable web application is a Streamlit app
  (`streamlit_app/`) that imports the backend's analytics modules directly
  and reads the bundled real data with no second server process, so the
  whole project folder works standalone when zipped and moved elsewhere.
  FastAPI (`backend/app/main.py`) and the React frontend
  (`frontend/src/`) remain in the repo, unmodified, as the existing tested
  API contract and a reference UI respectively.
```

- [ ] **Step 2: Add a new triple-check review pass**

Append to `docs/triple_check_review.md`:

```markdown
---

## v1.4 pass (2026-09) -- real data, market intelligence, Streamlit

### Pass 1 -- Head of Software Engineering

| Check | Verdict | Evidence |
|---|---|---|
| Real-data ingestion doesn't disturb the existing tested FastAPI path | Yes | Bulk real data lives in `data/raw/crr_auction/`, a directory `ingestion.load_records()`'s flat-`data/raw` tier never reads -- all 93+ pre-existing tests pass unmodified |
| SQL dependency is no longer load-bearing for non-SQL use | Yes | `db.py`'s SQLAlchemy imports are now lazy, so `app.ingestion` (and the Streamlit app) import cleanly with zero SQL dependencies installed |
| New analytics are pure, tested functions | Yes | `discover_top_pairs`/`top_paths`/`participant_strategy` are dict-in/dict-out, covered by unit tests including the BUY/SELL netting edge case |
| Real-data parsing bugs were caught before shipping, not assumed away | Yes | Downloaded and parsed a real ERCOT file during design; found and fixed the HedgeType/CRRType column-meaning confusion before writing any ingestion code against it |

### Pass 2 -- Senior Power Trader

| Check | Verdict | Evidence |
|---|---|---|
| Real participant names, not fictional placeholders | Yes | Real CRR Account Holder short codes joined against the real NP12-215-ER CRRAH registry |
| "Who's doing what" is answerable without paging through raw rows | Yes | Participant Strategy view: certificate count, Option/Obligation split, net position, Pre-Award share, top corridors |
| "What are the hot paths" is answerable at a glance | Yes | Overview's Hot Paths panel, ranked by real notional activity with a plain-language reason per path |
| Tracked-pair universe reflects real market activity, not a stale hand-picked list | Yes | `discover_top_pairs` re-derives the top 30 pairs from whatever the loaded data actually shows |
| Weather is mapped to the zones ERCOT itself uses, with seasonality | Yes | 8 official ERCOT weather zones, trailing-12-month average-temperature series per zone |

### Pass 3 -- Head of Frontend

| Check | Verdict | Evidence |
|---|---|---|
| One shareable app, not a two-process setup to boot locally | Yes | Streamlit app imports backend modules directly; `streamlit run streamlit_app/app.py` is the only thing to run |
| Consistent visual language across all four Streamlit pages/tabs | Yes | Shared `lib/theme.py` page config + banner + CSS used by every page |
| Data-source truth is visible on every page, not just Overview | Yes | `render_data_source_banner` called at the top of every page |
| Verified live, not just read | Yes | Live QA pass (see plan Task 12) clicked through all four pages, filters, search, and CSV export before this was called done |

**Open items (not blocking, tracked in `lessons_learned_and_future_work.md`):**
no automated Streamlit UI tests (matches this project's existing pattern of
smoke-testing the UI layer live rather than unit-testing it); presentation
deck still not updated for this round.
```

- [ ] **Step 3: Add a lessons-learned entry**

Append to `docs/lessons_learned_and_future_work.md` (in the "Lessons learned" numbered list, as item 7, and remove the now-resolved "Live ERCOT MIS ingestion" line from "Future enhancements"):

```markdown
**7. An earlier "no" is worth re-checking a second time, too.** Lesson 6
above already documented one case of this (the live Public API). The same
pattern repeated here: this project had assumed CRR auction data required
a browser session because ERCOT's modern `mis.ercot.com` file browser is
JS-driven and session-gated. That's true of that specific interface -- but
ERCOT also runs an older, still-live, completely unauthenticated legacy
servlet (`ercot.com/misapp/servlets/IceDocListJsonWS` +
`ercot.com/misdownload/servlets/mirDownload`) that serves the exact same
files. It was found only by actually trying it -- downloading and parsing
a real file -- rather than re-stating the earlier, broader conclusion.
```

Update the "Future enhancements" section: replace the line `**Live ERCOT MIS ingestion for the auction/participant data itself.**...` with:

```markdown
- ~~**Live ERCOT MIS ingestion for the auction/participant data itself.**~~
  **Done (2026-09).** `backend/scripts/fetch_real_ercot_data.py` pulls real
  CRR Monthly Auction Results and the real Market Participants List
  directly from ERCOT's public legacy MIS servlet -- no browser session,
  no authentication. See lesson 7 above.
```

- [ ] **Step 4: Add a prompt journal entry**

Append to `docs/prompt_journal.md`:

```markdown
## Entry: Real-data + Streamlit rebuild (2026-09)

**Trigger:** Reggie Wade's review call flagged that the app should use
real ERCOT auction data (a full year), map real participant IDs to real
names, look at settlement prices (not just LMPs), map weather to
load-zones/hubs with a seasonality view, and answer "who's doing what" /
"what are the hot paths." Separately, the deliverable needed to become a
single shareable Streamlit app rather than a two-process React/FastAPI
setup.

**Validation before building anything:** rather than trust the project's
own prior "CRR auction data requires a browser session" conclusion,
directly tested ERCOT's legacy MIS servlet endpoints with `curl` and found
them reachable, unauthenticated, and serving the real files -- downloaded
and parsed a real auction result and a real participant list before
writing any ingestion code against assumed column names. This surfaced
real bugs (HedgeType vs. CRRType column-meaning confusion) that a
speculative implementation would have shipped silently.

**Design decisions made with the user, not assumed:** confirmed BUY/SELL
netting semantics (net position, not gross double-count) and the
tracked-pair universe (fully data-driven top-N, not a fixed curated list)
as explicit choices before writing the design spec, since real data made
both of these live architectural questions the synthetic dataset had never
raised.
```

- [ ] **Step 5: Rewrite the real-data section of the README**

In `README.md`, replace the "## Using real ERCOT CRR auction data via CSV (no database available)" section (and its surrounding claim that the MIS download center "requires a browser session and isn't scriptable") with:

```markdown
## Real ERCOT CRR auction data (bundled, no download required)

This repo ships with 13 months of real ERCOT CRR Monthly Auction Results
(`data/raw/crr_auction/`) and the real ERCOT Market Participants List
(`data/reference/participants.csv`), fetched directly from ERCOT's public,
unauthenticated legacy MIS servlet endpoints -- no browser session, no
login, no MIS account required. This corrects an earlier assumption in
this project (see `docs/lessons_learned_and_future_work.md`) that this
data could only be reached through the modern, JS-gated `mis.ercot.com`
file browser.

The Streamlit app (see below) reads this bundled data directly, so it
works the moment the project folder is copied or unzipped somewhere else
-- no fetch step required. To refresh it after a new monthly auction
posts:

```bash
cd backend
python scripts/fetch_real_ercot_data.py
```

This is idempotent -- it only downloads auction months not already present
locally, and always refreshes the participant registry (a small file,
updated daily by ERCOT).

The FastAPI backend's own CSV tier is unaffected by this bundled data --
see `backend/app/ingestion.py`'s module docstring for why it's kept
completely separate (in short: so this bundled real data can never change
the FastAPI backend's existing, tested behavior). If you have your own
real ERCOT CRR CSVs and want the FastAPI backend specifically to use them,
drop them into `data/raw/` directly (not `data/raw/crr_auction/`) as
before.
```

Add a new section right after the "Quick look — the UI" section:

```markdown
## Quick start -- Streamlit (the primary, shareable app)

```bash
pip install -r streamlit_app/requirements.txt
streamlit run streamlit_app/app.py
```

This is a single process, no separate backend server to boot: it imports
`backend/app/{ingestion,analytics,scoring,domain,weather_zones}.py`
directly and reads the bundled real data described above. Four pages:
Overview (dashboard, Hot Paths, opportunity tiers, top participants,
weather-by-zone), Source/Sink Explorer, Participants (with a per-participant
Strategy breakdown), and Opportunity Signals.

**Deploying it as a shareable link (Streamlit Community Cloud, free):**
1. Push this repo to a GitHub repo you own.
2. Go to <https://share.streamlit.io>, sign in, click "New app."
3. Point it at your repo, branch `main`, and main file path
   `streamlit_app/app.py`. Streamlit Cloud auto-detects
   `streamlit_app/requirements.txt`. Click Deploy.

No environment variables or secrets are required for this to work --
everything it reads is bundled in the repo.
```

- [ ] **Step 6: Commit**

```bash
git add docs/requirements.md docs/triple_check_review.md docs/lessons_learned_and_future_work.md docs/prompt_journal.md README.md
git commit -m "docs: document real-data ingestion, market intelligence, and the Streamlit app"
```

---

### Task 14: Final full-suite verification and wrap-up

**Files:** none — verification only.

- [ ] **Step 1: Run the full backend test suite one more time**

```bash
cd backend && python -m pytest -q
```

Expected: all tests pass (93 original + new tests from Tasks 2, 3, 4, 6, 7).

- [ ] **Step 2: Confirm the FastAPI app still behaves exactly as documented**

```bash
cd backend && uvicorn app.main:app --port 8000 &
sleep 2
curl -s http://localhost:8000/api/meta | python3 -m json.tool
kill %1
```

Expected: `"data_source": "synthetic_demo"`, `"pair_count": 15` — unchanged from before this plan, confirming the bulk real data never touched FastAPI's behavior.

- [ ] **Step 3: Confirm the Streamlit app still boots cleanly**

```bash
cd /Users/saif_ansari/Downloads/ercot-crr-analytics
timeout 15 streamlit run streamlit_app/app.py --server.headless true --server.port 8502 || true
```

Expected: no traceback in the output before the timeout.

- [ ] **Step 4: Verify git history is clean**

```bash
git log --oneline
git status
```

Expected: one commit per task, working tree clean.

- [ ] **Step 5: Final commit if anything is outstanding**

```bash
git add -A
git status
```

If anything is unstaged, commit it with a descriptive message. If clean, this task is done with no further action.
