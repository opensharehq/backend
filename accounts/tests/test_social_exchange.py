"""Tests for one-time social-login exchange code helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.core.cache.backends.locmem import LocMemCache
from django.core.cache.backends.redis import RedisCache
from django.test import SimpleTestCase

from accounts.services.social_exchange import (
    SocialExchangeUnavailableError,
    consume_exchange_code,
    create_exchange_code,
)
from accounts.services.social_exchange_store import RedisSocialExchangeStore


class FakeRedisClient:
    """Very small fake Redis client supporting the adapter operations."""

    def __init__(self, store):
        """Keep a shared store for write and atomic consume semantics."""
        self.store = store
        self.eval_calls = 0
        self.last_set_timeout = None

    def eval(self, script, numkeys, key):
        """Atomically fetch and delete the stored value for the given key."""
        del script, numkeys
        self.eval_calls += 1
        return self.store.pop(key, None)

    def set(self, key, value, ex=None):
        """Store the raw payload under the given Redis key."""
        self.last_set_timeout = ex
        self.store[key] = value
        return True

    def delete(self, key):
        """Delete the payload when present."""
        return int(self.store.pop(key, None) is not None)


class FakeRedisInnerCache:
    """Inner cache object exposing the Redis client accessor."""

    def __init__(self, store):
        """Initialize the Redis client facade."""
        self._client = FakeRedisClient(store)

    def get_client(self, key, *, write=False):
        """Return the single fake client instance."""
        del key, write
        return self._client


class FakeRedisCacheBackend(RedisCache):
    """Enough of Django's Redis cache backend for service tests."""

    def __init__(self):
        """Track stored keys and write timeout for assertions."""
        super().__init__("redis://cache.test/1", {})
        self._store = {}
        self._cache = FakeRedisInnerCache(self._store)

    def make_and_validate_key(self, key):
        """Return a deterministic Redis key."""
        return f"test-prefix:{key}"


class FakeRedisClientWithoutEval:
    """Redis client missing the atomic consume capability."""

    def set(self, key, value, ex=None):
        """Accept writes to mimic partial backend support."""
        del key, value, ex
        return True

    def delete(self, key):
        """Accept deletes to mimic partial backend support."""
        del key
        return 0


class FakeRedisInnerCacheWithoutEval:
    """Inner cache object exposing a degraded Redis client."""

    def get_client(self, key, *, write=False):
        """Return a client without the required atomic API."""
        del key, write
        return FakeRedisClientWithoutEval()


class FakeRedisCacheBackendWithoutEval(RedisCache):
    """Redis cache backend lacking the eval capability used for consume."""

    def __init__(self):
        """Set up the Redis-shaped backend without atomic consume support."""
        super().__init__("redis://cache.test/1", {})
        self._cache = FakeRedisInnerCacheWithoutEval()

    def make_and_validate_key(self, key):
        """Return a deterministic Redis key."""
        return f"test-prefix:{key}"


class SocialExchangeServiceTests(SimpleTestCase):
    """Cover atomic exchange-code storage semantics."""

    @patch("accounts.services.social_exchange_store._default_cache")
    def test_exchange_code_is_consumed_only_once(self, default_cache_mock):
        """A one-time code should only yield its payload for the first consumer."""
        backend = FakeRedisCacheBackend()
        default_cache_mock.return_value = backend
        user = SimpleNamespace(pk=42)

        code = create_exchange_code(user, "github")

        self.assertEqual(
            consume_exchange_code(code),
            {"user_id": user.pk, "provider": "github"},
        )
        self.assertIsNone(consume_exchange_code(code))
        self.assertEqual(
            backend._cache._client.last_set_timeout,
            settings.SOCIAL_AUTH_EXCHANGE_CODE_TTL_SECONDS,
        )
        self.assertEqual(backend._cache._client.eval_calls, 2)

    @patch(
        "accounts.services.social_exchange_store._default_cache", return_value=object()
    )
    def test_exchange_code_requires_usable_cache_backend(self, _cache_mock):
        """Unsafe cache backends lacking the cache API should be rejected."""
        user = SimpleNamespace(pk=7)

        with self.assertRaises(SocialExchangeUnavailableError):
            create_exchange_code(user, "github")

        with self.assertRaises(SocialExchangeUnavailableError):
            consume_exchange_code("missing-code")

    def test_exchange_code_rejects_dummy_cache_backend(self):
        """DummyCache silently drops writes and must be refused explicitly."""
        from django.core.cache.backends.dummy import DummyCache

        store = RedisSocialExchangeStore(cache_backend=DummyCache("dummy", {}))

        with self.assertRaises(SocialExchangeUnavailableError):
            store.store("any-key", {"user_id": 1, "provider": "github"}, 60)

    def test_exchange_code_works_with_locmem_cache_backend(self):
        """Local development without Redis should still round-trip codes."""
        backend = LocMemCache("social-exchange-test", {"TIMEOUT": 60, "OPTIONS": {}})
        user = SimpleNamespace(pk=21)

        with patch(
            "accounts.services.social_exchange_store._default_cache",
            return_value=backend,
        ):
            code = create_exchange_code(user, "github")

            self.assertEqual(
                consume_exchange_code(code),
                {"user_id": user.pk, "provider": "github"},
            )
            self.assertIsNone(consume_exchange_code(code))

    @patch(
        "accounts.services.social_exchange_store._default_cache",
        return_value=FakeRedisCacheBackendWithoutEval(),
    )
    def test_exchange_code_requires_atomic_consume_capability(self, _cache_mock):
        """Redis-shaped backends without atomic consume support should fail closed."""
        with self.assertRaises(SocialExchangeUnavailableError):
            consume_exchange_code("missing-code")
