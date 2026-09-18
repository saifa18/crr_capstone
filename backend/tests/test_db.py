import pytest
from sqlalchemy import create_engine, insert

from app import db


@pytest.fixture
def sqlite_engine_with_data():
    """A throwaway in-memory SQLite database, seeded with rows in the
    same shape a real SQL Server table would have. This validates the
    SQLAlchemy Core query/mapping code in db.py end-to-end -- the exact
    same code path used against a real SQL Server, minus the network/ODBC
    driver layer, which isn't available in this environment (nor needed
    to prove the query logic is correct)."""
    engine = create_engine("sqlite:///:memory:")
    table = db._table("test_crr_auction_records")
    table.metadata.create_all(engine, tables=[table])

    rows = [
        {
            "auction_month": "2026-01", "source": "HB_WEST", "sink": "HB_HOUSTON",
            "crr_type": "obligation", "time_of_use": "peak_wd",
            "clearing_price": 12.5, "awarded_mw": 40.0, "participant": "Test Trading LLC",
        },
        {
            "auction_month": "2026-02", "source": "HB_WEST", "sink": "HB_HOUSTON",
            "crr_type": "OPTION", "time_of_use": "OFF_PEAK",
            "clearing_price": -3.25, "awarded_mw": 15.5, "participant": "Another Trader Co",
        },
    ]
    with engine.begin() as conn:
        conn.execute(insert(table), rows)

    return engine


