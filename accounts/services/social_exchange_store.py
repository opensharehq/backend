"""Cache-backed storage adapter for one-time social-login exchange codes."""

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

SOCIAL_EXCHANGE_CACHE_ALIAS = "social_exchange"


class SocialExchangeUnavailableError(RuntimeError):
    """Raised when one-time exchange code storage is unavailable."""


def _default_cache():
    """Return the configured cache backend for social exchange codes.

    Falls back to the default cache when the dedicated ``social_exchange``
    alias is not configured (older deployments).
    """
    try:
        return caches[SOCIAL_EXCHANGE_CACHE_ALIAS]
    except KeyError:
        return caches["default"]


class RedisSocialExchangeStore:
    """Store exchange payloads using the configured Django cache backend.

    Prefers atomic Lua ``GET``/``DEL`` when backed by Redis. For other cache
    backends (e.g. ``LocMemCache`` in local development without Redis) falls
    back to the standard Django cache ``set``/``get``/``delete`` API. The
    ``DummyCache`` backend is explicitly rejected because it silently
    discards writes, which would make exchange codes unusable.
    """

    # Backends that silently discard writes and therefore cannot persist codes.
    _UNSUPPORTED_BACKENDS = ("DummyCache",)

    def __init__(self, cache_backend=None):
        """Allow tests to inject a cache backend while defaulting to Django cache."""
        self.cache_backend = (
            _default_cache() if cache_backend is None else cache_backend
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(self, key: str, payload: dict[str, Any], timeout: int | None) -> None:
        """Persist a one-time payload under the given cache key."""
        serialized = self._serialize(payload)

        if isinstance(self.cache_backend, RedisCache):
            self._store_via_redis(key, serialized, timeout)
            return

        cache_backend = self._generic_cache()
        if timeout == 0:
            cache_backend.delete(key)
            return
        cache_backend.set(key, serialized, timeout)

    def consume(self, key: str) -> dict[str, Any] | None:
        """Atomically fetch and invalidate a one-time payload."""
        if isinstance(self.cache_backend, RedisCache):
            payload = self._consume_via_redis(key)
        else:
            cache_backend = self._generic_cache()
            payload = cache_backend.get(key)
            if payload is not None:
                cache_backend.delete(key)

        if payload in (None, False):
            return None
        return self._deserialize(payload)

    # ------------------------------------------------------------------
    # Redis-backed (atomic) path
    # ------------------------------------------------------------------

    def _store_via_redis(
        self, key: str, serialized: bytes, timeout: int | None
    ) -> None:
        cache_backend = self.cache_backend
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
        redis_client.set(redis_key, serialized, **set_kwargs)

    def _consume_via_redis(self, key: str) -> Any:
        cache_backend = self.cache_backend
        redis_key = cache_backend.make_and_validate_key(key)
        redis_client = self._redis_client(
            cache_backend,
            redis_key,
            write=True,
            required_methods=("eval",),
        )
        return redis_client.eval(ATOMIC_GET_DELETE_SCRIPT, 1, redis_key)

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

    # ------------------------------------------------------------------
    # Generic Django cache path
    # ------------------------------------------------------------------

    def _generic_cache(self):
        """Validate and return a Django cache backend usable for persistence."""
        cache_backend = self.cache_backend
        backend_cls_name = type(cache_backend).__name__
        if backend_cls_name in self._UNSUPPORTED_BACKENDS:
            msg = (
                "Social exchange codes cannot be stored in a "
                f"{backend_cls_name} backend. Configure REDIS_URL or ensure "
                "the 'social_exchange' cache alias points to a real cache "
                "backend (e.g. LocMemCache)."
            )
            raise SocialExchangeUnavailableError(msg)

        missing = [
            method
            for method in ("set", "get", "delete")
            if not callable(getattr(cache_backend, method, None))
        ]
        if missing:
            missing_list = ", ".join(sorted(missing))
            msg = (
                "Social exchange cache backend is missing required cache "
                f"methods: {missing_list}."
            )
            raise SocialExchangeUnavailableError(msg)

        return cache_backend

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

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
