from unittest.mock import MagicMock, patch

import pytest
import requests

from app.ercot_live import (
    ErcotApiClient,
    ErcotApiCredentialsError,
    ErcotApiError,
    PUBLIC_BASE_URL,
    TOKEN_URL,
)


def _client(**overrides):
    kwargs = dict(username="trader@example.com", password="hunter2", subscription_key="sub-key-123")
    kwargs.update(overrides)
    return ErcotApiClient(**kwargs)


def _mock_response(status_code=200, json_data=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    return resp


def test_missing_credentials_raises_clear_error(monkeypatch):
    monkeypatch.delenv("ERCOT_API_USERNAME", raising=False)
    monkeypatch.delenv("ERCOT_API_PASSWORD", raising=False)
    monkeypatch.delenv("ERCOT_API_SUBSCRIPTION_KEY", raising=False)
    client = ErcotApiClient()
    with pytest.raises(ErcotApiCredentialsError, match="ERCOT_API_USERNAME"):
        client.get_token()


def test_is_configured_reflects_env(monkeypatch):
    monkeypatch.delenv("ERCOT_API_USERNAME", raising=False)
    monkeypatch.delenv("ERCOT_API_PASSWORD", raising=False)
    monkeypatch.delenv("ERCOT_API_SUBSCRIPTION_KEY", raising=False)
    assert ErcotApiClient.is_configured() is False

    monkeypatch.setenv("ERCOT_API_USERNAME", "a")
    monkeypatch.setenv("ERCOT_API_PASSWORD", "b")
    monkeypatch.setenv("ERCOT_API_SUBSCRIPTION_KEY", "c")
    assert ErcotApiClient.is_configured() is True


def test_get_token_success():
    client = _client()
    with patch.object(client._session, "post") as mock_post:
        mock_post.return_value = _mock_response(200, {"id_token": "abc123"})
        token = client.get_token()

    assert token == "abc123"
    assert client._token.value == "abc123"
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args.args[0] == TOKEN_URL
    assert call_args.kwargs["data"]["username"] == "trader@example.com"
    assert call_args.kwargs["data"]["grant_type"] == "password"


def test_get_token_missing_id_token_in_response_raises():
    client = _client()
    with patch.object(client._session, "post") as mock_post:
        mock_post.return_value = _mock_response(200, {"error": "nope"})
        with pytest.raises(ErcotApiError, match="id_token"):
            client.get_token()


def test_get_token_bad_status_raises_actionable_message():
    client = _client()
    with patch.object(client._session, "post") as mock_post:
        mock_post.return_value = _mock_response(401, {})
        with pytest.raises(ErcotApiError, match="rejected the login"):
            client.get_token()


def test_get_token_network_error_raises_actionable_message():
    client = _client()
    with patch.object(client._session, "post", side_effect=requests.exceptions.ConnectionError("boom")):
        with pytest.raises(ErcotApiError, match="Could not reach"):
            client.get_token()


def test_token_is_cached_and_not_refetched_before_expiry():
    client = _client()
    with patch.object(client._session, "post") as mock_post:
        mock_post.return_value = _mock_response(200, {"id_token": "tok1"})
        client.get_token()
        # second call to a method that needs a token should NOT re-post
        headers = client._headers()
    assert mock_post.call_count == 1
    assert headers["Authorization"] == "Bearer tok1"


def test_token_is_refetched_after_expiry():
    client = _client()
    with patch.object(client._session, "post") as mock_post:
        mock_post.return_value = _mock_response(200, {"id_token": "tok1"})
        client.get_token()
    client._token.expires_at = 0  # force expiry
    with patch.object(client._session, "post") as mock_post2:
        mock_post2.return_value = _mock_response(200, {"id_token": "tok2"})
        headers = client._headers()
    assert mock_post2.call_count == 1
    assert headers["Authorization"] == "Bearer tok2"


def test_get_dam_settlement_point_prices_calls_correct_url_and_params():
    client = _client()
    fake_response = {"fields": [{"name": "deliveryDate"}], "data": [], "_meta": {"totalPages": 1}}
    with patch.object(client._session, "post") as mock_post, \
         patch.object(client._session, "get") as mock_get:
        mock_post.return_value = _mock_response(200, {"id_token": "tok"})
        mock_get.return_value = _mock_response(200, fake_response)
        result = client.get_dam_settlement_point_prices("HB_WEST", "2026-01-01", "2026-01-31")

    assert result == fake_response
    call = mock_get.call_args
    assert call.args[0] == f"{PUBLIC_BASE_URL}/np4-190-cd/dam_stlmnt_pnt_prices"
    assert call.kwargs["params"]["settlementPoint"] == "HB_WEST"
    assert call.kwargs["params"]["deliveryDateFrom"] == "2026-01-01"
    assert call.kwargs["params"]["deliveryDateTo"] == "2026-01-31"
    assert call.kwargs["headers"]["Ocp-Apim-Subscription-Key"] == "sub-key-123"
    assert call.kwargs["headers"]["Authorization"] == "Bearer tok"


def test_get_dam_shadow_prices_calls_correct_endpoint():
    client = _client()
    fake_response = {"fields": [], "data": [], "_meta": {"totalPages": 1}}
    with patch.object(client._session, "post") as mock_post, \
         patch.object(client._session, "get") as mock_get:
        mock_post.return_value = _mock_response(200, {"id_token": "tok"})
        mock_get.return_value = _mock_response(200, fake_response)
        client.get_dam_shadow_prices("2026-01-01", "2026-01-02")

    call = mock_get.call_args
    assert call.args[0] == f"{PUBLIC_BASE_URL}/np4-191-cd/dam_shadow_prices"


def test_rate_limit_retries_then_succeeds():
    client = _client()
    ok_response = _mock_response(200, {"fields": [], "data": [], "_meta": {"totalPages": 1}})
    rate_limited = _mock_response(429, {}, text="slow down")
    with patch.object(client._session, "post") as mock_post, \
         patch.object(client._session, "get") as mock_get, \
         patch("app.ercot_live.time.sleep"):
        mock_post.return_value = _mock_response(200, {"id_token": "tok"})
        mock_get.side_effect = [rate_limited, ok_response]
        result = client.get_dam_shadow_prices("2026-01-01", "2026-01-02")

    assert result == {"fields": [], "data": [], "_meta": {"totalPages": 1}}
    assert mock_get.call_count == 2


def test_non_retryable_4xx_raises_immediately():
    client = _client()
    with patch.object(client._session, "post") as mock_post, \
         patch.object(client._session, "get") as mock_get:
        mock_post.return_value = _mock_response(200, {"id_token": "tok"})
        mock_get.return_value = _mock_response(400, {}, text="bad settlement point")
        with pytest.raises(ErcotApiError, match="400"):
            client.get_dam_settlement_point_prices("NOT_REAL", "2026-01-01", "2026-01-02")
    assert mock_get.call_count == 1


def test_exhausted_retries_raises_actionable_message():
    client = _client()
    with patch.object(client._session, "post") as mock_post, \
         patch.object(client._session, "get") as mock_get, \
         patch("app.ercot_live.time.sleep"):
        mock_post.return_value = _mock_response(200, {"id_token": "tok"})
        mock_get.return_value = _mock_response(500, {}, text="server error")
        with pytest.raises(ErcotApiError, match="work-in-progress"):
            client.get_dam_shadow_prices("2026-01-01", "2026-01-02")
    assert mock_get.call_count == 3  # MAX_RETRIES
