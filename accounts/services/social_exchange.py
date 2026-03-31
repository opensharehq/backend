"""One-time social-login exchange codes for SPA handoff."""

from __future__ import annotations

import secrets
from typing import Any

from django.conf import settings
from django.core.cache import cache

EXCHANGE_CODE_CACHE_PREFIX = "accounts:social_exchange"


def _cache_key(code: str) -> str:
    return f"{EXCHANGE_CODE_CACHE_PREFIX}:{code}"


def create_exchange_code(user, provider: str) -> str:
    """Create a short-lived one-time code for social-login completion."""
    code = secrets.token_urlsafe(32)
    cache.set(
        _cache_key(code),
        {"user_id": user.pk, "provider": provider},
        settings.SOCIAL_AUTH_EXCHANGE_CODE_TTL_SECONDS,
    )
    return code


def consume_exchange_code(code: str) -> dict[str, Any] | None:
    """Consume and invalidate a one-time social-login exchange code."""
    key = _cache_key(code)
    payload = cache.get(key)
    if payload is None:
        return None

    cache.delete(key)
    return payload
