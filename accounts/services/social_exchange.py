"""One-time social-login exchange code helpers for SPA handoff."""

from __future__ import annotations

import secrets
from typing import Any

from django.conf import settings

from .social_exchange_store import (
    RedisSocialExchangeStore,
    SocialExchangeUnavailableError,
)

__all__ = [
    "SocialExchangeUnavailableError",
    "consume_exchange_code",
    "create_exchange_code",
]

EXCHANGE_CODE_CACHE_PREFIX = "accounts:social_exchange"


def _cache_key(code: str) -> str:
    return f"{EXCHANGE_CODE_CACHE_PREFIX}:{code}"


def _store() -> RedisSocialExchangeStore:
    """Build the storage adapter for exchange-code persistence."""
    return RedisSocialExchangeStore()


def create_exchange_code(user, provider: str) -> str:
    """Create a short-lived one-time code for social-login completion."""
    code = secrets.token_urlsafe(32)
    _store().store(
        _cache_key(code),
        {"user_id": user.pk, "provider": provider},
        settings.SOCIAL_AUTH_EXCHANGE_CODE_TTL_SECONDS,
    )
    return code


def consume_exchange_code(code: str) -> dict[str, Any] | None:
    """Consume and invalidate a one-time social-login exchange code."""
    return _store().consume(_cache_key(code))
