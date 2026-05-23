"""Tests for duplicate-email planning helpers."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from accounts.services.email_deduplication import build_duplicate_email_plans


def _user(**overrides):
    """Create a lightweight user-like object for planning tests."""
    values = {
        "pk": 1,
        "username": "user",
        "email": "user@example.com",
        "is_active": True,
        "merged_into_id": None,
        "is_staff": False,
        "is_superuser": False,
        "has_password": True,
    }
    values.update(overrides)
    user = SimpleNamespace(
        pk=values["pk"],
        username=values["username"],
        email=values["email"],
        is_active=values["is_active"],
        merged_into_id=values["merged_into_id"],
        is_staff=values["is_staff"],
        is_superuser=values["is_superuser"],
    )
    user.has_usable_password = lambda: values["has_password"]
    return user


class EmailDedupePlanTests(SimpleTestCase):
    """Cover duplicate-email planning behavior without depending on DB state."""

    @patch("accounts.services.email_deduplication._user_model")
    def test_build_duplicate_email_plans_prefers_active_unmerged_password_user(
        self,
        user_model_mock,
    ):
        """Plan builder should pick the best primary account deterministically."""
        manager = Mock()
        manager.exclude.return_value.select_related.return_value.order_by.return_value = [
            _user(
                pk=3,
                username="inactive",
                email="duplicate@example.com",
                is_active=False,
                has_password=True,
            ),
            _user(
                pk=2,
                username="social",
                email="Duplicate@example.com",
                is_active=True,
                has_password=False,
            ),
            _user(
                pk=1,
                username="primary",
                email="duplicate@example.com",
                is_active=True,
                has_password=True,
            ),
        ]
        user_model_mock.return_value = SimpleNamespace(objects=manager)

        plans = build_duplicate_email_plans()

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].primary.username, "primary")
        self.assertIsNone(plans[0].blocking_reason)

    @patch("accounts.services.email_deduplication._user_model")
    def test_build_duplicate_email_plans_blocks_admin_groups(self, user_model_mock):
        """Admin duplicate-email groups should be marked as blocked."""
        manager = Mock()
        manager.exclude.return_value.select_related.return_value.order_by.return_value = [
            _user(pk=1, username="admin", email="staff@example.com", is_staff=True),
            _user(pk=2, username="member", email="staff@example.com"),
        ]
        user_model_mock.return_value = SimpleNamespace(objects=manager)

        plans = build_duplicate_email_plans()

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].blocking_reason, "group contains an admin account")

    @patch("accounts.services.email_deduplication._user_model")
    def test_build_duplicate_email_plans_skips_blank_normalized_email(
        self, user_model_mock
    ):
        """Planning should ignore users whose normalized email is blank."""
        manager = Mock()
        manager.exclude.return_value.select_related.return_value.order_by.return_value = [
            _user(pk=1, username="blank", email="   "),
            _user(pk=2, username="single", email="single@example.com"),
        ]
        user_model_mock.return_value = SimpleNamespace(objects=manager)

        self.assertEqual(build_duplicate_email_plans(), [])
