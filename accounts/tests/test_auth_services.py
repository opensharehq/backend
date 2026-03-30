"""Focused tests for account authentication service helpers."""

from datetime import timedelta

import jwt
from django.conf import settings
from django.test import SimpleTestCase
from django.utils import timezone

from accounts.services.authentication import PasswordLoginError
from accounts.services.jwt_tokens import decode_access_token, get_user_from_access_token


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
