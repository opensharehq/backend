"""Additional model coverage for accounts app."""

from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import (
    WITHDRAWABLE_POINTS_CACHE_KEY_TEMPLATE,
    AccountMergeLog,
    AccountMergeRequest,
    Organization,
    OrganizationMembership,
)


class AccountModelMiscTests(TestCase):
    """Cover cache helpers and __str__ implementations."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="cache-user", email="c@example.com", password="pwd123456"
        )

    @override_settings(
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    )
    def test_withdrawable_points_uses_cache_and_clear_points_cache(self):
        """withdrawable_points should respect cache and clear_points_cache clears it."""
        cache_key = WITHDRAWABLE_POINTS_CACHE_KEY_TEMPLATE.format(user_id=self.user.pk)
        cache.set(cache_key, 99, None)

        # Cached value should be returned without hitting DB
        self.assertEqual(self.user.withdrawable_points, 99)

        # Populate the attribute cache then ensure it is removed
        self.user.__dict__["withdrawable_points"] = 42
        self.user.clear_points_cache()

        self.assertIsNone(cache.get(cache_key))
        self.assertNotIn("withdrawable_points", self.user.__dict__)

    def test_organization_membership_str(self):
        """__str__ should include username, org name and role display."""
        org = Organization.objects.create(name="Org1", slug="org1")
        membership = OrganizationMembership.objects.create(
            user=self.user, organization=org, role=OrganizationMembership.Role.ADMIN
        )
        self.assertIn("Org1", str(membership))
        self.assertIn("管理员", str(membership))

    def test_account_merge_request_str(self):
        """AccountMergeRequest __str__ uses source, target and status."""
        target = get_user_model().objects.create_user(
            username="target", email="t@example.com", password="pwd123456"
        )
        merge_request = AccountMergeRequest.objects.create(
            id=uuid4(),
            source_user=self.user,
            target_user=target,
            target_email_input=target.email,
            approve_token="token",
            expires_at=timezone.now() + timezone.timedelta(days=1),
            asset_snapshot={},
        )
        self.assertIn("cache-user", str(merge_request))
        self.assertIn("target", str(merge_request))
        self.assertIn(merge_request.status, str(merge_request))

    def test_account_merge_log_str(self):
        """AccountMergeLog __str__ returns summary counts."""
        target = get_user_model().objects.create_user(
            username="target2", email="t2@example.com", password="pwd123456"
        )
        req = AccountMergeRequest.objects.create(
            id=uuid4(),
            source_user=self.user,
            target_user=target,
            target_email_input=target.email,
            approve_token="token-log",
            expires_at=timezone.now() + timezone.timedelta(days=1),
            asset_snapshot={},
        )
        log = AccountMergeLog.objects.create(
            request=req, table_name="test", migrated_count=2, conflict_count=1
        )
        self.assertEqual(str(log), "test: +2/~1")
