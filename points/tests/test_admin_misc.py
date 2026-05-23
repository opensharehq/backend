"""Additional coverage for points admin behavior."""

from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib import admin
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.models import Organization
from points import services
from points.admin import (
    ContributionCacheAdmin,
    PendingPointGrantAdmin,
    PointAllocationAdmin,
    PointSourceAdmin,
    PointSourceInline,
    PointTransactionAdmin,
    PointTransactionInline,
    PointWalletAdmin,
    WithdrawalInline,
    WithdrawalRequestAdmin,
    grant_points_to_orgs_view,
    grant_points_to_users_view,
)
from points.models import (
    AllocationStatus,
    ContributionCache,
    PendingPointGrant,
    PointAllocation,
    PointSource,
    PointTransaction,
    PointType,
    PointWallet,
    Tag,
    TransactionType,
    WithdrawalRequest,
    WithdrawalStatus,
)

User = get_user_model()


class PointsAdminBehaviorTests(TestCase):
    """Cover behavior-heavy helpers in points admin."""

    def setUp(self):
        """Create a reusable points fixture set."""
        self.site = AdminSite()
        self.factory = RequestFactory()
        self.admin_user = User.objects.create_superuser(
            username="points-admin",
            email="points-admin@example.com",
            password="password123",
        )
        self.user = User.objects.create_user(
            username="points-owner",
            email="points-owner@example.com",
            password="password123",
        )
        self.content_type = ContentType.objects.get_for_model(self.user)
        self.wallet = PointWallet.objects.create(
            content_type=self.content_type,
            object_id=self.user.id,
        )
        self.tag = Tag.objects.create(name="积分标签", slug="points-tag")
        self.source_cash = PointSource.objects.create(
            wallet=self.wallet,
            point_type=PointType.CASH,
            original_amount=120,
            remaining_amount=120,
            reason="现金发放",
            created_by=self.admin_user,
        )
        self.source_gift = PointSource.objects.create(
            wallet=self.wallet,
            point_type=PointType.GIFT,
            tag=self.tag,
            original_amount=80,
            remaining_amount=80,
            reason="礼物发放",
            created_by=self.admin_user,
        )
        self.earn_transaction = PointTransaction.objects.create(
            wallet=self.wallet,
            transaction_type=TransactionType.EARN,
            point_type=PointType.CASH,
            amount=120,
            balance_after=120,
            description="收入",
            source=self.source_cash,
            created_by=self.admin_user,
        )
        self.spend_transaction = PointTransaction.objects.create(
            wallet=self.wallet,
            transaction_type=TransactionType.SPEND,
            point_type=PointType.CASH,
            amount=-20,
            balance_after=100,
            description="支出",
            source=self.source_cash,
            created_by=self.admin_user,
        )
        self.withdrawal = WithdrawalRequest.objects.create(
            wallet=self.wallet,
            amount=50,
            status=WithdrawalStatus.PENDING,
            real_name="张三",
            phone="13800138000",
            id_card="11010519491231002X",
            bank_name="中国银行",
            bank_account="6222000000000000000",
        )
        self.allocation = PointAllocation.objects.create(
            initiator_type=self.content_type,
            initiator_id=self.user.id,
            source_pool=self.source_cash,
            total_amount=100,
            project_scope={"tags": ["repo:github:test"]},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 1, 31),
            status=AllocationStatus.COMPLETED,
        )
        self.pending_grant = PendingPointGrant.objects.create(
            platform="github",
            actor_id="12345",
            actor_login="pending-user",
            email="pending@example.com",
            amount=60,
            point_type=PointType.GIFT,
            reason="待领取",
            tag=self.tag,
            granter_type=self.content_type,
            granter_id=self.user.id,
            allocation=self.allocation,
        )
        self.contribution_cache = ContributionCache.objects.create(
            project_identifier="repo:github:test",
            github_id="12345",
            github_login="cached-user",
            email="cached@example.com",
            start_month=date(2024, 1, 1),
            end_month=date(2024, 1, 31),
            contribution_score=Decimal("10.50"),
            raw_data={"details": []},
        )
        self.wallet_admin = PointWalletAdmin(PointWallet, self.site)
        self.source_admin = PointSourceAdmin(PointSource, self.site)
        self.transaction_admin = PointTransactionAdmin(PointTransaction, self.site)
        self.withdrawal_admin = WithdrawalRequestAdmin(WithdrawalRequest, self.site)
        self.allocation_admin = PointAllocationAdmin(PointAllocation, self.site)
        self.pending_admin = PendingPointGrantAdmin(PendingPointGrant, self.site)
        self.cache_admin = ContributionCacheAdmin(ContributionCache, self.site)

    def _request(self):
        """Build an authenticated admin request."""
        request = self.factory.post("/admin/points/")
        request.user = self.admin_user
        return request

    def _request_with_messages(self, path, user, method="get", data=None):
        """Build a request object with message storage for direct view calls."""
        request_factory_method = getattr(self.factory, method.lower())
        request = request_factory_method(path, data or {})
        request.user = user
        request.session = self.client.session
        request._messages = FallbackStorage(request)
        return request

    def test_wallet_admin_and_inlines_are_read_only(self):
        """Wallet admin helpers should expose balances and disable manual adds."""
        self.assertEqual(self.wallet_admin.owner_display(self.wallet), str(self.user))
        self.assertEqual(self.wallet_admin.owner_display(Mock(owner=None)), "-")
        self.assertEqual(self.wallet_admin.cash_balance(self.wallet), 120)
        self.assertEqual(self.wallet_admin.gift_balance(self.wallet), 80)
        self.assertEqual(self.wallet_admin.total_balance(self.wallet), 200)
        self.assertFalse(self.wallet_admin.has_add_permission(self._request()))
        self.assertFalse(
            PointSourceInline(PointWallet, self.site).has_add_permission(
                self._request(),
                self.wallet,
            )
        )
        self.assertFalse(
            PointTransactionInline(PointWallet, self.site).has_add_permission(
                self._request(),
                self.wallet,
            )
        )
        self.assertFalse(
            WithdrawalInline(PointWallet, self.site).has_add_permission(
                self._request(),
                self.wallet,
            )
        )

    def test_source_and_transaction_admin_helpers_cover_display_and_permissions(self):
        """Source/transaction admins should expose owners, colors, and immutability."""
        self.assertEqual(
            self.source_admin.wallet_owner(self.source_cash), str(self.user)
        )
        self.assertEqual(
            self.source_admin.wallet_owner(Mock(wallet=Mock(owner=None))),
            "-",
        )
        self.assertFalse(self.source_admin.has_add_permission(self._request()))
        self.assertFalse(
            self.source_admin.has_change_permission(self._request(), self.source_cash)
        )

        self.assertEqual(
            self.transaction_admin.wallet_owner(self.earn_transaction),
            str(self.user),
        )
        self.assertEqual(
            self.transaction_admin.wallet_owner(Mock(wallet=Mock(owner=None))),
            "-",
        )
        self.assertIn(
            "green",
            str(self.transaction_admin.transaction_type_display(self.earn_transaction)),
        )
        self.assertIn(
            "+120",
            str(self.transaction_admin.amount_display(self.earn_transaction)),
        )
        self.assertIn(
            "red",
            str(self.transaction_admin.amount_display(self.spend_transaction)),
        )
        self.assertFalse(self.transaction_admin.has_add_permission(self._request()))
        self.assertFalse(
            self.transaction_admin.has_change_permission(
                self._request(),
                self.earn_transaction,
            )
        )
        self.assertFalse(
            self.transaction_admin.has_delete_permission(
                self._request(),
                self.earn_transaction,
            )
        )

    @patch("points.admin.services.approve_withdrawal")
    @patch("points.admin.services.reject_withdrawal")
    @patch("points.admin.services.complete_withdrawal")
    def test_withdrawal_admin_actions_delegate_and_report_success(
        self,
        mock_complete_withdrawal,
        mock_reject_withdrawal,
        mock_approve_withdrawal,
    ):
        """Batch withdrawal actions should call services and emit summary messages."""
        self.withdrawal_admin.message_user = Mock()

        self.withdrawal_admin.approve_selected(
            self._request(),
            WithdrawalRequest.objects.filter(pk=self.withdrawal.pk),
        )
        self.withdrawal.status = WithdrawalStatus.PENDING
        self.withdrawal.save(update_fields=["status"])
        self.withdrawal_admin.reject_selected(
            self._request(),
            WithdrawalRequest.objects.filter(pk=self.withdrawal.pk),
        )
        approved = WithdrawalRequest.objects.create(
            wallet=self.wallet,
            amount=20,
            status=WithdrawalStatus.APPROVED,
            real_name="李四",
            phone="13900139000",
            id_card="110105194912310011",
            bank_name="工商银行",
            bank_account="6222000000000000001",
        )
        self.withdrawal_admin.complete_selected(
            self._request(),
            WithdrawalRequest.objects.filter(pk=approved.pk),
        )

        mock_approve_withdrawal.assert_called_once_with(
            self.withdrawal.id, self.admin_user
        )
        mock_reject_withdrawal.assert_called_once_with(
            self.withdrawal.id,
            self.admin_user,
            "批量拒绝",
        )
        mock_complete_withdrawal.assert_called_once_with(approved.id, self.admin_user)
        self.assertGreaterEqual(self.withdrawal_admin.message_user.call_count, 3)
        self.assertIn(
            "orange", str(self.withdrawal_admin.status_display(self.withdrawal))
        )
        self.assertEqual(
            self.withdrawal_admin.wallet_owner(self.withdrawal), str(self.user)
        )
        self.assertEqual(
            self.withdrawal_admin.wallet_owner(Mock(wallet=Mock(owner=None))),
            "-",
        )
        self.assertFalse(self.withdrawal_admin.has_add_permission(self._request()))

    @patch(
        "points.admin.services.approve_withdrawal",
        side_effect=services.InsufficientPointsError("余额不足"),
    )
    @patch(
        "points.admin.services.reject_withdrawal",
        side_effect=services.WithdrawalError("拒绝失败"),
    )
    @patch(
        "points.admin.services.complete_withdrawal",
        side_effect=services.WithdrawalError("完成失败"),
    )
    def test_withdrawal_admin_actions_surface_service_failures(
        self,
        _mock_complete_withdrawal,
        _mock_reject_withdrawal,
        _mock_approve_withdrawal,
    ):
        """Service exceptions should be surfaced through admin messages."""
        self.withdrawal_admin.message_user = Mock()
        approved = WithdrawalRequest.objects.create(
            wallet=self.wallet,
            amount=20,
            status=WithdrawalStatus.APPROVED,
            real_name="失败",
            phone="13800000000",
            id_card="110105194912310099",
            bank_name="建设银行",
            bank_account="6222000000000000099",
        )

        self.withdrawal_admin.approve_selected(
            self._request(),
            WithdrawalRequest.objects.filter(pk=self.withdrawal.pk),
        )
        self.withdrawal_admin.reject_selected(
            self._request(),
            WithdrawalRequest.objects.filter(pk=self.withdrawal.pk),
        )
        self.withdrawal_admin.complete_selected(
            self._request(),
            WithdrawalRequest.objects.filter(pk=approved.pk),
        )

        messages = " ".join(
            call.args[1] for call in self.withdrawal_admin.message_user.call_args_list
        )
        self.assertIn("批准失败", messages)
        self.assertIn("拒绝失败", messages)
        self.assertIn("完成失败", messages)

    def test_custom_admin_urls_and_allocation_helpers_are_exposed(self):
        """The custom grant URLs and allocation display helpers should stay wired."""
        url_names = {
            getattr(url, "name", None)
            for url in admin.site.get_urls()
            if getattr(url, "name", None)
        }

        self.assertIn("grant_points_to_users", url_names)
        self.assertIn("grant_points_to_orgs", url_names)
        self.assertEqual(
            self.allocation_admin.initiator_display(self.allocation),
            str(self.user),
        )
        self.assertIn(
            "green",
            str(self.allocation_admin.status_display(self.allocation)),
        )
        self.assertFalse(self.allocation_admin.has_add_permission(self._request()))
        self.assertFalse(
            self.allocation_admin.has_change_permission(
                self._request(), self.allocation
            )
        )

    def test_pending_grant_and_cache_admins_are_read_only(self):
        """Pending grants and contribution cache should expose status but stay immutable."""
        self.assertEqual(
            self.pending_admin.granter_display(self.pending_grant), str(self.user)
        )
        self.assertIn(
            "待领取",
            str(self.pending_admin.status_display(self.pending_grant)),
        )
        self.pending_grant.is_claimed = True
        self.pending_grant.save(update_fields=["is_claimed"])
        self.assertIn(
            "已领取",
            str(self.pending_admin.status_display(self.pending_grant)),
        )
        self.assertFalse(self.pending_admin.has_add_permission(self._request()))
        self.assertFalse(
            self.pending_admin.has_change_permission(
                self._request(), self.pending_grant
            )
        )
        self.assertFalse(self.cache_admin.has_add_permission(self._request()))

    def test_direct_grant_user_view_forbids_non_staff(self):
        """The raw helper should still reject non-staff access before admin wrapping."""
        regular_user = User.objects.create_user(
            username="points-non-staff",
            email="nonstaff@example.com",
            password="password123",
        )
        request = self._request_with_messages(
            f"/admin/points/grant-to-users/?ids={self.user.id}",
            regular_user,
        )

        response = grant_points_to_users_view(request)

        self.assertEqual(response.status_code, 403)

    def test_direct_grant_org_view_forbids_non_staff(self):
        """The organization helper should also guard against non-staff requests."""
        regular_user = User.objects.create_user(
            username="org-non-staff",
            email="org-nonstaff@example.com",
            password="password123",
        )
        request = self._request_with_messages(
            "/admin/points/grant-to-orgs/?ids=99999",
            regular_user,
        )

        response = grant_points_to_orgs_view(request)

        self.assertEqual(response.status_code, 403)

    def test_grant_user_view_handles_missing_selection_results(self):
        """Unknown user ids should redirect with an error message."""
        request = self._request_with_messages(
            "/admin/points/grant-to-users/?ids=999999",
            self.admin_user,
        )
        response = grant_points_to_users_view(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin:accounts_user_changelist"))
        messages_text = [message.message for message in get_messages(request)]
        self.assertIn("未找到选中的用户", messages_text)

    @patch("points.admin.services.grant_points", side_effect=Exception("发放失败"))
    def test_grant_user_view_reports_failures_without_success_banner(self, _mock_grant):
        """A fully failed batch should report errors and skip the success flash."""
        request = self._request_with_messages(
            f"/admin/points/grant-to-users/?ids={self.user.id}",
            self.admin_user,
            method="post",
            data={
                "point_type": PointType.CASH.value,
                "amount": 50,
                "reason": "失败场景",
            },
        )
        response = grant_points_to_users_view(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin:accounts_user_changelist"))
        messages_text = [message.message for message in get_messages(request)]
        self.assertTrue(
            any("给用户 points-owner 发放失败" in text for text in messages_text)
        )
        self.assertFalse(any("成功给" in text for text in messages_text))

    def test_grant_org_view_handles_missing_selection_results(self):
        """Unknown organization ids should redirect with an error message."""
        request = self._request_with_messages(
            "/admin/points/grant-to-orgs/?ids=999999",
            self.admin_user,
        )
        response = grant_points_to_orgs_view(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url, reverse("admin:accounts_organization_changelist")
        )
        messages_text = [message.message for message in get_messages(request)]
        self.assertIn("未找到选中的组织", messages_text)

    @patch("points.admin.services.grant_points", side_effect=Exception("发放失败"))
    def test_grant_org_view_reports_failures_without_success_banner(self, _mock_grant):
        """A fully failed organization batch should emit only error messages."""
        organization = Organization.objects.create(name="失败组织", slug="failed-org")
        request = self._request_with_messages(
            f"/admin/points/grant-to-orgs/?ids={organization.id}",
            self.admin_user,
            method="post",
            data={
                "point_type": PointType.CASH.value,
                "amount": 50,
                "reason": "失败场景",
            },
        )
        response = grant_points_to_orgs_view(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url, reverse("admin:accounts_organization_changelist")
        )
        messages_text = [message.message for message in get_messages(request)]
        self.assertTrue(
            any("给组织 失败组织 发放失败" in text for text in messages_text)
        )
        self.assertFalse(any("成功给" in text for text in messages_text))
