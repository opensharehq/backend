"""Redis-backed storage adapter for one-time social-login exchange codes."""

from __future__ import annotations

import json
from typing import Any

from django.core.cache import caches
from django.core.cache.backends.redis import RedisCache

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


def _default_cache():
    """Return the configured default cache backend."""
    return caches["default"]


class RedisSocialExchangeStore:
    """Store exchange payloads using a Redis cache backend."""

    def __init__(self, cache_backend: RedisCache | None = None):
        """Allow tests to inject a cache backend while defaulting to Django cache."""
        self.cache_backend = (
            _default_cache() if cache_backend is None else cache_backend
        )

    def store(self, key: str, payload: dict[str, Any], timeout: int | None) -> None:
        """Persist a one-time payload under the given cache key."""
        cache_backend = self._redis_cache()
        redis_key = cache_backend.make_and_validate_key(key)
        redis_timeout = cache_backend.get_backend_timeout(timeout)
        redis_client = self._redis_client(
            cache_backend,
            redis_key,
            write=True,
            required_methods=("set", "delete"),
        )

        if redis_timeout == 0:
            redis_client.delete(redis_key)
            return

        set_kwargs = {} if redis_timeout is None else {"ex": redis_timeout}
        redis_client.set(redis_key, self._serialize(payload), **set_kwargs)

    def consume(self, key: str) -> dict[str, Any] | None:
        """Atomically fetch and invalidate a one-time payload."""
        cache_backend = self._redis_cache()
        redis_key = cache_backend.make_and_validate_key(key)
        redis_client = self._redis_client(
            cache_backend,
            redis_key,
            write=True,
            required_methods=("eval",),
        )
        payload = redis_client.eval(ATOMIC_GET_DELETE_SCRIPT, 1, redis_key)
        if payload in (None, False):
            return None
        return self._deserialize(payload)

    def _redis_cache(self) -> RedisCache:
        """Require the default cache to expose Django's Redis backend."""
        if not isinstance(self.cache_backend, RedisCache):
            msg = "Social exchange codes require Redis-backed cache support."
            raise SocialExchangeUnavailableError(msg)
        return self.cache_backend

    def _redis_client(
        self,
        cache_backend: RedisCache,
        redis_key: str,
        *,
        write: bool,
        required_methods: tuple[str, ...],
    ):
        """Resolve a Redis client or raise a stable storage-unavailable error."""
        try:
            cache_client = cache_backend._cache
        except ImportError as exc:
            msg = "Social exchange cache backend could not initialize Redis support."
            raise SocialExchangeUnavailableError(msg) from exc

        get_client = getattr(cache_client, "get_client", None)
        if not callable(get_client):
            msg = "Social exchange cache backend lacks Redis client access."
            raise SocialExchangeUnavailableError(msg)

        redis_client = get_client(redis_key, write=write)
        missing_methods = [
            method
            for method in required_methods
            if not callable(getattr(redis_client, method, None))
        ]
        if missing_methods:
            missing = ", ".join(sorted(missing_methods))
            msg = (
                "Social exchange cache backend is missing required Redis "
                f"methods: {missing}."
            )
            raise SocialExchangeUnavailableError(msg)

        return redis_client

    def _serialize(self, payload: dict[str, Any]) -> bytes:
        """Encode payloads without depending on the cache backend serializer."""
        return json.dumps(payload, separators=(",", ":")).encode()

    def _deserialize(self, payload: Any) -> dict[str, Any]:
        """Decode the stored payload into the expected dict structure."""
        try:
            decoded_payload = json.loads(payload)
        except (TypeError, UnicodeDecodeError, ValueError) as exc:
            msg = "Social exchange payload could not be decoded."
            raise SocialExchangeUnavailableError(msg) from exc

        if not isinstance(decoded_payload, dict) or not {
            "provider",
            "user_id",
        }.issubset(decoded_payload):
            msg = "Social exchange payload is malformed."
            raise SocialExchangeUnavailableError(msg)

        return decoded_payload
