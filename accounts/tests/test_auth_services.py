"""Focused tests for account authentication service helpers."""

from datetime import timedelta
from unittest.mock import patch

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from accounts.services.authentication import PasswordLoginError
from accounts.services.jwt_tokens import (
    create_refresh_token,
    decode_access_token,
    get_user_from_access_token,
    rotate_refresh_token,
)


class PasswordLoginErrorTests(SimpleTestCase):
    """Cover common behavior for password login errors."""

    def test_str_returns_message(self):
        """Stringifying the error should return its human-readable message."""
        error = PasswordLoginError(
            code="invalid_credentials",
            status_code=401,
            message="用户名或密码错误，请重试",
        )

        self.assertEqual(str(error), error.message)


class JwtTokenServiceTests(SimpleTestCase):
    """Cover JWT helper edge cases not exercised by API tests."""

    def _encode_token(self, **payload_overrides) -> str:
        """Create a signed JWT payload for service-level tests."""
        payload = {
            "sub": "123",
            "type": "access",
            "iat": timezone.now(),
            "exp": timezone.now() + timedelta(minutes=5),
        }
        payload.update(payload_overrides)
        return jwt.encode(
            payload,
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )

    def test_decode_access_token_rejects_non_access_type(self):
        """Only access tokens should be accepted by the decoder."""
        token = self._encode_token(type="refresh")

        self.assertIsNone(decode_access_token(token))

    def test_get_user_from_access_token_rejects_non_integer_subject(self):
        """JWT subjects must be parseable user IDs."""
        token = self._encode_token(sub="not-an-integer")

        self.assertIsNone(get_user_from_access_token(token))


class RefreshTokenServiceTests(TestCase):
    """Cover refresh rotation edge cases at the service layer."""

    def setUp(self):
        """Create a reusable database-backed user fixture."""
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username="refresh-service-user",
            email="refresh-service-user@example.com",
            password="RefreshPass123!",
        )

    @patch("accounts.services.jwt_tokens.issue_token_pair")
    @patch("accounts.services.jwt_tokens._revoke_refresh_record_if_active")
    def test_rotate_refresh_token_returns_none_when_conditional_revoke_fails(
        self,
        revoke_mock,
        issue_token_pair_mock,
    ):
        """Rotation should not issue new tokens when the conditional revoke loses."""
        revoke_mock.return_value = False
        refresh_token = create_refresh_token(self.user)

        result = rotate_refresh_token(refresh_token)

        self.assertIsNone(result)
        issue_token_pair_mock.assert_not_called()
