"""
Client for ERCOT's real Public Data API (api.ercot.com).

This is a genuine, separate system from the CRR Auction Results MIS file
browser discussed in domain.py -- it is a proper REST API with OAuth2
password-grant ("ROPC") authentication and a subscription key, documented at
https://developer.ercot.com/applications/pubapi/ and explorable/registerable
for free at https://apiexplorer.ercot.com/.

It does NOT expose CRR auction awards (Source, Sink, clearing price,
Account Holder) as an endpoint -- that data is still MIS-archive-only (see
ingestion.py). It DOES expose, live and free once registered:
  - Day-Ahead Market Settlement Point Prices (NP4-190-CD) -- the real hourly
    price at every ERCOT hub and load zone. The spread between two
    settlement points' DAM prices *is* what a Point-To-Point (PTP)
    Obligation CRR pays its holder, so this is a legitimate, live proxy for
    realized CRR/congestion value -- arguably a more decision-relevant
    number for a trader than a stale auction clearing price.
  - Day-Ahead Market Shadow Prices (NP4-191-CD) -- the binding transmission
    constraints driving that congestion, by name. This is real
    "why is this congested" data, not descriptive statistics.

Registration (free, ~5 minutes):
  1. Create an account at https://apiexplorer.ercot.com/
  2. Subscribe to "Public API" on that portal to get a subscription key
     (Ocp-Apim-Subscription-Key)
  3. Set three environment variables before starting the backend:
       ERCOT_API_USERNAME=<the email you registered with>
       ERCOT_API_PASSWORD=<your apiexplorer.ercot.com password>
       ERCOT_API_SUBSCRIPTION_KEY=<the subscription key from step 2>

Known limitation (disclosed upstream by ERCOT and by third-party clients
such as gridstatus.io): this API is explicitly a work in progress and has
had documented reliability issues (intermittent timeouts / 500s under
load -- see https://github.com/ercot/api-specs/discussions/124). This
client retries with backoff on 429/5xx/timeouts and surfaces a clear error
after exhausting retries rather than hanging silently.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import requests

TOKEN_URL = (
    "https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/"
    "B2C_1_PUBAPI-ROPC-FLOW/oauth2/v2.0/token"
)
PUBLIC_BASE_URL = "https://api.ercot.com/api/public-reports"

# Fixed client_id ERCOT documents for the public ROPC flow (not a secret --
# it identifies the "ERCOT Public API" application, same for every caller).
CLIENT_ID = "fec253ea-0d06-4272-a5e6-b478baeecd70"

# Confirmed-working real endpoints (verified against ERCOT's own API
# discussion forum and the gridstatus.io open-source client as of this
# writing -- ERCOT has changed these before without notice, so if a call
# starts failing, check https://apiexplorer.ercot.com/ for the current path).
DAM_SETTLEMENT_POINT_PRICES_ENDPOINT = "/np4-190-cd/dam_stlmnt_pnt_prices"
DAM_SHADOW_PRICES_ENDPOINT = "/np4-191-cd/dam_shadow_prices"

TOKEN_EXPIRATION_SECONDS = 3600
REQUEST_TIMEOUT = (10, 30)  # (connect, read) seconds
MAX_RETRIES = 3


class ErcotApiError(RuntimeError):
    """Raised for any failure talking to the live ERCOT Public API, with a
    human-readable, actionable message (never a raw traceback dump)."""


class ErcotApiCredentialsError(ErcotApiError):
    """Raised when required credentials are missing."""


@dataclass
class _Token:
    value: str
    expires_at: float


class ErcotApiClient:
    """Thin, dependency-light client for the endpoints this project needs.

    Deliberately does not try to be a general-purpose ERCOT SDK (see
    gridstatus.io's `gridstatus.ercot_api` for that) -- just enough to fetch
    real DAM settlement point prices and shadow prices, tested and correct.
    """

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        subscription_key: str | None = None,
        session: requests.Session | None = None,
    ):
        self.username = username or os.environ.get("ERCOT_API_USERNAME")
        self.password = password or os.environ.get("ERCOT_API_PASSWORD")
        self.subscription_key = subscription_key or os.environ.get(
            "ERCOT_API_SUBSCRIPTION_KEY"
        )
        self._session = session or requests.Session()
        self._token: _Token | None = None

    @staticmethod
    def is_configured() -> bool:
        """True if the three required env vars are all set. Does not verify
        they are *valid* -- that only happens on first real call."""
        return all(
            os.environ.get(k)
            for k in ("ERCOT_API_USERNAME", "ERCOT_API_PASSWORD", "ERCOT_API_SUBSCRIPTION_KEY")
        )

    def _require_credentials(self) -> None:
        missing = [
            name
            for name, val in (
                ("ERCOT_API_USERNAME", self.username),
                ("ERCOT_API_PASSWORD", self.password),
                ("ERCOT_API_SUBSCRIPTION_KEY", self.subscription_key),
            )
            if not val
        ]
        if missing:
            raise ErcotApiCredentialsError(
                "Missing ERCOT Public API credentials: " + ", ".join(missing) + ". "
                "Register for free at https://apiexplorer.ercot.com/, subscribe to "
                "'Public API' to get a subscription key, then set these as "
                "environment variables before starting the backend."
            )

    def get_token(self) -> str:
        """Fetch a fresh ID token via the OAuth2 password grant. Tokens are
        valid for 1 hour and cannot be refreshed -- only reissued."""
        self._require_credentials()
        payload = {
            "grant_type": "password",
            "username": self.username,
            "password": self.password,
            "response_type": "id_token",
            "scope": f"openid {CLIENT_ID} offline_access",
            "client_id": CLIENT_ID,
        }
        try:
            response = self._session.post(TOKEN_URL, data=payload, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as e:
            raise ErcotApiError(f"Could not reach ERCOT's token endpoint: {e}") from e

        if response.status_code != 200:
            raise ErcotApiError(
                f"ERCOT rejected the login (HTTP {response.status_code}). "
                "Double-check ERCOT_API_USERNAME/ERCOT_API_PASSWORD match your "
                "apiexplorer.ercot.com account."
            )

        data = response.json()
        token = data.get("id_token")
        if not token:
            raise ErcotApiError("ERCOT's token response did not include an id_token.")

        self._token = _Token(value=token, expires_at=time.time() + TOKEN_EXPIRATION_SECONDS - 60)
        return token

    def _ensure_token(self) -> str:
        if self._token is None or time.time() >= self._token.expires_at:
            self.get_token()
        return self._token.value

    def _headers(self) -> dict:
        self._require_credentials()
        return {
            "Authorization": f"Bearer {self._ensure_token()}",
            "Ocp-Apim-Subscription-Key": self.subscription_key,
            "Accept": "application/json",
        }

    def _get(self, path: str, params: dict) -> dict:
        url = f"{PUBLIC_BASE_URL}{path}"
        delay = 1.0
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._session.get(
                    url, headers=self._headers(), params=params, timeout=REQUEST_TIMEOUT
                )
            except requests.exceptions.Timeout as e:
                last_error = e
                time.sleep(delay)
                delay *= 2
                continue
            except requests.exceptions.RequestException as e:
                raise ErcotApiError(f"Could not reach ERCOT's API at {path}: {e}") from e

            if response.status_code == 200:
                return response.json()
            if response.status_code == 429 or response.status_code >= 500:
                last_error = ErcotApiError(
                    f"ERCOT API returned HTTP {response.status_code} for {path} "
                    f"(attempt {attempt}/{MAX_RETRIES})."
                )
                time.sleep(delay)
                delay *= 2
                continue
            # 4xx other than 429: not retryable
            raise ErcotApiError(
                f"ERCOT API rejected the request to {path} with HTTP "
                f"{response.status_code}: {response.text[:300]}"
            )

        raise ErcotApiError(
            f"ERCOT API at {path} did not respond successfully after {MAX_RETRIES} "
            f"attempts. ERCOT's Public API is a documented work-in-progress and has "
            f"known intermittent reliability issues -- this is very likely transient; "
            f"try again shortly. Last error: {last_error}"
        )

    def get_dam_settlement_point_prices(
        self,
        settlement_point: str,
        delivery_date_from: str,
        delivery_date_to: str,
        page: int = 1,
        size: int = 1000,
    ) -> dict:
        """Real, live Day-Ahead Market hourly settlement point prices
        (NP4-190-CD) for one settlement point over a date range.

        Args:
            settlement_point: an ERCOT settlement point code, e.g. "HB_WEST".
            delivery_date_from / delivery_date_to: "YYYY-MM-DD".
        """
        return self._get(
            DAM_SETTLEMENT_POINT_PRICES_ENDPOINT,
            {
                "settlementPoint": settlement_point,
                "deliveryDateFrom": delivery_date_from,
                "deliveryDateTo": delivery_date_to,
                "page": page,
                "size": size,
            },
        )

    def get_dam_shadow_prices(
        self,
        delivery_date_from: str,
        delivery_date_to: str,
        page: int = 1,
        size: int = 1000,
    ) -> dict:
        """Real, live Day-Ahead Market shadow prices (NP4-191-CD): the
        binding transmission constraints for each hour, by name, and the
        shadow price (marginal value, $/MW) of each. This is the real
        "why is this path congested" data."""
        return self._get(
            DAM_SHADOW_PRICES_ENDPOINT,
            {
                "deliveryDateFrom": delivery_date_from,
                "deliveryDateTo": delivery_date_to,
                "page": page,
                "size": size,
            },
        )
