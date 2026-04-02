"""Tests for API v1 JWT authentication flows."""

from datetime import timedelta
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.cache.backends.redis import RedisCache
from django.test import TestCase, override_settings
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from social_django.models import UserSocialAuth

from accounts.services.jwt_tokens import create_access_token
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
    """Validate the v1 Django Ninja auth API."""

    login_url = "/api/v1/auth/login"
    verify_url = "/api/v1/auth/verify"

    def setUp(self):
        """Create a reusable user fixture."""
        self.User = get_user_model()
        self.password = "ApiLogin123!"  # noqa: S105 - test fixture password
        self.user = self.User.objects.create_user(
            username="api_user",
            email="api_user@example.com",
            password=self.password,
        )

    def test_login_with_username_returns_access_token(self):
        """Users can log in with username and receive a JWT."""
        response = self.client.post(
            self.login_url,
            {"account": self.user.username, "password": self.password},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["token_type"], "Bearer")
        self.assertEqual(payload["expires_in"], settings.JWT_ACCESS_TTL_SECONDS)
        self.assertTrue(payload["access_token"])
        self.assertEqual(payload["user"]["username"], self.user.username)
        self.assertEqual(payload["user"]["email"], self.user.email)

    def test_login_with_email_returns_access_token(self):
        """Users can log in with email and receive a JWT."""
        response = self.client.post(
            self.login_url,
            {"account": self.user.email, "password": self.password},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["id"], self.user.pk)

    def test_login_with_wrong_password_returns_invalid_credentials(self):
        """Wrong passwords should be rejected."""
        response = self.client.post(
            self.login_url,
            {"account": self.user.username, "password": "wrong"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "invalid_credentials")
        self.assertEqual(
            response.json()["message"],
            "Invalid username, email, or password.",
        )

    def test_login_for_inactive_user_returns_invalid_credentials(self):
        """Inactive accounts should receive the generic auth failure."""
        inactive = self.User.objects.create_user(
            username="inactive_api_user",
            email="inactive_api_user@example.com",
            password=self.password,
            is_active=False,
        )

        response = self.client.post(
            self.login_url,
            {"account": inactive.username, "password": self.password},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "invalid_credentials")
        self.assertEqual(
            response.json()["message"],
            "Invalid username, email, or password.",
        )

    def test_login_for_merged_account_returns_invalid_credentials(self):
        """Merged source accounts should not leak merge state."""
        target = self.User.objects.create_user(
            username="merged_target_api",
            email="merged_target_api@example.com",
            password=self.password,
        )
        source = self.User.objects.create_user(
            username="merged_source_api",
            email="merged_source_api@example.com",
            password=self.password,
            is_active=False,
        )
        source.merged_into = target
        source.save(update_fields=["merged_into", "is_active"])

        response = self.client.post(
            self.login_url,
            {"account": source.username, "password": self.password},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "invalid_credentials")
        self.assertEqual(
            response.json()["message"],
            "Invalid username, email, or password.",
        )

    def test_login_with_email_for_merged_account_returns_invalid_credentials(self):
        """Merged source email login should not leak merge state."""
        target = self.User.objects.create_user(
            username="merged_target_api_email",
            email="merged_target_api_email@example.com",
            password=self.password,
        )
        source = self.User.objects.create_user(
            username="merged_source_api_email",
            email="merged_source_api_email@example.com",
            password=self.password,
            is_active=False,
        )
        source.merged_into = target
        source.save(update_fields=["merged_into", "is_active"])

        response = self.client.post(
            self.login_url,
            {"account": source.email, "password": self.password},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "invalid_credentials")
        self.assertEqual(
            response.json()["message"],
            "Invalid username, email, or password.",
        )

    def test_login_request_validation_error_uses_api_shape(self):
        """Invalid request payloads should return the shared validation shape."""
        response = self.client.post(
            self.login_url,
            {"account": self.user.username},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "validation_error")
        self.assertEqual(response.json()["message"], "Request validation failed.")
        self.assertTrue(response.json()["detail"])

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

    def test_register_returns_token_pair(self):
        """Registering through the API should issue JWT tokens."""
        response = self.client.post(
            "/api/v1/auth/register",
            {
                "username": "new_api_user",
                "email": "new_api_user@example.com",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["user"]["username"], "new_api_user")
        self.assertTrue(payload["access_token"])
        self.assertTrue(payload["refresh_token"])

    def test_refresh_rotates_refresh_token(self):
        """Refreshing should return a new token pair."""
        login_response = self.client.post(
            self.login_url,
            {"account": self.user.username, "password": self.password},
            content_type="application/json",
        )
        refresh_token = login_response.json()["refresh_token"]

        response = self.client.post(
            "/api/v1/auth/refresh",
            {"refresh_token": refresh_token},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotEqual(payload["refresh_token"], refresh_token)
        self.assertEqual(payload["user"]["id"], self.user.id)

    def test_refresh_rejects_token_after_successful_rotation(self):
        """A refresh token should become unusable after a successful rotation."""
        login_response = self.client.post(
            self.login_url,
            {"account": self.user.username, "password": self.password},
            content_type="application/json",
        )
        refresh_token = login_response.json()["refresh_token"]

        first_response = self.client.post(
            "/api/v1/auth/refresh",
            {"refresh_token": refresh_token},
            content_type="application/json",
        )
        second_response = self.client.post(
            "/api/v1/auth/refresh",
            {"refresh_token": refresh_token},
            content_type="application/json",
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 401)
        self.assertEqual(second_response.json()["code"], "invalid_token")

    def test_logout_revokes_refresh_token(self):
        """Logging out should revoke the provided refresh token."""
        login_response = self.client.post(
            self.login_url,
            {"account": self.user.username, "password": self.password},
            content_type="application/json",
        )
        refresh_token = login_response.json()["refresh_token"]

        response = self.client.post(
            "/api/v1/auth/logout",
            {"refresh_token": refresh_token},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"revoked": True})

        second_response = self.client.post(
            "/api/v1/auth/refresh",
            {"refresh_token": refresh_token},
            content_type="application/json",
        )
        self.assertEqual(second_response.status_code, 401)

    def test_password_change_revokes_existing_refresh_tokens(self):
        """Changing a password should invalidate previously issued refresh tokens."""
        login_response = self.client.post(
            self.login_url,
            {"account": self.user.username, "password": self.password},
            content_type="application/json",
        )
        refresh_token = login_response.json()["refresh_token"]
        access_token = login_response.json()["access_token"]

        response = self.client.post(
            "/api/v1/auth/password/change",
            {
                "old_password": self.password,
                "new_password1": "NewStrongPass123!",
                "new_password2": "NewStrongPass123!",
            },
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {access_token}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["message"],
            "Your password has been changed successfully.",
        )

        refresh_response = self.client.post(
            "/api/v1/auth/refresh",
            {"refresh_token": refresh_token},
            content_type="application/json",
        )
        self.assertEqual(refresh_response.status_code, 401)

    @patch("accounts.api_v1.send_password_reset_email")
    def test_password_reset_request_uses_generic_response_for_unknown_email(
        self, enqueue_mock
    ):
        """Unknown emails should receive the same generic reset-request response."""
        response = self.client.post(
            "/api/v1/auth/password/reset/request",
            {"email": "missing@example.com"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["message"],
            "If the email is registered, a reset link will be sent.",
        )
        enqueue_mock.enqueue.assert_not_called()

    @patch("accounts.api_v1.send_password_reset_email")
    def test_password_reset_request_uses_generic_response_for_social_only_account(
        self, enqueue_mock
    ):
        """Passwordless social accounts should not leak account state."""
        social_user = self.User.objects.create_user(
            username="social_only_user",
            email="social_only@example.com",
            password=None,
        )
        social_user.set_unusable_password()
        social_user.save(update_fields=["password"])
        UserSocialAuth.objects.create(
            user=social_user,
            provider="github",
            uid="12345",
        )

        response = self.client.post(
            "/api/v1/auth/password/reset/request",
            {"email": social_user.email},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["message"],
            "If the email is registered, a reset link will be sent.",
        )
        enqueue_mock.enqueue.assert_not_called()

    @patch("accounts.api_v1.send_password_reset_email")
    def test_password_reset_request_queues_email_for_password_account(
        self, enqueue_mock
    ):
        """Normal password accounts still queue a reset email behind the generic response."""
        response = self.client.post(
            "/api/v1/auth/password/reset/request",
            {"email": self.user.email},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["message"],
            "If the email is registered, a reset link will be sent.",
        )
        enqueue_mock.enqueue.assert_called_once_with(self.user.id, "testserver", False)

    @patch("accounts.api_v1.send_password_reset_email")
    def test_password_reset_request_handles_duplicate_email_without_500(
        self, enqueue_mock
    ):
        """Duplicate emails should pick a usable-password account without crashing."""
        duplicate_email = "duplicate-reset@example.com"
        social_user = Mock(pk=101, id=101)
        password_user = Mock(pk=102, id=102)
        with patch(
            "accounts.api_v1.select_password_reset_user",
            return_value=(password_user, [social_user, password_user]),
        ):
            response = self.client.post(
                "/api/v1/auth/password/reset/request",
                {"email": duplicate_email},
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["message"],
            "If the email is registered, a reset link will be sent.",
        )
        enqueue_mock.enqueue.assert_called_once_with(
            password_user.id,
            "testserver",
            False,
        )

    def test_password_reset_confirm_revokes_existing_refresh_tokens(self):
        """Completing a password reset should invalidate previously issued refresh tokens."""
        login_response = self.client.post(
            self.login_url,
            {"account": self.user.username, "password": self.password},
            content_type="application/json",
        )
        refresh_token = login_response.json()["refresh_token"]
        uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)

        response = self.client.post(
            "/api/v1/auth/password/reset/confirm",
            {
                "uidb64": uidb64,
                "token": token,
                "new_password1": "ResetStrongPass123!",
                "new_password2": "ResetStrongPass123!",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["message"],
            "Your password has been reset successfully.",
        )

        refresh_response = self.client.post(
            "/api/v1/auth/refresh",
            {"refresh_token": refresh_token},
            content_type="application/json",
        )
        self.assertEqual(refresh_response.status_code, 401)

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
            password=self.password,
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
