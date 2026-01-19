"""Tests for account merge flow."""

from datetime import timedelta
from types import SimpleNamespace
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
from accounts.services.account_merge import (
    AccountMergeError,
    _copy_profile_fields,
    _merge_profiles,
    _migrate_organization_memberships,
    _migrate_shipping_addresses,
    _migrate_social_accounts,
    perform_merge,
)
from common.test_utils import CacheClearTestCase
from messages.models import Message
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

    def test_form_requires_username_or_email(self):
        """Submitting without username/email triggers explicit validation."""
        form = AccountMergeRequestForm(user=self.source, data={})
        assert not form.is_valid()
        assert "请输入目标账号的邮箱或用户名" in form.errors["__all__"][0]

    def test_form_can_match_using_email_only(self):
        """Providing only email uses email lookup branch."""
        form = AccountMergeRequestForm(
            user=self.source, data={"target_email": self.target.email}
        )
        assert form.is_valid()
        assert form.target_user == self.target

    def test_form_reports_multiple_matches(self):
        """Duplicate email results in MultipleObjectsReturned error message."""
        self.User.objects.create_user(
            username="target2", email=self.target.email, password="pwd123456"
        )
        form = AccountMergeRequestForm(
            user=self.source, data={"target_email": self.target.email}
        )
        assert not form.is_valid()
        assert "匹配到多个账号" in form.errors["__all__"][0]

    def test_form_blocks_admin_or_inactive_source(self):
        """Source user that is staff or inactive cannot start merge."""
        staff_user = self.User.objects.create_user(
            username="staffsrc",
            email="staffsrc@example.com",
            password="pwd123456",
            is_staff=True,
        )
        form = AccountMergeRequestForm(
            user=staff_user, data={"target_username": self.target.username}
        )
        assert not form.is_valid()
        assert "管理员账号不支持发起合并" in form.errors["__all__"][0]

        inactive = self.User.objects.create_user(
            username="inactive",
            email="inactive@example.com",
            password="pwd123456",
            is_active=False,
        )
        form = AccountMergeRequestForm(
            user=inactive, data={"target_username": self.target.username}
        )
        assert not form.is_valid()
        assert "账号已被停用" in form.errors["__all__"][0]


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
        mock_send.assert_called_once()

    def test_accept_request_moves_assets(self):
        """Target accepting merges orgs, addresses, and deactivates source."""
        # source assets
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
            asset_snapshot={},
        )

        perform_merge(merge_request)
        merge_request.refresh_from_db()

        self.source.refresh_from_db()
        self.target.refresh_from_db()

        assert merge_request.status == AccountMergeRequest.Status.ACCEPTED
        assert not self.source.is_active
        assert self.source.merged_into == self.target

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


