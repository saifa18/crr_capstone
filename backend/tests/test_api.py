import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_meta_endpoint():
    r = client.get("/api/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["record_count"] > 0
    # This backend now reads the same bundled real ERCOT MIS data as the
    # Streamlit app (see main.py's _get_data()) rather than the synthetic
    # generator, whenever that bundled data is present -- as it is here.
    assert body["data_source"] == "ercot_mis_real"
    # ~95,000 distinct real Source/Sink pairs, not the 15 illustrative
    # synthetic ones -- exact count isn't stable across data refreshes,
    # so assert order-of-magnitude instead of an exact number.
    assert body["pair_count"] > 1000
    # Full distinct auction-month list, ascending -- feeds the Participants
    # page's data-aware auction-period filter (never a hardcoded Jan-Dec list).
    assert body["auction_months"] == sorted(set(body["auction_months"]))
    assert len(body["auction_months"]) > 1
    assert all(len(m) == 7 and m[4] == "-" for m in body["auction_months"])


def test_dashboard_endpoint_shape():
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    body = r.json()
    for key in [
        "latest_auction_month", "latest_month_mw_awarded", "active_participant_count",
        "tracked_pair_count", "top_participants", "monthly_mw_trend",
    ]:
        assert key in body
    assert len(body["top_participants"]) == 5
    # Opportunity-tier output was dropped from this endpoint (confirmed
    # unused by any current frontend page -- see dashboard()'s docstring);
    # the opportunity score itself still exists at /api/opportunity-scores.
    assert "tier_distribution" not in body
    assert "top_opportunity_pairs" not in body


def test_dashboard_monthly_mw_trend_shape():
    r = client.get("/api/dashboard")
    body = r.json()
    trend = body["monthly_mw_trend"]
    assert len(trend) <= 12
    assert len(trend) > 0
    for row in trend:
        assert "auction_month" in row and "total_mw" in row
        assert row["total_mw"] >= 0
    months = [row["auction_month"] for row in trend]
    assert months == sorted(months)  # chronological order
    assert trend[-1]["auction_month"] == body["latest_auction_month"]


def test_pairs_endpoint_lists_all_pairs():
    r = client.get("/api/pairs")
    assert r.status_code == 200
    body = r.json()
    # The top 30 tracked corridors by real notional activity, not every
    # one of the real dataset's ~95,000 distinct pairs -- see _tracked()
    # in main.py.
    assert len(body) == 30
    assert all("average_obligation_price" in p for p in body)


def test_pair_series_endpoint_valid_pair():
    r = client.get("/api/pairs/HB_WEST/HB_HOUSTON/series")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "HB_WEST"
    assert body["sink"] == "HB_HOUSTON"
    assert len(body["series"]) > 0
    assert "metrics" in body


def test_pair_series_endpoint_filters_by_crr_type():
    # HB_WEST/HB_HOUSTON's real activity happens to be Option-only, so it
    # would 404 under an Obligation filter -- HB_WEST/LZ_WEST is a tracked
    # pair with real records of both types.
    r = client.get("/api/pairs/HB_WEST/LZ_WEST/series", params={"crr_type": "OBLIGATION"})
    assert r.status_code == 200


def test_pair_series_endpoint_unknown_settlement_point_404():
    r = client.get("/api/pairs/NOT_A_REAL_POINT/HB_HOUSTON/series")
    assert r.status_code == 404


def test_participants_endpoint():
    r = client.get("/api/participants")
    assert r.status_code == 200
    body = r.json()
    assert len(body) > 0
    assert body[0]["total_notional"] >= body[-1]["total_notional"]


def test_participant_detail_endpoint():
    all_p = client.get("/api/participants").json()
    name = all_p[0]["participant"]
    r = client.get(f"/api/participants/{name}")
    assert r.status_code == 200
    body = r.json()
    assert body["participant"] == name
    assert "recent_activity" in body


def test_participant_detail_unknown_404():
    r = client.get("/api/participants/Nonexistent Trading Co")
    assert r.status_code == 404


def test_participant_detail_period_filters_summary_and_activity_consistently(monkeypatch):
    import app.main as main_module

    fake_records = [
        {"participant": "Acme Trading", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "auction_month": "2026-01", "awarded_mw": 10.0, "clearing_price": 2.0, "crr_type": "OBLIGATION"},
        {"participant": "Acme Trading", "source": "HB_WEST", "sink": "HB_SOUTH",
         "auction_month": "2026-02", "awarded_mw": 5.0, "clearing_price": 1.0, "crr_type": "OBLIGATION"},
    ]
    monkeypatch.setattr(main_module, "_records", lambda: fake_records)

    # No period -> both months, both paths.
    r_all = client.get("/api/participants/Acme Trading")
    assert r_all.status_code == 200
    body_all = r_all.json()
    assert body_all["period"] == "all"
    assert body_all["summary"]["total_awarded_mw"] == 15.0
    assert body_all["summary"]["distinct_pairs"] == 2
    assert body_all["recent_activity"]["total"] == 2
    assert len(body_all["recent_activity"]["items"]) == 2

    # Exact month -> summary AND activity both scoped to just that month,
    # never a certificate table filtered independently of the summary above it.
    r_jan = client.get("/api/participants/Acme Trading", params={"period": "2026-01"})
    body_jan = r_jan.json()
    assert body_jan["period"] == "2026-01"
    assert body_jan["summary"]["total_awarded_mw"] == 10.0
    assert body_jan["summary"]["distinct_pairs"] == 1
    assert body_jan["recent_activity"]["total"] == 1
    assert body_jan["recent_activity"]["items"][0]["auction_month"] == "2026-01"

    # A month with zero records for this participant -> zeroed summary, not a 404/500.
    r_empty = client.get("/api/participants/Acme Trading", params={"period": "2026-03"})
    assert r_empty.status_code == 200
    assert r_empty.json()["summary"]["total_awarded_mw"] == 0.0
    assert r_empty.json()["recent_activity"] == {"items": [], "page": 1, "page_size": 25, "total": 0, "total_pages": 0}


def test_participant_detail_ytd_uses_datasets_own_latest_year(monkeypatch):
    import app.main as main_module

    fake_records = [
        {"participant": "Acme Trading", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "auction_month": "2025-11", "awarded_mw": 1.0, "clearing_price": 1.0, "crr_type": "OBLIGATION"},
        {"participant": "Acme Trading", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "auction_month": "2026-01", "awarded_mw": 2.0, "clearing_price": 1.0, "crr_type": "OBLIGATION"},
        {"participant": "Acme Trading", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "auction_month": "2026-02", "awarded_mw": 3.0, "clearing_price": 1.0, "crr_type": "OBLIGATION"},
    ]
    monkeypatch.setattr(main_module, "_records", lambda: fake_records)

    r = client.get("/api/participants/Acme Trading", params={"period": "ytd"})
    assert r.status_code == 200
    body = r.json()
    # 2025-11 excluded (prior year to the dataset's own latest year, 2026);
    # 2026-01 and 2026-02 included.
    assert body["summary"]["total_awarded_mw"] == 5.0
    assert body["recent_activity"]["total"] == 2


def test_participant_detail_rejects_malformed_period():
    r = client.get("/api/participants/Nonexistent Trading Co", params={"period": "not-a-period"})
    # Unknown participant is checked first (404) regardless; use a real one.
    all_p = client.get("/api/participants").json()
    name = all_p[0]["participant"]
    r = client.get(f"/api/participants/{name}", params={"period": "not-a-period"})
    assert r.status_code == 422


def test_participant_detail_scopes_to_a_specific_path_when_given(monkeypatch):
    import app.main as main_module

    fake_records = [
        {"participant": "Acme Trading", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "auction_month": "2026-01", "awarded_mw": 10.0, "clearing_price": 2.0, "crr_type": "OBLIGATION"},
        {"participant": "Acme Trading", "source": "HB_WEST", "sink": "HB_SOUTH",
         "auction_month": "2026-01", "awarded_mw": 5.0, "clearing_price": 1.0, "crr_type": "OBLIGATION"},
    ]
    monkeypatch.setattr(main_module, "_records", lambda: fake_records)

    # No source/sink -> both paths.
    r_all = client.get("/api/participants/Acme Trading")
    assert r_all.json()["summary"]["total_awarded_mw"] == 15.0
    assert r_all.json()["recent_activity"]["total"] == 2

    # Scoped to just HB_WEST/HB_HOUSTON -> summary AND certificates both
    # narrow to that one path, consistently (never one filtered without the other).
    r_scoped = client.get("/api/participants/Acme Trading", params={"source": "HB_WEST", "sink": "HB_HOUSTON"})
    body = r_scoped.json()
    assert body["summary"]["total_awarded_mw"] == 10.0
    assert body["summary"]["distinct_pairs"] == 1
    assert body["recent_activity"]["total"] == 1
    assert body["recent_activity"]["items"][0]["sink"] == "HB_HOUSTON"


def test_participant_detail_paginates_certificates_server_side(monkeypatch):
    import app.main as main_module

    # 63 real matching certificates -- filters (participant, implicitly
    # "all" period, no path) are applied first, THEN pagination: this must
    # yield ceil(63/25) = 3 pages, never a full 63-row payload for one page.
    fake_records = [
        {"participant": "Acme Trading", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "auction_month": "2026-01", "awarded_mw": float(i), "clearing_price": 1.0, "crr_type": "OBLIGATION"}
        for i in range(63)
    ]
    monkeypatch.setattr(main_module, "_records", lambda: fake_records)

    r1 = client.get("/api/participants/Acme Trading", params={"page": 1, "page_size": 25})
    body1 = r1.json()["recent_activity"]
    assert body1["page"] == 1
    assert body1["page_size"] == 25
    assert body1["total"] == 63
    assert body1["total_pages"] == 3
    assert len(body1["items"]) == 25

    r2 = client.get("/api/participants/Acme Trading", params={"page": 2, "page_size": 25})
    body2 = r2.json()["recent_activity"]
    assert len(body2["items"]) == 25

    r3 = client.get("/api/participants/Acme Trading", params={"page": 3, "page_size": 25})
    body3 = r3.json()["recent_activity"]
    assert len(body3["items"]) == 13  # remainder: 63 - 25 - 25

    # No overlap and no gaps between pages -- every awarded_mw value (each
    # record here has a unique one, 0..62) appears on exactly one page.
    seen_mw = set()
    for body in (body1, body2, body3):
        for item in body["items"]:
            assert item["awarded_mw"] not in seen_mw
            seen_mw.add(item["awarded_mw"])
    assert seen_mw == {float(i) for i in range(63)}

    # Page 4 doesn't exist -- degrades to an empty items list, not an error.
    r4 = client.get("/api/participants/Acme Trading", params={"page": 4, "page_size": 25})
    assert r4.status_code == 200
    assert r4.json()["recent_activity"]["items"] == []
    assert r4.json()["recent_activity"]["total"] == 63


def test_participant_detail_pagination_default_page_size_is_25():
    all_p = client.get("/api/participants").json()
    name = all_p[0]["participant"]
    r = client.get(f"/api/participants/{name}")
    assert r.status_code == 200
    assert r.json()["recent_activity"]["page_size"] == 25
    assert r.json()["recent_activity"]["page"] == 1


def test_participant_detail_crr_type_filters_strictly(monkeypatch):
    # Reproduces the reported bug: selecting CRR Type = Obligation must
    # never return an Option row, and vice versa. Filtering happens before
    # both the summary math and pagination, so `total`/`total_pages` and
    # `summary.total_awarded_mw` all reflect only the matching type too.
    import app.main as main_module

    fake_records = [
        {"participant": "Acme Trading", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "auction_month": "2026-01", "awarded_mw": 10.0, "clearing_price": 2.0, "crr_type": "OBLIGATION"},
        {"participant": "Acme Trading", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "auction_month": "2026-01", "awarded_mw": 20.0, "clearing_price": 1.0, "crr_type": "OPTION"},
        {"participant": "Acme Trading", "source": "HB_WEST", "sink": "HB_SOUTH",
         "auction_month": "2026-02", "awarded_mw": 5.0, "clearing_price": 1.0, "crr_type": "OBLIGATION"},
    ]
    monkeypatch.setattr(main_module, "_records", lambda: fake_records)

    r_obligation = client.get("/api/participants/Acme Trading", params={"crr_type": "OBLIGATION"})
    body_obl = r_obligation.json()
    assert body_obl["recent_activity"]["total"] == 2
    assert all(item["crr_type"] == "OBLIGATION" for item in body_obl["recent_activity"]["items"])
    assert body_obl["summary"]["total_awarded_mw"] == 15.0  # 10 + 5, the OPTION row excluded

    r_option = client.get("/api/participants/Acme Trading", params={"crr_type": "OPTION"})
    body_opt = r_option.json()
    assert body_opt["recent_activity"]["total"] == 1
    assert all(item["crr_type"] == "OPTION" for item in body_opt["recent_activity"]["items"])
    assert body_opt["summary"]["total_awarded_mw"] == 20.0

    # A type with zero matches degrades to an honest empty result, not a
    # fallback to another type.
    r_none = client.get("/api/participants/Acme Trading", params={"crr_type": "OPTION", "period": "2026-02"})
    assert r_none.json()["recent_activity"] == {"items": [], "page": 1, "page_size": 25, "total": 0, "total_pages": 0}


def test_participant_detail_crr_type_is_case_insensitive(monkeypatch):
    import app.main as main_module

    fake_records = [
        {"participant": "Acme Trading", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "auction_month": "2026-01", "awarded_mw": 10.0, "clearing_price": 2.0, "crr_type": "OBLIGATION"},
    ]
    monkeypatch.setattr(main_module, "_records", lambda: fake_records)

    r = client.get("/api/participants/Acme Trading", params={"crr_type": "obligation"})
    assert r.status_code == 200
    assert r.json()["recent_activity"]["total"] == 1


def test_participant_detail_rejects_invalid_crr_type():
    all_p = client.get("/api/participants").json()
    name = all_p[0]["participant"]
    r = client.get(f"/api/participants/{name}", params={"crr_type": "NOT_A_TYPE"})
    assert r.status_code == 422


def test_opportunity_scores_endpoint():
    r = client.get("/api/opportunity-scores")
    assert r.status_code == 200
    body = r.json()
    # Scored over the 30 tracked pairs, minus any that are Option-only and
    # so have no Obligation-based value signal to score (see the tier-sum
    # test above) -- so this is bounded, not exact.
    assert 0 < len(body) <= 30
    for s in body:
        assert s["tier"] in ("Low", "Medium", "High")
        assert 0 <= s["score"] <= 100
        assert len(s["explanation"]) >= 3
    scores = [s["score"] for s in body]
    assert scores == sorted(scores, reverse=True)


def test_pair_series_csv_export():
    r = client.get("/api/pairs/HB_WEST/HB_HOUSTON/series", params={"format": "csv"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    lines = r.text.strip().splitlines()
    assert lines[0] == "auction_month,avg_clearing_price"
    assert len(lines) > 1


def test_health_endpoint():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_system_status_endpoint_shape():
    r = client.get("/api/system/status")
    assert r.status_code == 200
    body = r.json()
    for key in [
        "active_data_source", "data_source_warning", "record_count",
        "sql_configured", "csv_files_present", "ercot_live_api_configured",
    ]:
        assert key in body
    assert body["record_count"] > 0


def test_system_status_reflects_sql_not_configured_by_default(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SQL_SERVER_HOST", raising=False)
    monkeypatch.delenv("SQL_SERVER_DATABASE", raising=False)
    r = client.get("/api/system/status")
    assert r.json()["sql_configured"] is False
    # with SQL not configured, the bundled real ERCOT MIS data serves it
    # (see main.py's _get_data()) -- not the synthetic generator, since
    # that bundled real data ships in this repo's data/raw/crr_auction/.
    assert r.json()["active_data_source"] == "ercot_mis_real"


def test_pair_participants_endpoint():
    r = client.get("/api/pairs/HB_WEST/HB_HOUSTON/participants")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "HB_WEST"
    assert body["sink"] == "HB_HOUSTON"
    assert len(body["participants"]) > 0
    assert "total_notional" in body["participants"][0]


def test_pair_participants_unknown_settlement_point_404():
    r = client.get("/api/pairs/NOT_REAL/HB_HOUSTON/participants")
    assert r.status_code == 404


def test_live_status_reports_not_configured_by_default(monkeypatch):
    monkeypatch.delenv("ERCOT_API_USERNAME", raising=False)
    monkeypatch.delenv("ERCOT_API_PASSWORD", raising=False)
    monkeypatch.delenv("ERCOT_API_SUBSCRIPTION_KEY", raising=False)
    r = client.get("/api/live/status")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert "apiexplorer.ercot.com" in body["message"]


def test_live_status_reports_configured_when_env_set(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")
    r = client.get("/api/live/status")
    assert r.status_code == 200
    assert r.json()["configured"] is True


def test_live_lmp_spread_without_credentials_returns_501(monkeypatch):
    monkeypatch.delenv("ERCOT_API_USERNAME", raising=False)
    monkeypatch.delenv("ERCOT_API_PASSWORD", raising=False)
    monkeypatch.delenv("ERCOT_API_SUBSCRIPTION_KEY", raising=False)
    r = client.get("/api/pairs/HB_WEST/HB_HOUSTON/live-lmp-spread")
    assert r.status_code == 501
    assert "apiexplorer.ercot.com" in r.json()["detail"]


def test_live_lmp_spread_rejects_synthetic_resource_node_pairs(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")
    r = client.get("/api/pairs/PANHANDLE_WIND_RN/HB_NORTH/live-lmp-spread")
    assert r.status_code == 422
    assert "illustrative demo" in r.json()["detail"]


def test_live_lmp_spread_unknown_settlement_point_404(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")
    r = client.get("/api/pairs/NOT_REAL/HB_NORTH/live-lmp-spread")
    assert r.status_code == 404


def test_live_lmp_spread_success_with_mocked_client(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")

    import app.main as main_module

    fake_records = [
        {"auction_month": "2026-01", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "crr_type": "OBLIGATION", "time_of_use": "PEAK_WD", "clearing_price": 12.5,
         "awarded_mw": 0.0, "participant": "(ERCOT live DAM -- no participant data)",
         "is_synthetic": False},
    ]
    monkeypatch.setattr(main_module, "fetch_live_pair_records", lambda *a, **k: fake_records)

    r = client.get("/api/pairs/HB_WEST/HB_HOUSTON/live-lmp-spread")
    assert r.status_code == 200
    body = r.json()
    assert body["data_source"] == "ercot_live_dam_spp"
    assert body["source"] == "HB_WEST"
    assert len(body["series"]) == 1


def test_live_lmp_spread_wraps_api_errors_as_502(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")

    import app.main as main_module
    from app.ercot_live import ErcotApiError

    def boom(*a, **k):
        raise ErcotApiError("ERCOT is having a bad day")

    monkeypatch.setattr(main_module, "fetch_live_pair_records", boom)

    r = client.get("/api/pairs/HB_WEST/HB_HOUSTON/live-lmp-spread")
    assert r.status_code == 502
    assert "bad day" in r.json()["detail"]


def test_live_binding_constraints_without_credentials_returns_501(monkeypatch):
    monkeypatch.delenv("ERCOT_API_USERNAME", raising=False)
    monkeypatch.delenv("ERCOT_API_PASSWORD", raising=False)
    monkeypatch.delenv("ERCOT_API_SUBSCRIPTION_KEY", raising=False)
    r = client.get("/api/live/binding-constraints", params={"date_from": "2026-01-01", "date_to": "2026-01-02"})
    assert r.status_code == 501


def _fake_shadow_price_response(rows):
    return {
        "fields": [
            {"name": "deliveryDate"}, {"name": "hourEnding"}, {"name": "constraintName"},
            {"name": "contingencyName"}, {"name": "shadowPrice"}, {"name": "fromStation"},
            {"name": "toStation"},
        ],
        "data": rows,
        "_meta": {"totalPages": 1},
    }


def test_live_binding_constraints_success_with_mocked_client(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")

    import app.main as main_module
    main_module._binding_constraints_cached.cache_clear()

    class FakeClient:
        def get_dam_shadow_prices(self, date_from, date_to, page=1, size=1000):
            return _fake_shadow_price_response(
                [["2026-01-01T00:00:00", 14, "RN_LIMIT_WEST_345", "BASE CASE", 42.1, "STA_A", "STA_B"]]
            )

    monkeypatch.setattr(main_module, "_get_live_client", lambda: FakeClient())

    r = client.get("/api/live/binding-constraints", params={"date_from": "2026-01-01", "date_to": "2026-01-02"})
    assert r.status_code == 200
    body = r.json()
    # Shaped into the same named, snake_case fields as the Streamlit app's
    # identical helper -- see main.py's live_binding_constraints docstring.
    assert body["items"] == [{
        "delivery_date": "2026-01-01",
        "hour_ending": 14,
        "constraint_name": "RN_LIMIT_WEST_345",
        "contingency_name": "BASE CASE",
        "shadow_price": 42.1,
        "from_station": "STA_A",
        "to_station": "STA_B",
    }]
    assert body["truncated"] is False
    assert body["page"] == 1
    assert body["page_size"] == 25
    assert body["total"] == 1
    assert body["total_pages"] == 1


def test_live_binding_constraints_normalizes_real_ercot_field_quirks(monkeypatch):
    # Reproduces the exact raw shape confirmed live against ERCOT's real
    # NP4-191-CD endpoint: hourEnding as a zero-padded "HH:00" string (the
    # same quirk already fixed for the settlement-price endpoint, but not
    # yet applied here) and leading whitespace baked into every string
    # field. Both must be cleaned up, not shown raw in the UI.
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")

    import app.main as main_module
    main_module._binding_constraints_cached.cache_clear()

    class FakeClient:
        def get_dam_shadow_prices(self, date_from, date_to, page=1, size=1000):
            return _fake_shadow_price_response(
                [["2026-09-22", "24:00", " 6437__F", "  BASE CASE", 71.432, " SCRCV", " KNAPP"]]
            )

    monkeypatch.setattr(main_module, "_get_live_client", lambda: FakeClient())

    r = client.get("/api/live/binding-constraints", params={"date_from": "2026-09-22", "date_to": "2026-09-22"})
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["hour_ending"] == 24  # not the raw "24:00" string
    assert item["constraint_name"] == "6437__F"  # leading space stripped
    assert item["contingency_name"] == "BASE CASE"
    assert item["from_station"] == "SCRCV"
    assert item["to_station"] == "KNAPP"


def test_live_binding_constraints_filters_before_pagination(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")

    import app.main as main_module
    main_module._binding_constraints_cached.cache_clear()

    # 30 rows for constraint "A" (low shadow price) and 3 for "B" (high) --
    # filtering to constraint_name="B" before paginating must yield total=3,
    # total_pages=1, never a page sliced from the unfiltered 33.
    rows = [
        ["2026-01-01", 1 + (i % 24), "A", "BASE CASE", 1.0, "STA_A", "STA_B"] for i in range(30)
    ] + [
        ["2026-01-01", 1 + i, "B", "BASE CASE", 500.0, "STA_C", "STA_D"] for i in range(3)
    ]

    class FakeClient:
        def get_dam_shadow_prices(self, date_from, date_to, page=1, size=1000):
            return _fake_shadow_price_response(rows)

    monkeypatch.setattr(main_module, "_get_live_client", lambda: FakeClient())

    r_all = client.get("/api/live/binding-constraints", params={"date_from": "2026-01-01", "date_to": "2026-01-01"})
    assert r_all.json()["total"] == 33

    r_b = client.get(
        "/api/live/binding-constraints",
        params={"date_from": "2026-01-01", "date_to": "2026-01-01", "constraint_name": "B"},
    )
    body_b = r_b.json()
    assert body_b["total"] == 3
    assert body_b["total_pages"] == 1
    assert all(item["constraint_name"] == "B" for item in body_b["items"])

    # constraint_options and summary reflect the FULL window, not the
    # constraint_name-filtered subset -- the dropdown must still offer "A".
    assert set(body_b["constraint_options"]) == {"A", "B"}


def test_live_binding_constraints_sort_and_pagination(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")

    import app.main as main_module
    main_module._binding_constraints_cached.cache_clear()

    rows = [["2026-01-01", 1, f"C{i:03d}", "BASE CASE", float(i), "STA_A", "STA_B"] for i in range(60)]

    class FakeClient:
        def get_dam_shadow_prices(self, date_from, date_to, page=1, size=1000):
            return _fake_shadow_price_response(rows)

    monkeypatch.setattr(main_module, "_get_live_client", lambda: FakeClient())

    r1 = client.get(
        "/api/live/binding-constraints",
        params={"date_from": "2026-01-01", "date_to": "2026-01-01", "sort_key": "shadow_price", "sort_dir": "asc", "page": 1, "page_size": 25},
    )
    body1 = r1.json()
    assert body1["total"] == 60
    assert body1["total_pages"] == 3
    assert [item["shadow_price"] for item in body1["items"][:3]] == [0.0, 1.0, 2.0]

    r2 = client.get(
        "/api/live/binding-constraints",
        params={"date_from": "2026-01-01", "date_to": "2026-01-01", "sort_key": "shadow_price", "sort_dir": "asc", "page": 2, "page_size": 25},
    )
    body2 = r2.json()
    assert [item["shadow_price"] for item in body2["items"][:3]] == [25.0, 26.0, 27.0]

    # No overlap between pages.
    seen = {item["shadow_price"] for item in body1["items"]} | {item["shadow_price"] for item in body2["items"]}
    r3 = client.get(
        "/api/live/binding-constraints",
        params={"date_from": "2026-01-01", "date_to": "2026-01-01", "sort_key": "shadow_price", "sort_dir": "asc", "page": 3, "page_size": 25},
    )
    body3 = r3.json()
    seen |= {item["shadow_price"] for item in body3["items"]}
    assert seen == {float(i) for i in range(60)}


def test_live_binding_constraints_rejects_invalid_sort_key():
    r_sort = client.get(
        "/api/live/binding-constraints",
        params={"date_from": "2026-01-01", "date_to": "2026-01-01", "sort_key": "not_a_field"},
    )
    assert r_sort.status_code == 422


def test_pairs_endpoint_shape():
    r = client.get("/api/pairs")
    assert r.status_code == 200
    body = r.json()
    assert len(body) > 0
    for pair in body:
        assert set(pair.keys()) == {
            "source", "source_name", "sink", "sink_name",
            "average_obligation_price", "trend_direction",
            "total_notional", "participant_count",
        }


def test_opportunity_scores_endpoint_shape():
    r = client.get("/api/opportunity-scores")
    assert r.status_code == 200
    body = r.json()
    assert len(body) > 0
    for score in body:
        assert set(score.keys()) == {
            "source", "source_name", "sink", "sink_name",
            "score", "tier", "factors", "explanation", "metrics",
        }


def test_settlement_history_without_credentials_returns_501(monkeypatch):
    monkeypatch.delenv("ERCOT_API_USERNAME", raising=False)
    monkeypatch.delenv("ERCOT_API_PASSWORD", raising=False)
    monkeypatch.delenv("ERCOT_API_SUBSCRIPTION_KEY", raising=False)
    r = client.get("/api/pairs/HB_WEST/HB_HOUSTON/settlement-history")
    assert r.status_code == 501


def test_settlement_history_rejects_pair_with_no_real_auction_record(monkeypatch):
    # A pair with zero matching real CRR auction records at all -- e.g. a
    # made-up code -- is rejected outright, before any live ERCOT call is
    # attempted. Real ERCOT-ness is never inferred from the name looking
    # plausible; it must come from this project's real auction dataset.
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")
    r = client.get("/api/pairs/NOT_A_REAL_CODE/ALSO_NOT_REAL/settlement-history")
    assert r.status_code == 404


def test_settlement_history_rejects_pair_backed_by_synthetic_records(monkeypatch):
    # A pair that DOES have matching records, but they're tagged
    # is_synthetic=True (the demo-generator fallback), must be excluded
    # from live Path Settlements -- this is the real data-integrity gate,
    # not a name-based whitelist (a real ERCOT resource node like
    # MERCURY_ALL must NOT be caught by this and must proceed to a live
    # fetch, confirmed by test_settlement_history_success_with_mocked_client
    # using a real hub pair with no such flag).
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")

    import app.main as main_module

    monkeypatch.setattr(
        main_module,
        "_records",
        lambda: [{"source": "DEMO_SRC", "sink": "DEMO_SINK", "is_synthetic": True}],
    )
    r = client.get("/api/pairs/DEMO_SRC/DEMO_SINK/settlement-history")
    assert r.status_code == 422
    assert "synthetic" in r.json()["detail"]


def test_settlement_history_success_with_mocked_client(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")

    import app.main as main_module

    main_module._cached_node_hourly_prices.cache_clear()
    fake_hourly = [
        {"delivery_date": "2026-01-01", "hour_ending": 8, "spread": 10.0, "option_settlement": 10.0, "time_of_use": "PEAK_WD"},
        {"delivery_date": "2026-01-02", "hour_ending": 8, "spread": -2.0, "option_settlement": 0.0, "time_of_use": "PEAK_WD"},
    ]
    monkeypatch.setattr(
        main_module,
        "fetch_settlement_point_hourly_prices",
        lambda client, sp, date_from, date_to: [{"delivery_date": "x", "hour_ending": 1, "price": 1.0}],
    )
    monkeypatch.setattr(main_module, "compute_spread_records", lambda src, snk, source, sink: fake_hourly)

    r = client.get(
        "/api/pairs/HB_WEST/HB_HOUSTON/settlement-history",
        params={"date_from": "2026-01-01", "date_to": "2026-01-02"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["data_source"] == "ercot_live_dam_spp"
    assert body["source"] == "HB_WEST"
    assert body["sink"] == "HB_HOUSTON"
    assert body["source_name"] and body["sink_name"]
    assert body["daily_series"] == [
        {"date": "2026-01-01", "obligation_price": 10.0, "option_price": 10.0},
        {"date": "2026-01-02", "obligation_price": -2.0, "option_price": 0.0},
    ]
    # raw per-node daily price series, for the Source-vs-Sink toggle view
    assert body["source_daily"] == [{"date": "x", "price": 1.0}]
    assert body["sink_daily"] == [{"date": "x", "price": 1.0}]
    # latest/average/min/max summary for the Path Detail View
    assert body["summary"]["obligation"] == {"latest": -2.0, "average": 4.0, "min": -2.0, "max": 10.0}
    assert body["summary"]["option"] == {"latest": 0.0, "average": 5.0, "min": 0.0, "max": 10.0}


def test_settlement_history_no_data_returns_404(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")

    import app.main as main_module

    main_module._cached_node_hourly_prices.cache_clear()
    monkeypatch.setattr(main_module, "fetch_settlement_point_hourly_prices", lambda *a, **k: [])
    monkeypatch.setattr(main_module, "compute_spread_records", lambda *a, **k: [])

    r = client.get("/api/pairs/HB_WEST/HB_HOUSTON/settlement-history")
    assert r.status_code == 404


def test_settlement_leaderboard_without_credentials_returns_501(monkeypatch):
    monkeypatch.delenv("ERCOT_API_USERNAME", raising=False)
    monkeypatch.delenv("ERCOT_API_PASSWORD", raising=False)
    monkeypatch.delenv("ERCOT_API_SUBSCRIPTION_KEY", raising=False)
    r = client.get("/api/pairs/HB_WEST/HB_HOUSTON/settlement-leaderboard", params={"auction_month": "2026-01"})
    assert r.status_code == 501


def test_settlement_leaderboard_requires_auction_month():
    r = client.get("/api/pairs/HB_WEST/HB_HOUSTON/settlement-leaderboard")
    assert r.status_code == 422  # FastAPI's own required-query-param validation


def test_settlement_leaderboard_computes_realized_value_from_awarded_mw(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")

    import app.main as main_module

    fake_records = [
        {"auction_month": "2026-01", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "crr_type": "OBLIGATION", "time_of_use": "PEAK_WD", "clearing_price": 5.0,
         "awarded_mw": 10.0, "participant": "Winner Co", "is_synthetic": False},
        {"auction_month": "2026-01", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "crr_type": "OPTION", "time_of_use": "PEAK_WD", "clearing_price": 1.0,
         "awarded_mw": 20.0, "participant": "Option Holder Co", "is_synthetic": False},
        {"auction_month": "2026-02", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "crr_type": "OBLIGATION", "time_of_use": "PEAK_WD", "clearing_price": 5.0,
         "awarded_mw": 999.0, "participant": "Wrong Month Co", "is_synthetic": False},
    ]
    main_module._cached_node_hourly_prices.cache_clear()
    monkeypatch.setattr(main_module, "_records", lambda: fake_records)
    monkeypatch.setattr(main_module, "fetch_settlement_point_hourly_prices", lambda *a, **k: [{"x": 1}])
    monkeypatch.setattr(main_module, "compute_spread_records", lambda *a, **k: [
        {"delivery_date": "2026-01-05", "hour_ending": 8, "spread": 10.0, "option_settlement": 10.0, "time_of_use": "PEAK_WD"},
        {"delivery_date": "2026-01-12", "hour_ending": 8, "spread": -2.0, "option_settlement": 0.0, "time_of_use": "PEAK_WD"},
    ])

    r = client.get(
        "/api/pairs/HB_WEST/HB_HOUSTON/settlement-leaderboard",
        params={"auction_month": "2026-01"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["data_source"] == "ercot_live_dam_spp"
    rows = {row["participant"]: row for row in body["rows"]}

    # obligation_value_per_mw for 2026-01/PEAK_WD = 10 + (-2) = 8
    assert rows["Winner Co"]["settlement_value"] == pytest.approx(80.0)   # 10 MW * 8
    assert rows["Winner Co"]["crr_type"] == "OBLIGATION"

    # option_value_per_mw for 2026-01/PEAK_WD = max(10,0) + max(-2,0) = 10
    assert rows["Option Holder Co"]["settlement_value"] == pytest.approx(200.0)  # 20 MW * 10

    assert "Wrong Month Co" not in rows  # different auction_month, excluded


def test_settlement_leaderboard_no_awards_for_month_returns_empty_rows(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")

    import app.main as main_module

    main_module._cached_node_hourly_prices.cache_clear()
    # A real, non-synthetic record for this pair exists, but only for a
    # different auction month -- the pair itself is real (passes
    # _require_real_nonsynthetic_pair), it simply has no awards in the
    # month being asked about.
    monkeypatch.setattr(
        main_module,
        "_records",
        lambda: [{"source": "HB_WEST", "sink": "HB_HOUSTON", "is_synthetic": False, "auction_month": "2026-02"}],
    )
    monkeypatch.setattr(main_module, "fetch_settlement_point_hourly_prices", lambda *a, **k: [{"x": 1}])
    monkeypatch.setattr(main_module, "compute_spread_records", lambda *a, **k: [
        {"delivery_date": "2026-01-05", "hour_ending": 8, "spread": 10.0, "option_settlement": 10.0, "time_of_use": "PEAK_WD"},
    ])

    r = client.get(
        "/api/pairs/HB_WEST/HB_HOUSTON/settlement-leaderboard",
        params={"auction_month": "2026-01"},
    )
    assert r.status_code == 200
    assert r.json()["rows"] == []


def test_settlement_leaderboard_bulk_without_credentials_returns_501(monkeypatch):
    monkeypatch.delenv("ERCOT_API_USERNAME", raising=False)
    monkeypatch.delenv("ERCOT_API_PASSWORD", raising=False)
    monkeypatch.delenv("ERCOT_API_SUBSCRIPTION_KEY", raising=False)
    r = client.get("/api/settlement-leaderboard", params={"auction_month": "2026-01"})
    assert r.status_code == 501


def test_settlement_leaderboard_bulk_requires_auction_month():
    r = client.get("/api/settlement-leaderboard")
    assert r.status_code == 422


def test_settlement_leaderboard_bulk_requires_source_and_sink_together(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")
    r = client.get("/api/settlement-leaderboard", params={"auction_month": "2026-01", "source": "HB_WEST"})
    assert r.status_code == 422


def _setup_bulk_leaderboard_env(monkeypatch, fake_records, top_pairs):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")

    import app.main as main_module

    main_module._cached_node_hourly_prices.cache_clear()
    monkeypatch.setattr(main_module, "_records", lambda: fake_records)
    monkeypatch.setattr(main_module, "_tracked", lambda: (fake_records, top_pairs))
    monkeypatch.setattr(main_module, "fetch_settlement_point_hourly_prices", lambda *a, **k: [{"x": 1}])
    monkeypatch.setattr(main_module, "compute_spread_records", lambda *a, **k: [
        {"delivery_date": "2026-01-05", "hour_ending": 8, "spread": 10.0, "option_settlement": 10.0, "time_of_use": "PEAK_WD"},
    ])
    return main_module


def test_settlement_leaderboard_bulk_aggregates_across_tracked_pairs_before_pagination(monkeypatch):
    # 31 real matching rows spread across two tracked corridors -- filters
    # (here, none) are applied to the FULL cross-corridor set before
    # pagination, so this must yield ceil(31/25) = 2 pages, never a
    # single-corridor-sized payload.
    fake_records = [
        {"auction_month": "2026-01", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "crr_type": "OBLIGATION", "time_of_use": "PEAK_WD", "clearing_price": 5.0,
         "awarded_mw": 1.0, "participant": f"Participant {i}", "is_synthetic": False}
        for i in range(30)
    ] + [
        {"auction_month": "2026-01", "source": "HB_NORTH", "sink": "HB_SOUTH",
         "crr_type": "OPTION", "time_of_use": "PEAK_WD", "clearing_price": 5.0,
         "awarded_mw": 2.0, "participant": "Other Path Co", "is_synthetic": False},
    ]
    top_pairs = [{"source": "HB_WEST", "sink": "HB_HOUSTON"}, {"source": "HB_NORTH", "sink": "HB_SOUTH"}]
    _setup_bulk_leaderboard_env(monkeypatch, fake_records, top_pairs)

    r1 = client.get("/api/settlement-leaderboard", params={"auction_month": "2026-01", "page": 1, "page_size": 25})
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["total"] == 31
    assert body1["total_pages"] == 2
    assert len(body1["items"]) == 25

    r2 = client.get("/api/settlement-leaderboard", params={"auction_month": "2026-01", "page": 2, "page_size": 25})
    body2 = r2.json()
    assert len(body2["items"]) == 6

    # No overlap and no gaps between the two pages.
    seen = {row["participant"] for row in body1["items"]} | {row["participant"] for row in body2["items"]}
    assert len(seen) == 31


def test_settlement_leaderboard_bulk_filters_by_participant_and_crr_type_strictly(monkeypatch):
    fake_records = [
        {"auction_month": "2026-01", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "crr_type": "OBLIGATION", "time_of_use": "PEAK_WD", "clearing_price": 5.0,
         "awarded_mw": 10.0, "participant": "Winner Co", "is_synthetic": False},
        {"auction_month": "2026-01", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "crr_type": "OPTION", "time_of_use": "PEAK_WD", "clearing_price": 1.0,
         "awarded_mw": 20.0, "participant": "Winner Co", "is_synthetic": False},
        {"auction_month": "2026-01", "source": "HB_NORTH", "sink": "HB_SOUTH",
         "crr_type": "OBLIGATION", "time_of_use": "PEAK_WD", "clearing_price": 5.0,
         "awarded_mw": 5.0, "participant": "Other Co", "is_synthetic": False},
    ]
    top_pairs = [{"source": "HB_WEST", "sink": "HB_HOUSTON"}, {"source": "HB_NORTH", "sink": "HB_SOUTH"}]
    _setup_bulk_leaderboard_env(monkeypatch, fake_records, top_pairs)

    r_participant = client.get("/api/settlement-leaderboard", params={"auction_month": "2026-01", "participant": "Winner Co"})
    body = r_participant.json()
    assert body["total"] == 2
    assert {row["participant"] for row in body["items"]} == {"Winner Co"}

    # Strict type filtering, case-insensitive: OBLIGATION must never include
    # an OPTION row and vice versa -- reproduces the reported bug at the
    # cross-corridor level too, not just the single-pair endpoint.
    r_obligation = client.get("/api/settlement-leaderboard", params={"auction_month": "2026-01", "crr_type": "obligation"})
    body_obl = r_obligation.json()
    assert body_obl["total"] == 2
    assert all(row["crr_type"] == "OBLIGATION" for row in body_obl["items"])

    r_option = client.get("/api/settlement-leaderboard", params={"auction_month": "2026-01", "crr_type": "OPTION"})
    body_opt = r_option.json()
    assert body_opt["total"] == 1
    assert all(row["crr_type"] == "OPTION" for row in body_opt["items"])


def test_settlement_leaderboard_bulk_scoped_to_one_path_matches_single_pair_math(monkeypatch):
    fake_records = [
        {"auction_month": "2026-01", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "crr_type": "OBLIGATION", "time_of_use": "PEAK_WD", "clearing_price": 5.0,
         "awarded_mw": 10.0, "participant": "Winner Co", "is_synthetic": False},
    ]
    _setup_bulk_leaderboard_env(monkeypatch, fake_records, [{"source": "HB_WEST", "sink": "HB_HOUSTON"}])

    r = client.get(
        "/api/settlement-leaderboard",
        params={"auction_month": "2026-01", "source": "HB_WEST", "sink": "HB_HOUSTON"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["settlement_value"] == pytest.approx(100.0)  # 10 MW * 10 (single spread record)


def test_settlement_leaderboard_bulk_reports_synthetic_pairs_as_unavailable(monkeypatch):
    fake_records = [
        {"auction_month": "2026-01", "source": "HB_WEST", "sink": "HB_HOUSTON",
         "crr_type": "OBLIGATION", "time_of_use": "PEAK_WD", "clearing_price": 5.0,
         "awarded_mw": 10.0, "participant": "Winner Co", "is_synthetic": False},
        {"auction_month": "2026-01", "source": "SYN_A", "sink": "SYN_B",
         "crr_type": "OBLIGATION", "time_of_use": "PEAK_WD", "clearing_price": 5.0,
         "awarded_mw": 3.0, "participant": "Demo Co", "is_synthetic": True},
    ]
    top_pairs = [{"source": "HB_WEST", "sink": "HB_HOUSTON"}, {"source": "SYN_A", "sink": "SYN_B"}]
    _setup_bulk_leaderboard_env(monkeypatch, fake_records, top_pairs)

    r = client.get("/api/settlement-leaderboard", params={"auction_month": "2026-01"})
    body = r.json()
    assert body["total"] == 1
    assert {row["participant"] for row in body["items"]} == {"Winner Co"}
    assert any(u["source"] == "SYN_A" and u["sink"] == "SYN_B" for u in body["unavailable_pairs"])


def test_settlement_summary_without_credentials_returns_501(monkeypatch):
    monkeypatch.delenv("ERCOT_API_USERNAME", raising=False)
    monkeypatch.delenv("ERCOT_API_PASSWORD", raising=False)
    monkeypatch.delenv("ERCOT_API_SUBSCRIPTION_KEY", raising=False)
    r = client.get("/api/pairs/settlement-summary")
    assert r.status_code == 501


def test_settlement_summary_dedupes_shared_node_fetches_real_nodes_only(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")

    import app.main as main_module

    main_module._cached_node_hourly_prices.cache_clear()

    # Two real, non-synthetic pairs sharing MERCURY_ALL (a real ERCOT
    # resource node from the bundled auction data, NOT a hub or load
    # zone -- exactly the kind of pair the old name-whitelist wrongly
    # excluded), one pair backed only by synthetic demo records, and one
    # pair that's real but for which ERCOT's live API returns no data in
    # this window (a genuine, data-driven "unavailable," not a guess).
    fake_records = [
        {"source": "MERCURY_ALL", "sink": "HB_HOUSTON", "is_synthetic": False},
        {"source": "MERCURY_ALL", "sink": "HB_SOUTH", "is_synthetic": False},
        {"source": "DEMO_SRC", "sink": "DEMO_SINK", "is_synthetic": True},
        {"source": "REAL_BUT_EMPTY_SRC", "sink": "REAL_BUT_EMPTY_SINK", "is_synthetic": False},
    ]
    fake_top_pairs = [
        {"source": "MERCURY_ALL", "sink": "HB_HOUSTON"},
        {"source": "MERCURY_ALL", "sink": "HB_SOUTH"},  # shares MERCURY_ALL with the pair above
        {"source": "DEMO_SRC", "sink": "DEMO_SINK"},
        {"source": "REAL_BUT_EMPTY_SRC", "sink": "REAL_BUT_EMPTY_SINK"},
    ]
    monkeypatch.setattr(main_module, "_records", lambda: fake_records)
    monkeypatch.setattr(main_module, "_tracked", lambda: (fake_records, fake_top_pairs))

    call_log = []

    def fake_fetch(client, settlement_point, date_from, date_to):
        call_log.append(settlement_point)
        prices = {"MERCURY_ALL": 20.0, "HB_HOUSTON": 30.0, "HB_SOUTH": 25.0}
        if settlement_point not in prices:
            return []  # ERCOT genuinely has no data for this point in this window
        return [{"delivery_date": "2026-01-01", "hour_ending": 1, "price": prices[settlement_point]}]

    monkeypatch.setattr(main_module, "fetch_settlement_point_hourly_prices", fake_fetch)

    r = client.get(
        "/api/pairs/settlement-summary",
        params={"date_from": "2026-01-01", "date_to": "2026-01-01"},
    )
    assert r.status_code == 200
    body = r.json()

    # MERCURY_ALL is shared by both real pairs but must only be fetched from
    # ERCOT once -- the redundant-request bug the node-level cache fixes.
    assert call_log.count("MERCURY_ALL") == 1
    assert call_log.count("HB_HOUSTON") == 1
    assert call_log.count("HB_SOUTH") == 1
    # The synthetic pair must never even trigger a live ERCOT lookup.
    assert "DEMO_SRC" not in call_log
    assert "DEMO_SINK" not in call_log

    pairs_by_key = {(p["source"], p["sink"]): p for p in body["pairs"]}
    assert pairs_by_key[("MERCURY_ALL", "HB_HOUSTON")]["daily_series"] == [
        {"date": "2026-01-01", "obligation_price": 10.0, "option_price": 10.0}
    ]
    assert pairs_by_key[("MERCURY_ALL", "HB_SOUTH")]["daily_series"] == [
        {"date": "2026-01-01", "obligation_price": 5.0, "option_price": 5.0}
    ]

    unavailable_by_key = {(p["source"], p["sink"]): p["reason"] for p in body["unavailable_pairs"]}
    assert "synthetic" in unavailable_by_key[("DEMO_SRC", "DEMO_SINK")]
    assert "no live settlement point price data" in unavailable_by_key[("REAL_BUT_EMPTY_SRC", "REAL_BUT_EMPTY_SINK")]


def test_pair_participants_filters_by_crr_type(monkeypatch):
    import app.main as main_module

    fake_records = [
        {"source": "HB_WEST", "sink": "HB_HOUSTON", "crr_type": "OBLIGATION", "time_of_use": "PEAK_WD",
         "auction_month": "2026-01", "clearing_price": 5.0, "awarded_mw": 10.0, "participant": "Obligation Co"},
        {"source": "HB_WEST", "sink": "HB_HOUSTON", "crr_type": "OPTION", "time_of_use": "PEAK_WD",
         "auction_month": "2026-01", "clearing_price": 1.0, "awarded_mw": 20.0, "participant": "Option Co"},
    ]
    monkeypatch.setattr(main_module, "_records", lambda: fake_records)

    r = client.get("/api/pairs/HB_WEST/HB_HOUSTON/participants", params={"crr_type": "OPTION"})
    assert r.status_code == 200
    names = {p["participant"] for p in r.json()["participants"]}
    assert names == {"Option Co"}
