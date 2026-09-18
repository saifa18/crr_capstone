"""
SQL database layer for real CRR auction data.

This is the connection point for a real SQL Server database that lives on
a DIFFERENT machine from wherever this backend runs. Nothing in this file
assumes the database is local -- it is entirely configured through
environment variables, so the same code works whether the database is on
localhost, another machine on the LAN, or a cloud-hosted SQL Server
instance, with zero code changes.

--------------------------------------------------------------------------
HOW TO POINT THIS AT A REAL SQL SERVER (read this first)
--------------------------------------------------------------------------
Two ways to configure the connection -- use whichever is easier:

1. One connection string (recommended if you already have one):
     set DATABASE_URL=mssql+pyodbc://USER:PASSWORD@HOST:1433/DATABASE?driver=ODBC+Driver+18+for+SQL+Server

2. Separate pieces (recommended otherwise -- this module assembles the
   connection string for you, and handles both SQL auth and Windows/
   trusted-connection auth):
     set SQL_SERVER_HOST=your-server-hostname-or-ip
     set SQL_SERVER_PORT=1433
     set SQL_SERVER_DATABASE=ERCOT_CRR
     set SQL_SERVER_DRIVER=ODBC Driver 18 for SQL Server
     # then EITHER SQL auth:
     set SQL_SERVER_USERNAME=your_username
     set SQL_SERVER_PASSWORD=your_password
     # OR Windows/trusted-connection auth (Windows only, no username/password):
     set SQL_SERVER_TRUSTED_CONNECTION=yes

Requires the `pyodbc` Python package (already in requirements.txt) AND a
system-level ODBC driver for SQL Server installed on the machine running
this backend -- NOT a Python package, an OS-level install:
  - Windows: usually already present; if not, install "ODBC Driver 18 for
    SQL Server" from Microsoft.
  - macOS:   brew tap microsoft/mssql-release && brew install msodbcsql18
  - Linux (Debian/Ubuntu): see Microsoft's "Install the Microsoft ODBC
    driver for SQL Server on Linux" docs for your distro.

Once configured, `ingestion.load_records()` uses this automatically --
see that module's docstring for the full data-source priority order.

--------------------------------------------------------------------------
EXPECTED TABLE SCHEMA
--------------------------------------------------------------------------
Expects one table (name configurable via SQL_SERVER_TABLE, default
`crr_auction_records`) with these columns -- this is the SAME shape as
the CSV ingestion path and the synthetic generator, so every other module
in this backend (analytics, scoring, the API) needs zero changes:

    auction_month   VARCHAR(7)      e.g. '2026-01'
    source          VARCHAR(50)     ERCOT settlement point code, e.g. 'HB_WEST'
    sink             VARCHAR(50)    ERCOT settlement point code, e.g. 'HB_HOUSTON'
    crr_type         VARCHAR(20)    'OBLIGATION' or 'OPTION'
    time_of_use      VARCHAR(20)    'PEAK_WD', 'PEAK_WE', or 'OFF_PEAK'
    clearing_price    FLOAT         $/MWh, can be negative
    awarded_mw        FLOAT         MW awarded in this auction line item
    participant        VARCHAR(200) CRR Account Holder / participant name

See `backend/scripts/create_sql_server_schema.sql` for the exact T-SQL to
create this table, and `init_db()` below for a Python-side equivalent that
works against any SQLAlchemy-supported database (handy for a quick local
smoke test against SQLite before pointing at the real server).
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import (
    Column,
    Engine,
    Float,
    MetaData,
    String,
    Table,
    create_engine,
    select,
)
from sqlalchemy.exc import SQLAlchemyError

DEFAULT_TABLE_NAME = "crr_auction_records"

metadata = MetaData()


def _table(name: str) -> Table:
    """Builds (or returns the already-built) Table object for a given
    table name. `extend_existing=True` makes repeated calls with the same
    name safe (e.g. across multiple requests) rather than raising on a
    duplicate definition."""
    if name in metadata.tables:
        return metadata.tables[name]
    return Table(
        name,
        metadata,
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


class SqlBackendError(RuntimeError):
    """Raised for any SQL connection/query failure, with a human-readable,
    actionable message -- never a raw driver traceback bubbled to the API
    layer."""


def is_sql_configured() -> bool:
    """True if enough environment variables are set to attempt a SQL
    connection. Does not verify the connection actually works -- that only
    happens on first real query, via get_engine()/load_records_from_sql()."""
    if os.environ.get("DATABASE_URL"):
        return True
    return bool(os.environ.get("SQL_SERVER_HOST")) and bool(os.environ.get("SQL_SERVER_DATABASE"))


def _build_connection_url() -> str:
    explicit = os.environ.get("DATABASE_URL")
    if explicit:
        return explicit

    host = os.environ.get("SQL_SERVER_HOST")
    database = os.environ.get("SQL_SERVER_DATABASE")
    if not host or not database:
        raise SqlBackendError(
            "SQL Server is not configured. Set DATABASE_URL, or set both "
            "SQL_SERVER_HOST and SQL_SERVER_DATABASE (plus SQL_SERVER_USERNAME/"
            "SQL_SERVER_PASSWORD, or SQL_SERVER_TRUSTED_CONNECTION=yes for "
            "Windows auth). See db.py's module docstring for the full list."
        )

    port = os.environ.get("SQL_SERVER_PORT", "1433")
    driver = os.environ.get("SQL_SERVER_DRIVER", "ODBC Driver 18 for SQL Server")
    driver_param = driver.replace(" ", "+")

    trusted = os.environ.get("SQL_SERVER_TRUSTED_CONNECTION", "").lower() in ("yes", "true", "1")
    if trusted:
        return (
            f"mssql+pyodbc://@{host}:{port}/{database}"
            f"?driver={driver_param}&trusted_connection=yes"
        )

    username = os.environ.get("SQL_SERVER_USERNAME")
    password = os.environ.get("SQL_SERVER_PASSWORD")
    if not username or not password:
        raise SqlBackendError(
            "SQL_SERVER_HOST/SQL_SERVER_DATABASE are set, but neither "
            "SQL_SERVER_USERNAME/SQL_SERVER_PASSWORD nor "
            "SQL_SERVER_TRUSTED_CONNECTION=yes is set -- can't authenticate. "
            "Set one or the other."
        )

    from urllib.parse import quote_plus
    return (
        f"mssql+pyodbc://{quote_plus(username)}:{quote_plus(password)}@{host}:{port}/{database}"
        f"?driver={driver_param}"
    )


def get_engine(url: str | None = None) -> Engine:
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
    resolved_url = url or _build_connection_url()
    timeout_seconds = int(os.environ.get("SQL_SERVER_CONNECT_TIMEOUT_SECONDS", "10"))
    try:
        connect_args = {"timeout": timeout_seconds} if resolved_url.startswith("mssql+pyodbc") else {}
        return create_engine(resolved_url, pool_pre_ping=True, connect_args=connect_args)
    except SqlBackendError:
        raise
    except Exception as e:  # pragma: no cover - defensive, e.g. malformed URL
        raise SqlBackendError(f"Could not build a database engine: {e}") from e


def init_db(engine: Engine, table_name: str | None = None) -> None:
    """Creates the expected table if it doesn't exist yet. Safe to call
    against an existing, already-populated table (no-op in that case).
    Mainly useful for a quick local smoke test against SQLite -- against a
    real production SQL Server, a DBA-managed schema
    (see scripts/create_sql_server_schema.sql) is usually preferred."""
    table_name = table_name or os.environ.get("SQL_SERVER_TABLE", DEFAULT_TABLE_NAME)
    table = _table(table_name)
    try:
        table.metadata.create_all(engine, tables=[table], checkfirst=True)
    except SQLAlchemyError as e:
        raise SqlBackendError(f"Could not create/verify table '{table_name}': {e}") from e


def load_records_from_sql(engine: Engine | None = None, table_name: str | None = None) -> list[dict[str, Any]]:
    """Queries every row from the CRR auction records table and returns
    them in the exact dict shape analytics.py/scoring.py already expect --
    so once this succeeds, the rest of the backend needs zero changes.

    Raises SqlBackendError with a clear, actionable message on any
    connection or query failure -- a bad host, bad credentials, a missing
    table, a missing ODBC driver, etc. all get a specific, readable
    explanation rather than a raw driver traceback.
    """
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
