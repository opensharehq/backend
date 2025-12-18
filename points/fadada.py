"""
FaDaDa (法大大) OpenAPI client helpers.

This module keeps request/signing logic inside a small client for business usage and
test mocking.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any, Protocol

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

API_SUBVERSION = "5.1"
SIGN_TYPE = "HMAC-SHA256"
DEFAULT_TIMEOUT_SECONDS = 10


class FadadaClientError(Exception):
    """Base error for FaDaDa client failures."""


class FadadaNotConfiguredError(FadadaClientError):
    """Raised when required configuration is missing."""


class FadadaRequestError(FadadaClientError):
    """Raised when HTTP request fails."""


@dataclass(frozen=True, slots=True)
class FadadaAccessToken:
    """Access token returned by FaDaDa."""

    token: str
    expires_in: int | None = None


class _WithdrawalSigningData(Protocol):
    real_name: str
    id_number: str
    phone_number: str
    bank_name: str
    bank_account: str


def _now_millis() -> str:
    return str(int(time.time() * 1000))


def _nonce_32_digits() -> str:
    return f"{secrets.randbelow(10**32):032d}"


def generate_fdd_sign(app_secret: str, param_map: dict[str, Any]) -> str:
    """
    Generate FaDaDa v5 API signature (HMAC-SHA256).

    Rules (aligned with the official SDK pseudo code):
    1) Filter out empty params; sort by ASCII; join into k=v&k2=v2...
    2) sign_text = sha256Hex(param_to_sign_str)
    3) secret_signing = hmacSha256(appSecret, timestamp)
    4) signature = hex(hmacSha256(secret_signing, sign_text)).toLowerCase()
    """
    filtered_params = {
        key: value
        for key, value in param_map.items()
        if value is not None and str(value).strip() != ""
    }
    sorted_keys = sorted(filtered_params.keys())
    param_to_sign_str = "&".join(
        [f"{key}={filtered_params[key]}" for key in sorted_keys]
    )

    timestamp = str(filtered_params.get("X-FASC-Timestamp", "")).strip()
    if not timestamp:
        msg = "X-FASC-Timestamp is required for signature generation"
        raise ValueError(msg)

    sign_text = hashlib.sha256(param_to_sign_str.encode("utf-8")).hexdigest()
    secret_signing = hmac.new(
        app_secret.encode("utf-8"),
        timestamp.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    signature = hmac.new(
        secret_signing,
        sign_text.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return signature


class FadadaClient:
    """
    A minimal FaDaDa OpenAPI v5.1 client.

    Note: `sign_with_template` is intentionally left as a placeholder. Implementing
    the actual signing workflow depends on the selected product capabilities and
    template configuration on FaDaDa side.
    """

    def __init__(
        self,
        *,
        api_host: str,
        app_id: str,
        app_secret: str,
        api_subversion: str = API_SUBVERSION,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Create a FaDaDa API client configured for a specific app."""
        self.api_host = api_host.rstrip("/") + "/"
        self.app_id = app_id
        self.app_secret = app_secret
        self.api_subversion = api_subversion
        self.timeout_seconds = timeout_seconds

        if not self.api_host or not self.app_id or not self.app_secret:
            msg = (
                "FaDaDa client is not configured (missing api_host/app_id/app_secret)."
            )
            raise FadadaNotConfiguredError(msg)

    @classmethod
    def from_settings(cls) -> FadadaClient:
        """Build a client instance from Django settings."""
        return cls(
            api_host=getattr(settings, "FDD_API_HOST", ""),
            app_id=getattr(settings, "FDD_APP_ID", ""),
            app_secret=getattr(settings, "FDD_APP_SECRET", ""),
            api_subversion=getattr(settings, "FDD_API_SUBVERSION", API_SUBVERSION),
            timeout_seconds=getattr(
                settings, "FDD_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS
            ),
        )

    def _build_signed_headers(
        self,
        *,
        access_token: str | None = None,
        biz_content: str | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        timestamp = _now_millis()
        nonce = _nonce_32_digits()

        param_map: dict[str, Any] = {
            "X-FASC-App-Id": self.app_id,
            "X-FASC-Sign-Type": SIGN_TYPE,
            "X-FASC-Timestamp": timestamp,
            "X-FASC-Nonce": nonce,
            "X-FASC-Api-SubVersion": self.api_subversion,
        }
        if access_token:
            param_map["X-FASC-AccessToken"] = access_token
        if biz_content is not None:
            param_map["bizContent"] = biz_content
        if extra_params:
            param_map.update(extra_params)

        signature = generate_fdd_sign(self.app_secret, param_map)

        headers = {
            key: str(value) for key, value in param_map.items() if key != "bizContent"
        }
        headers["X-FASC-Sign"] = signature
        return headers

    def get_access_token(self, *, force_refresh: bool = False) -> FadadaAccessToken:
        """Return a cached access token, refreshing when needed."""
        cache_key = f"fadada_access_token:{self.app_id}"
        if not force_refresh:
            cached = cache.get(cache_key)
            if isinstance(cached, dict) and cached.get("token"):
                return FadadaAccessToken(
                    token=str(cached["token"]),
                    expires_in=cached.get("expires_in"),
                )

        url = f"{self.api_host}service/get-access-token"
        headers = self._build_signed_headers(
            extra_params={"X-FASC-Grant-Type": "client_credential"},
        )

        try:
            response = requests.post(url, headers=headers, timeout=self.timeout_seconds)
            response.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - network failure
            msg = f"FaDaDa request failed: {exc}"
            raise FadadaRequestError(msg) from exc

        data = response.json()
        try:
            token = data["data"]["accessToken"]
        except (KeyError, TypeError) as exc:
            msg = f"Unexpected access token response: {data}"
            raise FadadaRequestError(msg) from exc

        expires_in = data.get("data", {}).get("expiresIn")
        token_obj = FadadaAccessToken(token=str(token), expires_in=expires_in)
        cache.set(
            cache_key,
            {"token": token_obj.token, "expires_in": token_obj.expires_in},
            timeout=getattr(settings, "FDD_ACCESS_TOKEN_CACHE_SECONDS", 50 * 60),
        )
        return token_obj

    def sign_with_template(
        self,
        *,
        withdrawal_data: _WithdrawalSigningData,
        signing_record_id: int,
    ) -> dict[str, Any]:
        """
        Initiate template-based signing.

        The withdrawal flow will call this method to initiate a signing task and
        typically trigger SMS signing for the actor. The exact endpoint/payload
        depends on your FaDaDa product configuration and template setup.
        """
        _ = (withdrawal_data, signing_record_id)
        msg = "sign_with_template is not implemented yet."
        raise NotImplementedError(msg)

    @staticmethod
    def dumps_biz_content(data: dict[str, Any]) -> str:
        """Serialize bizContent with a stable JSON format."""
        return json.dumps(data, separators=(",", ":"), ensure_ascii=False)
