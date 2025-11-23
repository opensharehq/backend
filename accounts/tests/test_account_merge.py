"""Tests for account merge flow."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from social_django.models import UserSocialAuth

from accounts.forms import AccountMergeRequestForm
from accounts.models import (
    AccountMergeLog,
    AccountMergeRequest,
    Organization,
    OrganizationMembership,
    ShippingAddress,
    UserProfile,
)
from accounts.services import perform_merge
from common.test_utils import CacheClearTestCase
from messages.models import Message
from points.models import PointSource
from shop.models import Redemption, ShopItem


class AccountMergeFormTests(CacheClearTestCase):
    """Validate form rules around pending limits and matching."""

    def setUp(self):
        """Prepare users for form validation tests."""
        super().setUp()
        self.User = get_user_model()
        self.source = self.User.objects.create_user(
            username="source",
            email="source@example.com",
            password="pwd123456",
        )
        self.target = self.User.objects.create_user(
            username="target",
            email="target@example.com",
            password="pwd123456",
        )

    def test_form_blocks_duplicate_pending(self):
        """A source cannot create multiple pending requests."""
        AccountMergeRequest.objects.create(
            id=uuid4(),
            source_user=self.source,
            target_user=self.target,
            target_username_input=self.target.username,
            status=AccountMergeRequest.Status.PENDING,
            approve_token="token-a",
            expires_at=timezone.now() + timedelta(days=7),
            asset_snapshot={},
        )

        form = AccountMergeRequestForm(
            user=self.source,
            data={"target_username": self.target.username},
        )
        assert not form.is_valid()
        assert "已有待处理" in form.errors["__all__"][0]

    def test_form_blocks_target_pending_quota(self):
        """Target cannot receive >3 pending requests."""
        for _ in range(3):
            AccountMergeRequest.objects.create(
                id=uuid4(),
                source_user=self.User.objects.create_user(
                    username=f"s{_}", email=f"s{_}@ex.com", password="pwd123456"
                ),
                target_user=self.target,
                target_username_input=self.target.username,
                status=AccountMergeRequest.Status.PENDING,
                approve_token=f"token-{_}",
                expires_at=timezone.now() + timedelta(days=7),
                asset_snapshot={},
            )

        form = AccountMergeRequestForm(
            user=self.source, data={"target_username": self.target.username}
        )
        assert not form.is_valid()
        assert "待处理申请过多" in form.errors["__all__"][0]

    def test_form_allows_new_after_pending_expired(self):
        """Expired pending requests should not block new submission."""
        AccountMergeRequest.objects.create(
            id=uuid4(),
            source_user=self.source,
            target_user=self.target,
            target_username_input=self.target.username,
            status=AccountMergeRequest.Status.PENDING,
            approve_token="token-expired",
            expires_at=timezone.now() - timedelta(days=1),
            asset_snapshot={},
        )

        form = AccountMergeRequestForm(
            user=self.source, data={"target_username": self.target.username}
        )
        assert form.is_valid()

    def test_target_quota_ignores_expired(self):
        """Expired requests should not count toward target pending limit."""
        for _ in range(3):
            AccountMergeRequest.objects.create(
                id=uuid4(),
                source_user=self.User.objects.create_user(
                    username=f"sx{_}", email=f"sx{_}@ex.com", password="pwd123456"
                ),
                target_user=self.target,
                target_username_input=self.target.username,
                status=AccountMergeRequest.Status.PENDING,
                approve_token=f"token-exp-{_}",
                expires_at=timezone.now() - timedelta(days=1),
                asset_snapshot={},
            )

        form = AccountMergeRequestForm(
            user=self.source, data={"target_username": self.target.username}
        )
        assert form.is_valid()

    def test_form_reports_target_not_found(self):
        """Shows explicit message when target account is missing."""
        form = AccountMergeRequestForm(
            user=self.source, data={"target_username": "ghost"}
        )
        assert not form.is_valid()
        assert "未找到匹配的目标账号" in form.errors["__all__"][0]

    def test_form_blocks_admin_target(self):
        """Merging into admin account is rejected with specific text."""
        admin_user = self.User.objects.create_superuser(
            username="admin", email="admin@example.com", password="pwd123456"
        )
        form = AccountMergeRequestForm(
            user=self.source,
            data={
                "target_username": admin_user.username,
                "target_email": admin_user.email,
            },
        )
        assert not form.is_valid()
        assert "目标账号为管理员" in form.errors["__all__"][0]

    def test_form_requires_username_email_match(self):
        """Username exists but mismatched email should report not found."""
        form = AccountMergeRequestForm(
            user=self.source,
            data={
                "target_username": self.target.username,
                "target_email": "wrong@example.com",
            },
        )
        assert not form.is_valid()
        assert "未找到匹配的目标账号" in form.errors["__all__"][0]

    def test_form_blocks_self_merge(self):
        """User cannot merge into self."""
        form = AccountMergeRequestForm(
            user=self.source, data={"target_username": self.source.username}
        )
        assert not form.is_valid()
        assert "不能合并到自己的账号" in form.errors["__all__"][0]


class AccountMergeViewTests(CacheClearTestCase):
    """End-to-end view tests for creating and processing requests."""

    def setUp(self):
        """Create two users for merge flows and log client."""
        super().setUp()
        self.User = get_user_model()
        self.source = self.User.objects.create_user(
            username="source",
            email="source@example.com",
            password="pwd123456",
        )
        self.target = self.User.objects.create_user(
            username="target",
            email="target@example.com",
            password="pwd123456",
        )
        self.client = Client()

    @patch("accounts.views.inbox_services.send_message")
    def test_create_request_via_view(self, mock_send):
        """Posting to merge endpoint creates request and inbox message."""
        mock_send.return_value = Message.objects.create(
            title="账号合并请求", content="body"
        )
        self.client.force_login(self.source)
        response = self.client.post(
            reverse("accounts:merge_request"),
            {
                "target_username": self.target.username,
                "target_email": self.target.email,
            },
        )
        self.assertRedirects(response, reverse("accounts:merge_request"))

        merge_request = AccountMergeRequest.objects.get(source_user=self.source)
        assert merge_request.status == AccountMergeRequest.Status.PENDING
        assert merge_request.message is not None
        assert merge_request.asset_snapshot.get("total_points") == 0
        mock_send.assert_called_once()

    def test_accept_request_moves_assets(self):
        """Target accepting merges points, orgs, addresses, and deactivates source."""
        # source assets
        PointSource.objects.create(
            user=self.source, initial_points=100, remaining_points=100
        )
        UserSocialAuth.objects.create(
            user=self.source, provider="github", uid="uid-source"
        )
        source_profile = UserProfile.objects.create(
            user=self.source,
            company="Acme",
            location="Earth",
        )

        # shipping addresses (duplicate)
        ShippingAddress.objects.create(
            user=self.source,
            receiver_name="Alice",
            phone="123",
            province="P",
            city="C",
            district="D",
            address="Street 1",
            is_default=True,
        )
        ShippingAddress.objects.create(
            user=self.target,
            receiver_name="Alice",
            phone="123",
            province="P",
            city="C",
            district="D",
            address="Street 1",
            is_default=False,
        )

        # org membership conflict
        org = Organization.objects.create(name="Org", slug="org")
        OrganizationMembership.objects.create(
            user=self.source, organization=org, role=OrganizationMembership.Role.OWNER
        )
        OrganizationMembership.objects.create(
            user=self.target, organization=org, role=OrganizationMembership.Role.MEMBER
        )

        # redemption record
        item = ShopItem.objects.create(name="Gift", description="d", cost=1)
        Redemption.objects.create(
            user_profile=self.source, item=item, points_cost_at_redemption=1
        )

        # existing social auth on target (different uid)
        UserSocialAuth.objects.create(
            user=self.target, provider="github", uid="uid-target"
        )

        merge_request = AccountMergeRequest.objects.create(
            id=uuid4(),
            source_user=self.source,
            target_user=self.target,
            target_username_input=self.target.username,
            status=AccountMergeRequest.Status.PENDING,
            approve_token="token-b",
            expires_at=timezone.now() + timedelta(days=7),
            asset_snapshot={"total_points": 100},
        )

        perform_merge(merge_request)
        merge_request.refresh_from_db()

        self.source.refresh_from_db()
        self.target.refresh_from_db()

        assert merge_request.status == AccountMergeRequest.Status.ACCEPTED
        assert not self.source.is_active
        assert self.source.merged_into == self.target
        assert PointSource.objects.filter(user=self.target).count() == 1
        assert PointSource.objects.filter(user=self.source).count() == 0

        # shipping address dedup keeps single entry
        assert ShippingAddress.objects.filter(user=self.target).count() == 1

        # org membership upgraded to owner
        target_membership = OrganizationMembership.objects.get(
            user=self.target, organization=org
        )
        assert target_membership.role == OrganizationMembership.Role.OWNER
        assert not OrganizationMembership.objects.filter(
            user=self.source, organization=org
        ).exists()

        # social auth conflict skipped
        assert (
            UserSocialAuth.objects.filter(
                user=self.target, provider="github", uid="uid-source"
            ).count()
            == 1
        )

        # redemption moved
        assert Redemption.objects.filter(user_profile=self.target).count() == 1

        # profile fields filled when blank
        target_profile = UserProfile.objects.get(user=self.target)
        assert target_profile.company == source_profile.company

        # logs produced
        assert AccountMergeLog.objects.filter(request=merge_request).exists()

    def test_merge_review_requires_target(self):
        """Non-target user gets 403 when viewing merge request."""
        merge_request = AccountMergeRequest.objects.create(
            id=uuid4(),
            source_user=self.source,
            target_user=self.target,
            target_username_input=self.target.username,
            status=AccountMergeRequest.Status.PENDING,
            approve_token="token-c",
            expires_at=timezone.now() + timedelta(days=7),
            asset_snapshot={},
        )

        self.client.force_login(self.source)
        response = self.client.get(
            reverse("accounts:merge_review", args=[merge_request.approve_token])
        )
        assert response.status_code == 403

    def test_expired_request_marks_expired_on_review(self):
        """Viewing an expired request marks it expired and processed."""
        merge_request = AccountMergeRequest.objects.create(
            id=uuid4(),
            source_user=self.source,
            target_user=self.target,
            target_username_input=self.target.username,
            status=AccountMergeRequest.Status.PENDING,
            approve_token="token-d",
            expires_at=timezone.now() - timedelta(days=1),
            asset_snapshot={},
        )

        self.client.force_login(self.target)
        response = self.client.get(
            reverse("accounts:merge_review", args=[merge_request.approve_token])
        )
        assert response.status_code == 200
        merge_request.refresh_from_db()
        assert merge_request.status == AccountMergeRequest.Status.EXPIRED
        assert merge_request.processed_by == self.target

    @patch("accounts.views.inbox_services.send_message")
    def test_reject_request_updates_status_and_notifies(self, mock_send):
        """Rejecting sets status and sends notification."""
        merge_request = AccountMergeRequest.objects.create(
            id=uuid4(),
            source_user=self.source,
            target_user=self.target,
            target_username_input=self.target.username,
            status=AccountMergeRequest.Status.PENDING,
            approve_token="token-e",
            expires_at=timezone.now() + timedelta(days=1),
            asset_snapshot={},
        )

        self.client.force_login(self.target)
        response = self.client.post(
            reverse("accounts:merge_reject", args=[merge_request.approve_token])
        )
        self.assertRedirects(
            response,
            reverse("accounts:merge_review", args=[merge_request.approve_token]),
        )

        merge_request.refresh_from_db()
        assert merge_request.status == AccountMergeRequest.Status.REJECTED
        assert merge_request.processed_by == self.target
        assert merge_request.processed_at is not None
        mock_send.assert_called()