class AccountMergeServiceEdgeTests(CacheClearTestCase):
    """Exercise edge-case branches inside account_merge service helpers."""

    def setUp(self):
        super().setUp()
        self.User = get_user_model()
        self.source = self.User.objects.create_user(
            username="svc-source", email="svc-source@example.com", password="pwd123456"
        )
        self.target = self.User.objects.create_user(
            username="svc-target", email="svc-target@example.com", password="pwd123456"
        )
        self.merge_request = AccountMergeRequest.objects.create(
            id=uuid4(),
            source_user=self.source,
            target_user=self.target,
            target_username_input=self.target.username,
            status=AccountMergeRequest.Status.ACCEPTED,
            approve_token="svc-token",
            expires_at=timezone.now() + timedelta(days=7),
            asset_snapshot={},
        )

    def test_copy_profile_fields_handles_missing_source(self):
        """_copy_profile_fields returns 0 when source_profile is None."""
        target_profile = UserProfile.objects.create(user=self.target)
        copied = _copy_profile_fields(None, target_profile)
        assert copied == 0

    def test_migrate_social_accounts_counts_conflicts(self):
        """Duplicate social accounts increment conflict count without migration."""
        source_social = SimpleNamespace(provider="github", uid="abc", user=self.source)

        class FakeQS(list):
            def select_related(self, *args, **kwargs):
                return self

        def filter_side_effect(*_, **kwargs):
            user = kwargs.get("user")
            if user == self.target:
                return FakeQS(
                    [SimpleNamespace(provider="github", uid="abc", user=self.target)]
                )
            if user == self.source:
                return FakeQS([source_social])
            return FakeQS()

        with patch("accounts.services.account_merge.UserSocialAuth") as mock_sa:
            mock_sa.objects.filter.side_effect = filter_side_effect
            mock_sa.objects.select_for_update.return_value = mock_sa.objects

            _migrate_social_accounts(self.merge_request, self.source, self.target)

        log = self.merge_request.logs.filter(table_name="social_auth").latest(
            "created_at"
        )
        assert log.migrated_count == 0
        assert log.conflict_count == 1

    def test_migrate_shipping_addresses_skips_duplicates(self):
        """Duplicate addresses should be skipped and redemptions re-pointed."""
        target_address = ShippingAddress.objects.create(
            user=self.target,
            receiver_name="收件人",
            phone="13800138000",
            province="省",
            city="市",
            district="区",
            address="街道1号",
        )
        source_address = ShippingAddress.objects.create(
            user=self.source,
            receiver_name="收件人",
            phone="13800138000",
            province="省",
            city="市",
            district="区",
            address="街道1号",
        )
        item = ShopItem.objects.create(name="Gift", description="d", cost=1)
        Redemption.objects.create(
            user_profile=self.source,
            item=item,
            points_cost_at_redemption=1,
            shipping_address=source_address,
        )

        _migrate_shipping_addresses(self.merge_request, self.source, self.target)

        assert not ShippingAddress.objects.filter(user=self.source).exists()
        redemption = Redemption.objects.get(user_profile=self.source)
        assert redemption.shipping_address == target_address
        log = self.merge_request.logs.filter(table_name="shipping_addresses").latest(
            "created_at"
        )
        assert log.skipped_count == 1

    def test_migrate_shipping_addresses_moves_unique(self):
        """Non-duplicate addresses migrate and increment migrated count."""
        unique_address = ShippingAddress.objects.create(
            user=self.source,
            receiver_name="小明",
            phone="13800138001",
            province="省",
            city="市",
            district="区",
            address="另一条街",
        )

        _migrate_shipping_addresses(self.merge_request, self.source, self.target)

        unique_address.refresh_from_db()
        assert unique_address.user == self.target
        log = self.merge_request.logs.filter(table_name="shipping_addresses").latest(
            "created_at"
        )
        assert log.migrated_count == 1
        assert log.skipped_count == 0

    def test_migrate_organization_memberships_prefers_higher_role(self):
        """Incoming higher role should replace target membership role."""
        org = Organization.objects.create(name="Org", slug="org")
        target_membership = OrganizationMembership.objects.create(
            user=self.target, organization=org, role=OrganizationMembership.Role.MEMBER
        )
        source_membership = OrganizationMembership.objects.create(
            user=self.source, organization=org, role=OrganizationMembership.Role.OWNER
        )

        _migrate_organization_memberships(self.merge_request, self.source, self.target)

        target_membership.refresh_from_db()
        assert target_membership.role == OrganizationMembership.Role.OWNER
        assert not OrganizationMembership.objects.filter(
            pk=source_membership.pk
        ).exists()
        log = self.merge_request.logs.filter(
            table_name="organization_memberships"
        ).latest("created_at")
        assert log.conflict_count == 1

    def test_migrate_organization_memberships_moves_when_unique(self):
        """Unique memberships should be migrated to target."""
        org = Organization.objects.create(name="Org2", slug="org2")
        membership = OrganizationMembership.objects.create(
            user=self.source, organization=org, role=OrganizationMembership.Role.MEMBER
        )

        _migrate_organization_memberships(self.merge_request, self.source, self.target)

        membership.refresh_from_db()
        assert membership.user == self.target
        log = self.merge_request.logs.filter(
            table_name="organization_memberships"
        ).latest("created_at")
        assert log.migrated_count == 1
        assert log.conflict_count == 0

    def test_merge_profiles_handles_missing_source_profile(self):
        """If source lacks profile, migration still logs zero copied fields."""
        _merge_profiles(self.merge_request, self.source, self.target)
        log = self.merge_request.logs.filter(table_name="profile").latest("created_at")
        assert log.migrated_count == 0

    def _build_request(self, **overrides):
        """Helper to create requests with custom status/expiry."""
        return AccountMergeRequest.objects.create(
            id=uuid4(),
            source_user=overrides.get("source_user", self.source),
            target_user=overrides.get("target_user", self.target),
            target_username_input=overrides.get(
                "target_username_input", self.target.username
            ),
            status=overrides.get("status", AccountMergeRequest.Status.PENDING),
            approve_token=overrides.get("approve_token", f"token-{uuid4()}"),
            expires_at=overrides.get("expires_at", timezone.now() + timedelta(days=1)),
            asset_snapshot={},
        )

    def test_perform_merge_returns_immediately_when_accepted(self):
        """Accepted requests are returned without reprocessing."""
        merge_request = self._build_request(status=AccountMergeRequest.Status.ACCEPTED)
        result = perform_merge(merge_request)
        assert result.status == AccountMergeRequest.Status.ACCEPTED

    def test_perform_merge_expires_pending_requests(self):
        """Expired pending requests are marked expired with processor set."""
        new_source = self.User.objects.create_user(
            username="pending-source",
            email="pending-source@example.com",
            password="pwd123456",
        )
        merge_request = self._build_request(
            status=AccountMergeRequest.Status.PENDING,
            expires_at=timezone.now() - timedelta(seconds=1),
            approve_token="expired-token",
            source_user=new_source,
        )
        result = perform_merge(merge_request)
        assert result.status == AccountMergeRequest.Status.EXPIRED
        assert result.processed_by == self.target

    def test_perform_merge_rejects_non_pending_status(self):
        """Non-pending non-accepted status raises AccountMergeError."""
        merge_request = self._build_request(status=AccountMergeRequest.Status.REJECTED)
        with self.assertRaises(AccountMergeError):
            perform_merge(merge_request)

    def test_perform_merge_requires_active_users(self):
        """Inactive source or target should abort the merge."""
        inactive_source = self.User.objects.create_user(
            username="inactive-source",
            email="inactive-source@example.com",
            password="pwd123456",
        )
        merge_request = self._build_request(
            approve_token="inactive-source", source_user=inactive_source
        )
        inactive_source.is_active = False
        inactive_source.save(update_fields=["is_active"])
        with self.assertRaisesMessage(AccountMergeError, "源账号已停用"):
            perform_merge(merge_request)

        active_source = self.User.objects.create_user(
            username="active-source",
            email="active-source@example.com",
            password="pwd123456",
        )
        merge_request = self._build_request(
            approve_token="inactive-target", source_user=active_source
        )
        self.target.is_active = False
        self.target.save(update_fields=["is_active"])
        with self.assertRaisesMessage(AccountMergeError, "目标账号已停用"):
            perform_merge(merge_request)

    def test_perform_merge_blocks_admin_target(self):
        """Target admins cannot receive merges."""
        new_source = self.User.objects.create_user(
            username="new-source", email="new-source@example.com", password="pwd123456"
        )
        merge_request = self._build_request(
            approve_token="admin-target",
            source_user=new_source,
        )
        self.target.is_staff = True
        self.target.save(update_fields=["is_staff"])
        with self.assertRaisesMessage(AccountMergeError, "不允许合并到管理员账号"):
            perform_merge(merge_request)
