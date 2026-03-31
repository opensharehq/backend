"""Tests for API v1 JWT authentication flows."""

from datetime import timedelta
from unittest.mock import patch

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.test import TestCase
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from social_django.models import UserSocialAuth

from accounts.services.jwt_tokens import create_access_token


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

    def test_login_for_inactive_user_returns_disabled_error(self):
        """Inactive accounts should receive a dedicated error."""
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

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "account_disabled")
        self.assertEqual(response.json()["message"], "This account is disabled.")

    def test_login_for_merged_account_returns_merge_hint(self):
        """Merged source accounts should return the target account hint."""
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

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "account_merged")
        self.assertIn("destination account", response.json()["message"])

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
