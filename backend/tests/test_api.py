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


def test_dashboard_endpoint_shape():
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    body = r.json()
    for key in [
        "latest_auction_month", "latest_month_mw_awarded", "active_participant_count",
        "tracked_pair_count", "top_opportunity_pairs", "top_participants",
        "tier_distribution", "monthly_mw_trend",
    ]:
        assert key in body
    assert len(body["top_opportunity_pairs"]) == 5
    assert len(body["top_participants"]) == 5


def test_dashboard_tier_distribution_sums_to_pair_count():
    r = client.get("/api/dashboard")
    body = r.json()
    dist = body["tier_distribution"]
    assert set(dist.keys()) == {"High", "Medium", "Low"}
    # A tracked pair with real activity but zero OBLIGATION-type records
    # (e.g. Option-only trading on that path) has no economic-value signal
    # to score and is skipped -- see scoring.score_all_pairs, `if
    # m["average"] is None: continue`. So this can be less than, but never
    # more than, the tracked pair count.
    assert 0 < sum(dist.values()) <= body["tracked_pair_count"]
    assert all(v >= 0 for v in dist.values())


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


def test_live_binding_constraints_success_with_mocked_client(monkeypatch):
    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")

    import app.main as main_module

    class FakeClient:
        def get_dam_shadow_prices(self, date_from, date_to, page=1, size=1000):
            return {
                "fields": [
                    {"name": "deliveryDate"}, {"name": "hourEnding"}, {"name": "constraintName"},
                    {"name": "contingencyName"}, {"name": "shadowPrice"}, {"name": "fromStation"},
                    {"name": "toStation"},
                ],
                "data": [["2026-01-01T00:00:00", 14, "RN_LIMIT_WEST_345", "BASE CASE", 42.1, "STA_A", "STA_B"]],
                "_meta": {"totalPages": 1},
            }

    monkeypatch.setattr(main_module, "_get_live_client", lambda: FakeClient())

    r = client.get("/api/live/binding-constraints", params={"date_from": "2026-01-01", "date_to": "2026-01-02"})
    assert r.status_code == 200
    body = r.json()
    # Shaped into the same named, snake_case fields as the Streamlit app's
    # identical helper -- see main.py's live_binding_constraints docstring.
    assert body["constraints"] == [{
        "delivery_date": "2026-01-01",
        "hour_ending": 14,
        "constraint_name": "RN_LIMIT_WEST_345",
        "contingency_name": "BASE CASE",
        "shadow_price": 42.1,
        "from_station": "STA_A",
        "to_station": "STA_B",
    }]
    assert body["truncated"] is False
