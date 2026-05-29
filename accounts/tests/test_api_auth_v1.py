"""Tests for API v1 JWT authentication and social login flows."""

from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache.backends.redis import RedisCache
from django.test import TestCase, override_settings
from django.utils import timezone
from social_django.models import UserSocialAuth

from accounts.services.jwt_tokens import create_access_token, create_refresh_token
from accounts.services.social_exchange import SocialExchangeUnavailableError


class _RedisClientWithoutEval:
    """Redis client missing the atomic consume primitive."""

    def set(self, key, value, ex=None):
        """Accept writes to mimic partial backend support."""
        del key, value, ex
        return True

    def delete(self, key):
        """Accept deletes to mimic partial backend support."""
        del key
        return 0


class _RedisInnerCacheWithoutEval:
    """Inner cache exposing a degraded Redis client."""

    def get_client(self, key, *, write=False):
        """Return a client that cannot perform atomic consume."""
        del key, write
        return _RedisClientWithoutEval()


class _RedisCacheBackendWithoutEval(RedisCache):
    """Redis cache backend lacking the eval capability used by exchange consume."""

    def __init__(self):
        """Initialize the Redis-shaped cache backend for tests."""
        super().__init__("redis://cache.test/1", {})
        self._cache = _RedisInnerCacheWithoutEval()

    def make_and_validate_key(self, key):
        """Return a deterministic Redis key for tests."""
        return f"test-prefix:{key}"


