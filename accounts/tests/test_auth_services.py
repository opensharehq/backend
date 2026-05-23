"""Focused tests for account authentication service helpers."""

from datetime import timedelta
from unittest.mock import Mock, patch

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from accounts.email_addresses import (
    get_email_login_candidates,
    matching_email_users,
    select_password_reset_user,
)
from accounts.services.authentication import (
    AccountDisabledError,
    AccountMergedError,
    PasswordLoginError,
    authenticate_by_login_id,
)
from accounts.services.jwt_tokens import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    get_user_from_access_token,
    get_user_from_refresh_token,
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
        self.assertEqual(str(AccountDisabledError()), "账号已被停用，请联系管理员")
        self.assertIn("target", str(AccountMergedError("target")))

    @patch("accounts.services.authentication.get_email_login_candidates")
    @patch("accounts.services.authentication.authenticate")
    def test_authenticate_by_login_id_tries_all_matching_email_candidates(
        self,
        authenticate_mock,
        get_candidates_mock,
    ):
        """Email login should iterate through candidates until one authenticates."""
        first_candidate = Mock(username="first")
        second_candidate = Mock(username="second")
        matched_user = Mock(is_active=True, merged_into_id=None)
        get_candidates_mock.return_value = [first_candidate, second_candidate]
        authenticate_mock.side_effect = [None, None, matched_user]

        user = authenticate_by_login_id("shared@example.com", "Secret123!")

        self.assertIs(user, matched_user)
        self.assertEqual(
            authenticate_mock.call_args_list[1].kwargs["username"], "first"
        )
        self.assertEqual(
            authenticate_mock.call_args_list[2].kwargs["username"], "second"
        )

    @patch("accounts.email_addresses.matching_email_users")
    def test_select_password_reset_user_prefers_active_unmerged_password_account(
        self,
        matching_users_mock,
    ):
        """Password reset should choose the best usable account among matches."""
        merged_user = Mock(pk=30, merged_into_id=100, is_active=False)
        merged_user.has_usable_password.return_value = True
        active_password_user = Mock(pk=20, merged_into_id=None, is_active=True)
        active_password_user.has_usable_password.return_value = True
        active_social_user = Mock(pk=10, merged_into_id=None, is_active=True)
        active_social_user.has_usable_password.return_value = False
        matching_users_mock.return_value = [
            merged_user,
            active_social_user,
            active_password_user,
        ]

        user, candidates = select_password_reset_user("shared@example.com")

        self.assertIs(user, active_password_user)
        self.assertEqual(
            get_email_login_candidates("shared@example.com"),
            [active_password_user, active_social_user, merged_user],
        )
        self.assertEqual(candidates[0], active_password_user)

    def test_matching_email_users_blank_input_returns_empty_queryset(self):
        """Blank email lookups should return an empty queryset."""
        self.assertFalse(matching_email_users("").exists())


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

    def test_get_user_from_access_token_rejects_merged_user(self):
        """Access tokens for merged users should not authenticate."""
        target = self.User.objects.create_user(
            username="access-target",
            email="access-target@example.com",
            password="RefreshPass123!",
        )
        self.user.merged_into = target
        self.user.save(update_fields=["merged_into"])

        self.assertIsNone(get_user_from_access_token(create_access_token(self.user)))

    def test_refresh_token_user_resolution_rejects_invalid_subject(self):
        """Refresh user resolution should reject non-integer subjects."""
        refresh_token = create_refresh_token(self.user)
        payload = jwt.decode(
            refresh_token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        payload["sub"] = "not-an-integer"
        invalid_subject = jwt.encode(
            payload,
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )

        self.assertIsNone(get_user_from_refresh_token(invalid_subject))

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
