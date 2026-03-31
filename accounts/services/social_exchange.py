"""One-time social-login exchange codes for SPA handoff."""

from __future__ import annotations

import secrets
from typing import Any

from django.conf import settings
from django.core.cache import caches
from django.core.cache.backends.redis import RedisCache

EXCHANGE_CODE_CACHE_PREFIX = "accounts:social_exchange"
ATOMIC_GET_DELETE_SCRIPT = """
local value = redis.call("GET", KEYS[1])
if not value then
    return false
end
redis.call("DEL", KEYS[1])
return value
"""


class SocialExchangeUnavailableError(RuntimeError):
    """Raised when one-time exchange code storage is unavailable."""


def _cache_key(code: str) -> str:
    return f"{EXCHANGE_CODE_CACHE_PREFIX}:{code}"


def _default_cache():
    """Return the configured default cache backend."""
    return caches["default"]


def _redis_cache() -> RedisCache:
    """Return the default cache when it provides Redis primitives."""
    cache_backend = _default_cache()
    if not isinstance(cache_backend, RedisCache):
        msg = "Social exchange codes require Redis-backed cache support."
        raise SocialExchangeUnavailableError(msg)
    return cache_backend


def create_exchange_code(user, provider: str) -> str:
    """Create a short-lived one-time code for social-login completion."""
    code = secrets.token_urlsafe(32)
    cache_backend = _redis_cache()
    cache_backend.set(
        _cache_key(code),
        {"user_id": user.pk, "provider": provider},
        settings.SOCIAL_AUTH_EXCHANGE_CODE_TTL_SECONDS,
    )
    return code


def consume_exchange_code(code: str) -> dict[str, Any] | None:
    """Consume and invalidate a one-time social-login exchange code."""
    cache_backend = _redis_cache()
    key = _cache_key(code)
    redis_key = cache_backend.make_and_validate_key(key)
    redis_client = cache_backend._cache.get_client(redis_key, write=True)
    payload = redis_client.eval(ATOMIC_GET_DELETE_SCRIPT, 1, redis_key)
    if payload in (None, False):
        return None

    return cache_backend._cache._serializer.loads(payload)