class ApiV1AuthTests(TestCase):
    """Validate the v1 Django Ninja JWT auth endpoints."""

    verify_url = "/api/v1/auth/verify"
    refresh_url = "/api/v1/auth/refresh"
    logout_url = "/api/v1/auth/logout"

    def setUp(self):
        """Create a reusable user fixture."""
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username="api_user",
            email="api_user@example.com",
        )
        self.user.set_unusable_password()
        self.user.save(update_fields=["password"])

    def test_verify_returns_current_user_for_valid_token(self):
        """Valid access tokens should resolve the current user."""
        token = create_access_token(self.user)

        response = self.client.get(
            self.verify_url,
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "authenticated": True,
                "user": {
                    "id": self.user.pk,
                    "username": self.user.username,
                    "email": self.user.email,
                    "is_active": True,
                },
            },
        )

    def test_verify_requires_bearer_token(self):
        """Missing bearer tokens should be rejected."""
        response = self.client.get(self.verify_url)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {
                "code": "invalid_token",
                "message": "The token is invalid or has expired.",
            },
        )

    def test_verify_rejects_wrong_authorization_scheme(self):
        """Unexpected authorization schemes should be rejected."""
        response = self.client.get(
            self.verify_url,
            HTTP_AUTHORIZATION="Token abc123",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "invalid_token")

    def test_verify_rejects_forged_token(self):
        """Tokens signed with the wrong secret should be rejected."""
        forged_token = jwt.encode(
            {
                "sub": str(self.user.pk),
                "type": "access",
                "iat": timezone.now(),
                "exp": timezone.now() + timedelta(minutes=5),
            },
            "wrong-secret",
            algorithm=settings.JWT_ALGORITHM,
        )

        response = self.client.get(
            self.verify_url,
            HTTP_AUTHORIZATION=f"Bearer {forged_token}",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "invalid_token")

    def test_verify_rejects_expired_token(self):
        """Expired tokens should be rejected."""
        expired_token = jwt.encode(
            {
                "sub": str(self.user.pk),
                "type": "access",
                "iat": timezone.now() - timedelta(minutes=10),
                "exp": timezone.now() - timedelta(minutes=5),
            },
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )

        response = self.client.get(
            self.verify_url,
            HTTP_AUTHORIZATION=f"Bearer {expired_token}",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "invalid_token")

    def test_verify_rejects_token_for_disabled_user(self):
        """Previously issued tokens should fail once the user is disabled."""
        token = create_access_token(self.user)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.client.get(
            self.verify_url,
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "invalid_token")

    def test_verify_rejects_token_for_merged_user(self):
        """Previously issued tokens should fail once the user is merged."""
        token = create_access_token(self.user)
        target = self.User.objects.create_user(
            username="verify_merge_target",
            email="verify_merge_target@example.com",
        )
        self.user.merged_into = target
        self.user.is_active = False
        self.user.save(update_fields=["merged_into", "is_active"])

        response = self.client.get(
            self.verify_url,
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "invalid_token")

    def test_verify_rejects_token_for_deleted_user(self):
        """Previously issued tokens should fail once the user is deleted."""
        token = create_access_token(self.user)
        self.user.delete()

        response = self.client.get(
            self.verify_url,
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "invalid_token")

    def test_refresh_rotates_refresh_token(self):
        """Refreshing should return a new token pair."""
        refresh_token = create_refresh_token(self.user)

        response = self.client.post(
            self.refresh_url,
            {"refresh_token": refresh_token},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotEqual(payload["refresh_token"], refresh_token)
        self.assertEqual(payload["user"]["id"], self.user.id)
        self.assertEqual(payload["token_type"], "Bearer")
        self.assertEqual(payload["expires_in"], settings.JWT_ACCESS_TTL_SECONDS)
        self.assertTrue(payload["access_token"])

    def test_refresh_rejects_token_after_successful_rotation(self):
        """A refresh token should become unusable after a successful rotation."""
        refresh_token = create_refresh_token(self.user)

        first_response = self.client.post(
            self.refresh_url,
            {"refresh_token": refresh_token},
            content_type="application/json",
        )
        second_response = self.client.post(
            self.refresh_url,
            {"refresh_token": refresh_token},
            content_type="application/json",
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 401)
        self.assertEqual(second_response.json()["code"], "invalid_token")

    def test_refresh_rejects_invalid_token(self):
        """An unparseable refresh token should be rejected."""
        response = self.client.post(
            self.refresh_url,
            {"refresh_token": "not-a-token"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "invalid_token")

    def test_logout_revokes_refresh_token(self):
        """Logging out should revoke the provided refresh token."""
        refresh_token = create_refresh_token(self.user)

        response = self.client.post(
            self.logout_url,
            {"refresh_token": refresh_token},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"revoked": True})

        second_response = self.client.post(
            self.refresh_url,
            {"refresh_token": refresh_token},
            content_type="application/json",
        )
        self.assertEqual(second_response.status_code, 401)

    def test_logout_rejects_invalid_token(self):
        """Logging out with an invalid token should be rejected."""
        response = self.client.post(
            self.logout_url,
            {"refresh_token": "invalid"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "invalid_token")

    def test_me_endpoint_returns_authenticated_user(self):
        """The /me endpoint should return the authenticated user payload."""
        token = create_access_token(self.user)

        response = self.client.get(
            "/api/v1/auth/me",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], self.user.pk)
        self.assertEqual(response.json()["username"], self.user.username)

    @patch("accounts.api_v1.consume_exchange_code")
    def test_social_exchange_code_can_only_be_used_once(self, consume_mock):
        """The exchange endpoint should reject a reused one-time code."""
        consume_mock.side_effect = [
            {"user_id": self.user.pk, "provider": "github"},
            None,
        ]

        first_response = self.client.post(
            "/api/v1/auth/social/exchange",
            {"exchange_code": "one-time-code"},
            content_type="application/json",
        )
        second_response = self.client.post(
            "/api/v1/auth/social/exchange",
            {"exchange_code": "one-time-code"},
            content_type="application/json",
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertTrue(first_response.json()["access_token"])
        self.assertEqual(second_response.status_code, 401)
        self.assertEqual(second_response.json()["code"], "invalid_exchange_code")

    @patch(
        "accounts.services.social_exchange_store._default_cache",
        return_value=_RedisCacheBackendWithoutEval(),
    )
    def test_social_exchange_returns_503_when_exchange_storage_unavailable(
        self,
        _cache_mock,
    ):
        """The exchange endpoint should fail closed when Redis support is missing."""
        response = self.client.post(
            "/api/v1/auth/social/exchange",
            {"exchange_code": "one-time-code"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "social_exchange_unavailable")

    @override_settings(
        FRONTEND_APP_URL="https://frontend.example",
        FRONTEND_SOCIAL_CALLBACK_PATH="/auth/social/callback",
    )
    @patch("accounts.api_v1._get_provider_or_error", return_value={})
    @patch(
        "accounts.api_v1.create_exchange_code",
        side_effect=SocialExchangeUnavailableError("redis required"),
    )
    def test_social_callback_redirects_with_authentication_failed_when_exchange_creation_fails(
        self,
        _create_exchange_code_mock,
        _provider_mock,
    ):
        """The SPA handoff should fail safely when an exchange code cannot be created."""
        self.client.force_login(self.user)
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="github-1")

        response = self.client.get("/api/v1/auth/social/github/callback")

        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlparse(response.url).query)
        self.assertEqual(query["provider"], ["github"])
        self.assertEqual(query["error"], ["authentication_failed"])
