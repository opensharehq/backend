"""Additional model coverage for accounts app."""

from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import (
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