def test_is_sql_configured_false_by_default(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SQL_SERVER_HOST", raising=False)
    monkeypatch.delenv("SQL_SERVER_DATABASE", raising=False)
    assert db.is_sql_configured() is False


def test_is_sql_configured_true_with_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mssql+pyodbc://user:pass@host/db")
    assert db.is_sql_configured() is True


def test_is_sql_configured_true_with_host_and_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SQL_SERVER_HOST", "myserver")
    monkeypatch.setenv("SQL_SERVER_DATABASE", "ERCOT_CRR")
    assert db.is_sql_configured() is True


def test_is_sql_configured_false_with_only_host(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SQL_SERVER_HOST", "myserver")
    monkeypatch.delenv("SQL_SERVER_DATABASE", raising=False)
    assert db.is_sql_configured() is False


def test_build_connection_url_uses_database_url_directly(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "mssql+pyodbc://user:pass@host:1433/mydb")
    assert db._build_connection_url() == "mssql+pyodbc://user:pass@host:1433/mydb"


def test_build_connection_url_assembles_sql_auth(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SQL_SERVER_HOST", "myserver.example.com")
    monkeypatch.setenv("SQL_SERVER_DATABASE", "ERCOT_CRR")
    monkeypatch.setenv("SQL_SERVER_USERNAME", "sa")
    monkeypatch.setenv("SQL_SERVER_PASSWORD", "hunter2")
    monkeypatch.delenv("SQL_SERVER_TRUSTED_CONNECTION", raising=False)
    monkeypatch.delenv("SQL_SERVER_PORT", raising=False)
    monkeypatch.delenv("SQL_SERVER_DRIVER", raising=False)

    url = db._build_connection_url()
    assert url.startswith("mssql+pyodbc://sa:hunter2@myserver.example.com:1433/ERCOT_CRR")
    assert "driver=ODBC+Driver+18+for+SQL+Server" in url


def test_build_connection_url_assembles_trusted_connection(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SQL_SERVER_HOST", "myserver")
    monkeypatch.setenv("SQL_SERVER_DATABASE", "ERCOT_CRR")
    monkeypatch.setenv("SQL_SERVER_TRUSTED_CONNECTION", "yes")
    monkeypatch.delenv("SQL_SERVER_USERNAME", raising=False)
    monkeypatch.delenv("SQL_SERVER_PASSWORD", raising=False)

    url = db._build_connection_url()
    assert "trusted_connection=yes" in url
    assert "myserver" in url


def test_build_connection_url_missing_host_raises_clear_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SQL_SERVER_HOST", raising=False)
    monkeypatch.delenv("SQL_SERVER_DATABASE", raising=False)
    with pytest.raises(db.SqlBackendError, match="not configured"):
        db._build_connection_url()


def test_build_connection_url_missing_credentials_raises_clear_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("SQL_SERVER_HOST", "myserver")
    monkeypatch.setenv("SQL_SERVER_DATABASE", "ERCOT_CRR")
    monkeypatch.delenv("SQL_SERVER_USERNAME", raising=False)
    monkeypatch.delenv("SQL_SERVER_PASSWORD", raising=False)
    monkeypatch.delenv("SQL_SERVER_TRUSTED_CONNECTION", raising=False)
    with pytest.raises(db.SqlBackendError, match="authenticate"):
        db._build_connection_url()


def test_load_records_from_sql_returns_correctly_shaped_dicts(sqlite_engine_with_data):
    records = db.load_records_from_sql(engine=sqlite_engine_with_data, table_name="test_crr_auction_records")
    assert len(records) == 2

    by_month = {r["auction_month"]: r for r in records}
    jan = by_month["2026-01"]
    assert jan["source"] == "HB_WEST"
    assert jan["sink"] == "HB_HOUSTON"
    assert jan["crr_type"] == "OBLIGATION"  # normalized to uppercase
    assert jan["time_of_use"] == "PEAK_WD"  # normalized to uppercase
    assert jan["clearing_price"] == pytest.approx(12.5)
    assert jan["awarded_mw"] == pytest.approx(40.0)
    assert jan["participant"] == "Test Trading LLC"
    assert jan["is_synthetic"] is False

    feb = by_month["2026-02"]
    assert feb["clearing_price"] == pytest.approx(-3.25)  # negative prices preserved


def test_load_records_from_sql_empty_table_returns_empty_list():
    engine = create_engine("sqlite:///:memory:")
    table = db._table("empty_test_table")
    table.metadata.create_all(engine, tables=[table])
    records = db.load_records_from_sql(engine=engine, table_name="empty_test_table")
    assert records == []


def test_load_records_from_sql_missing_table_raises_clear_error():
    engine = create_engine("sqlite:///:memory:")
    with pytest.raises(db.SqlBackendError, match="Could not query table"):
        db.load_records_from_sql(engine=engine, table_name="table_that_does_not_exist")


def test_init_db_creates_table_idempotently():
    engine = create_engine("sqlite:///:memory:")
    db.init_db(engine, table_name="idempotent_test_table")
    db.init_db(engine, table_name="idempotent_test_table")  # second call must not raise
    records = db.load_records_from_sql(engine=engine, table_name="idempotent_test_table")
    assert records == []


def test_get_engine_with_bad_url_raises_sql_backend_error():
    with pytest.raises(db.SqlBackendError):
        db.get_engine(url="not-a-valid-sqlalchemy-url")


def test_get_engine_applies_connect_timeout_for_mssql(monkeypatch):
    monkeypatch.setenv("SQL_SERVER_CONNECT_TIMEOUT_SECONDS", "3")
    captured = {}

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return create_engine("sqlite:///:memory:")  # stand-in, we only care about the call args

    monkeypatch.setattr(db, "create_engine", fake_create_engine)
    db.get_engine(url="mssql+pyodbc://user:pass@nonexistent-host:1433/db?driver=ODBC+Driver+18+for+SQL+Server")

    assert captured["kwargs"]["connect_args"] == {"timeout": 3}


def test_get_engine_skips_timeout_arg_for_non_mssql_urls(monkeypatch):
    captured = {}

    def fake_create_engine(url, **kwargs):
        captured["kwargs"] = kwargs
        return create_engine("sqlite:///:memory:")

    monkeypatch.setattr(db, "create_engine", fake_create_engine)
    db.get_engine(url="sqlite:///:memory:")

    assert captured["kwargs"]["connect_args"] == {}


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
