"""Tests for one-time social-login exchange code helpers."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from accounts.services.social_exchange import (
    SocialExchangeUnavailableError,
    consume_exchange_code,
    create_exchange_code,
)


class FakeRedisSerializer:
    """Serialize payloads the same way the Redis cache backend does."""

    def dumps(self, value):
        """Serialize Python values to bytes."""
        return json.dumps(value).encode()

    def loads(self, value):
        """Deserialize bytes back to Python values."""
        return json.loads(value.decode())


class FakeRedisClient:
    """Very small fake Redis client supporting the Lua eval used in production."""

    def __init__(self, store):
        """Keep a shared store for atomic pop semantics."""
        self.store = store
        self.eval_calls = 0

    def eval(self, script, numkeys, key):
        """Atomically fetch and delete the stored value for the given key."""
        del script, numkeys
        self.eval_calls += 1
        return self.store.pop(key, None)


class FakeRedisInnerCache:
    """Inner cache object exposing serializer and client accessors."""

    def __init__(self, store):
        """Initialize serializer and Redis client facade."""
        self._serializer = FakeRedisSerializer()
        self._client = FakeRedisClient(store)

    def get_client(self, key, *, write=False):
        """Return the single fake client instance."""
        del key, write
        return self._client


class FakeRedisCacheBackend:
    """Enough of Django's Redis cache backend for service tests."""

    def __init__(self):
        """Track stored keys and write timeout for assertions."""
        self._store = {}
        self._cache = FakeRedisInnerCache(self._store)
        self.last_timeout = None

    def make_and_validate_key(self, key):
        """Return a deterministic Redis key."""
        return f"test-prefix:{key}"

    def set(self, key, value, timeout):
        """Serialize and store the value under the derived key."""
        self.last_timeout = timeout
        redis_key = self.make_and_validate_key(key)
        self._store[redis_key] = self._cache._serializer.dumps(value)


class SocialExchangeServiceTests(SimpleTestCase):
    """Cover atomic exchange-code storage semantics."""

    @patch("accounts.services.social_exchange._redis_cache")
    def test_exchange_code_is_consumed_only_once(self, redis_cache_mock):
        """A one-time code should only yield its payload for the first consumer."""
        backend = FakeRedisCacheBackend()
        redis_cache_mock.return_value = backend
        user = SimpleNamespace(pk=42)

        code = create_exchange_code(user, "github")

        self.assertEqual(
            consume_exchange_code(code),
            {"user_id": user.pk, "provider": "github"},
        )
        self.assertIsNone(consume_exchange_code(code))
        self.assertEqual(
            backend.last_timeout,
            settings.SOCIAL_AUTH_EXCHANGE_CODE_TTL_SECONDS,
        )
        self.assertEqual(backend._cache._client.eval_calls, 2)

    @patch("accounts.services.social_exchange._default_cache", return_value=object())
    def test_exchange_code_requires_redis_cache_backend(self, _cache_mock):
        """Unsafe cache backends should be rejected instead of used non-atomically."""
        user = SimpleNamespace(pk=7)

        with self.assertRaises(SocialExchangeUnavailableError):
            create_exchange_code(user, "github")

        with self.assertRaises(SocialExchangeUnavailableError):
            consume_exchange_code("missing-code")
