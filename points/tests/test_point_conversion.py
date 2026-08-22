"""Tests for the one-time RMB-to-USD point conversion."""

import json
from datetime import date
from io import StringIO
from unittest import mock

from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from accounts.models import User
from points.allocation_services import AllocationService
from points.models import (
    PendingPointGrant,
    PointAllocation,
    PointSource,
    PointTransaction,
    PointType,
    PointWallet,
    WithdrawalRequest,
)
from points.point_conversion import (
    PointConversionBlocked,
    apply_point_conversion,
    apportion_source_amounts,
    build_conversion_summary,
    convert_amount,
    lock_conversion_tables,
)
from talent_reach.models import OutreachCampaign, OutreachRecipient


class PointConversionMathTests(SimpleTestCase):
    """Exercise exact conversion and deterministic apportionment."""

    def test_convert_amount_uses_exact_floor_rounding(self):
        self.assertEqual(convert_amount(0), 0)
        self.assertEqual(convert_amount(6), 0)
        self.assertEqual(convert_amount(7), 1)
        self.assertEqual(convert_amount(66), 9)
        self.assertEqual(convert_amount(67), 10)

    def test_convert_amount_rejects_negative_values(self):
        with self.assertRaisesMessage(ValueError, "non-negative"):
            convert_amount(-1)

    def test_apportion_preserves_converted_bucket_total(self):
        converted = apportion_source_amounts([(4, 5), (2, 5), (3, 5), (1, 5)])

        self.assertEqual(converted, {1: 1, 2: 1, 3: 0, 4: 0})
        self.assertEqual(sum(converted.values()), convert_amount(20))

    def test_apportion_handles_empty_and_rejects_negative_values(self):
        self.assertEqual(apportion_source_amounts([]), {})
        with self.assertRaisesMessage(ValueError, "non-negative"):
            apportion_source_amounts([(1, -1)])

    def test_non_postgres_table_lock_is_a_noop(self):
        connection = mock.Mock(vendor="sqlite")

        lock_conversion_tables(connection, [mock.Mock()])

        connection.cursor.assert_not_called()

    def test_postgres_table_lock_quotes_all_model_tables(self):
        cursor = mock.MagicMock()
        cursor.__enter__.return_value = cursor
        connection = mock.Mock(vendor="postgresql")
        connection.ops.quote_name.side_effect = lambda name: f'"{name}"'
        connection.cursor.return_value = cursor
        first_model = mock.Mock()
        first_model._meta.db_table = "points_pointsource"
        second_model = mock.Mock()
        second_model._meta.db_table = "points_pointtransaction"

        lock_conversion_tables(connection, [first_model, second_model])

        cursor.execute.assert_called_once_with(
            'LOCK TABLE "points_pointsource", '
            '"points_pointtransaction" IN ACCESS EXCLUSIVE MODE'
        )


class PointConversionIntegrationTests(TestCase):
    """Exercise previews and writes against real Django models."""

    def setUp(self):
        self.owner = User.objects.create_user(username="conversion-owner")
        self.recipient = User.objects.create_user(username="conversion-recipient")
        self.rewarded_recipient = User.objects.create_user(
            username="conversion-rewarded"
        )
        self.user_type = ContentType.objects.get_for_model(User)
        self.wallet = PointWallet.objects.create(
            content_type=self.user_type,
            object_id=self.owner.id,
        )
        self.cash_source_one = self._create_source(PointType.CASH, 5)
        self.cash_source_two = self._create_source(PointType.CASH, 5)
        self.gift_source = self._create_source(PointType.GIFT, 67)
        self.allocation = PointAllocation.objects.create(
            initiator_type=self.user_type,
            initiator_id=self.owner.id,
            source_pool=self.cash_source_one,
            total_amount=207,
            project_scope={"tags": ["owner/repo"]},
            start_month=date(2026, 1, 1),
            end_month=date(2026, 1, 1),
            status="completed",
        )
        self.pending = self._create_pending(amount=67)
        self.small_pending = self._create_pending(amount=6)
        self.claimed_pending = self._create_pending(
            amount=134,
            is_claimed=True,
            claimed_by=self.recipient,
            claimed_at=timezone.now(),
        )
        self.campaign = OutreachCampaign.objects.create(
            author=self.owner,
            title="Conversion campaign",
            content="Body",
            point_type=PointType.CASH,
            cost_per_user=67,
            total_cost=134,
            reward_ratio=0.5,
            reward_pool=67,
            reward_expiry_days=30,
            total_recipients=2,
            status=OutreachCampaign.Status.COMPLETED,
        )
        self.outreach_pending = OutreachRecipient.objects.create(
            campaign=self.campaign,
            user=self.recipient,
            reward_amount=67,
        )
        self.outreach_rewarded = OutreachRecipient.objects.create(
            campaign=self.campaign,
            user=self.rewarded_recipient,
            reward_amount=67,
            is_rewarded=True,
            rewarded_at=timezone.now(),
        )

    def _create_source(self, point_type, amount):
        return PointSource.objects.create(
            wallet=self.wallet,
            point_type=point_type,
            original_amount=amount,
            remaining_amount=amount,
            reason="conversion fixture",
        )

    def _create_pending(self, amount, **kwargs):
        return PendingPointGrant.objects.create(
            platform="github",
            actor_id=f"actor-{PendingPointGrant.objects.count()}",
            actor_login="recipient",
            amount=amount,
            point_type=PointType.CASH,
            reason="pending conversion fixture",
            granter_type=self.user_type,
            granter_id=self.owner.id,
            allocation=self.allocation,
            **kwargs,
        )

    @staticmethod
    def _summary():
        return build_conversion_summary(
            PointSource=PointSource,
            PendingPointGrant=PendingPointGrant,
            PointAllocation=PointAllocation,
            WithdrawalRequest=WithdrawalRequest,
            OutreachRecipient=OutreachRecipient,
        )

    @staticmethod
    def _apply():
        return apply_point_conversion(
            PointSource=PointSource,
            PointTransaction=PointTransaction,
            PendingPointGrant=PendingPointGrant,
            PointAllocation=PointAllocation,
            WithdrawalRequest=WithdrawalRequest,
            OutreachRecipient=OutreachRecipient,
        )

    def test_summary_reports_all_affected_liabilities(self):
        summary = self._summary()

        self.assertEqual(summary.source_rows, 3)
        self.assertEqual(summary.wallet_buckets, 2)
        self.assertEqual(summary.wallet_old_total, 77)
        self.assertEqual(summary.wallet_new_total, 11)
        self.assertEqual(summary.pending_rows, 3)
        self.assertEqual(summary.pending_unclaimed_rows, 2)
        self.assertEqual(summary.pending_old_total, 207)
        self.assertEqual(summary.pending_new_total, 30)
        self.assertEqual(summary.pending_unclaimed_zero_after, 1)
        self.assertEqual(summary.outreach_unclaimed_rows, 1)
        self.assertEqual(summary.outreach_old_total, 67)
        self.assertEqual(summary.outreach_new_total, 10)
        self.assertEqual(summary.outreach_zero_after, 0)
        self.assertFalse(summary.has_blockers)
        self.assertFalse(summary.as_dict()["has_blockers"])

    def test_apply_converts_balances_and_appends_adjustment_transactions(self):
        summary = self._apply()

        self.assertEqual(summary.wallet_old_total, 77)
        self.cash_source_one.refresh_from_db()
        self.cash_source_two.refresh_from_db()
        self.gift_source.refresh_from_db()
        self.assertEqual(
            self.cash_source_one.remaining_amount
            + self.cash_source_two.remaining_amount,
            1,
        )
        self.assertEqual(self.gift_source.remaining_amount, 10)
        self.assertEqual(self.cash_source_one.original_amount, 5)

        self.pending.refresh_from_db()
        self.small_pending.refresh_from_db()
        self.claimed_pending.refresh_from_db()
        self.assertEqual(self.pending.amount, 10)
        self.assertEqual(self.small_pending.amount, 0)
        self.assertEqual(self.claimed_pending.amount, 20)

        self.outreach_pending.refresh_from_db()
        self.outreach_rewarded.refresh_from_db()
        self.assertEqual(self.outreach_pending.reward_amount, 10)
        self.assertEqual(self.outreach_rewarded.reward_amount, 67)

        cash_transaction = PointTransaction.objects.get(point_type=PointType.CASH)
        gift_transaction = PointTransaction.objects.get(point_type=PointType.GIFT)
        self.assertEqual(cash_transaction.amount, -9)
        self.assertEqual(cash_transaction.balance_after, 1)
        self.assertEqual(gift_transaction.amount, -57)
        self.assertEqual(gift_transaction.balance_after, 10)
        self.assertIn("point_conversion:rmb_to_usd_2026", cash_transaction.reference_id)

    def test_pending_grants_preserve_each_claimants_converted_total(self):
        first = self._create_pending(amount=5)
        second = self._create_pending(amount=5)
        third = self._create_pending(amount=5)
        fourth = self._create_pending(amount=5)
        PendingPointGrant.objects.filter(
            id__in=[first.id, second.id, third.id, fourth.id]
        ).update(actor_id="shared-actor")

        self._apply()

        converted_amounts = list(
            PendingPointGrant.objects.filter(
                id__in=[first.id, second.id, third.id, fourth.id]
            )
            .order_by("id")
            .values_list("amount", flat=True)
        )
        self.assertEqual(converted_amounts, [1, 1, 0, 0])
        self.assertEqual(sum(converted_amounts), convert_amount(20))

    def test_unidentifiable_pending_grants_are_converted_individually(self):
        grants = [self._create_pending(amount=5) for _ in range(4)]
        grant_ids = [grant.id for grant in grants]
        PendingPointGrant.objects.filter(id__in=grant_ids).update(actor_id="")

        self._apply()

        converted_amounts = list(
            PendingPointGrant.objects.filter(id__in=grant_ids)
            .order_by("id")
            .values_list("amount", flat=True)
        )
        self.assertEqual(converted_amounts, [0, 0, 0, 0])

    def test_claimed_grants_without_claimant_are_converted_individually(self):
        grants = [
            self._create_pending(
                amount=5,
                is_claimed=True,
                claimed_at=timezone.now(),
            )
            for _ in range(4)
        ]
        grant_ids = [grant.id for grant in grants]

        self._apply()

        converted_amounts = list(
            PendingPointGrant.objects.filter(id__in=grant_ids)
            .order_by("id")
            .values_list("amount", flat=True)
        )
        self.assertEqual(converted_amounts, [0, 0, 0, 0])

    def test_apply_stops_before_writing_when_an_allocation_is_active(self):
        self.allocation.status = "executing"
        self.allocation.save(update_fields=["status"])

        with self.assertRaisesMessage(PointConversionBlocked, "active allocations=1"):
            self._apply()

        self.cash_source_one.refresh_from_db()
        self.assertEqual(self.cash_source_one.remaining_amount, 5)
        self.assertFalse(PointTransaction.objects.exists())

    def test_apply_stops_for_pending_withdrawal(self):
        WithdrawalRequest.objects.create(
            wallet=self.wallet,
            amount=5,
            status="pending",
            real_name="Test User",
            phone="123",
            id_card="123",
            bank_name="Test Bank",
            bank_account="123",
        )

        summary = self._summary()
        self.assertEqual(summary.blocking_withdrawals, 1)
        self.assertTrue(summary.has_blockers)
        with self.assertRaisesMessage(
            PointConversionBlocked,
            "pending/approved withdrawals=1",
        ):
            self._apply()

    def test_zero_pending_grant_can_be_settled_and_rolled_back(self):
        self.small_pending.amount = 0
        self.small_pending.save(update_fields=["amount"])

        claimed = AllocationService._claim_pending_grant(
            self.recipient,
            self.small_pending,
        )

        self.assertEqual(claimed, 0)
        self.small_pending.refresh_from_db()
        self.assertTrue(self.small_pending.is_claimed)
        self.assertEqual(self.small_pending.claimed_by, self.recipient)

        AllocationService._rollback_single_grant(
            self.recipient,
            self.small_pending,
        )
        self.small_pending.refresh_from_db()
        self.assertFalse(self.small_pending.is_claimed)
        self.assertIsNone(self.small_pending.claimed_by)


class PreviewPointsUsdConversionCommandTests(TestCase):
    """Exercise read-only production preflight behavior."""

    @mock.patch(
        "points.management.commands.preview_points_usd_conversion."
        "Command._migration_applied",
        return_value=False,
    )
    def test_command_outputs_json_summary(self, _migration_applied):
        out = StringIO()

        call_command("preview_points_usd_conversion", json=True, stdout=out)

        payload = json.loads(out.getvalue())
        self.assertEqual(payload["wallet_old_total"], 0)
        self.assertFalse(payload["has_blockers"])

    @mock.patch(
        "points.management.commands.preview_points_usd_conversion."
        "Command._migration_applied",
        return_value=False,
    )
    def test_command_fails_when_blockers_exist(self, _migration_applied):
        user = User.objects.create_user(username="command-owner")
        user_type = ContentType.objects.get_for_model(User)
        wallet = PointWallet.objects.create(
            content_type=user_type,
            object_id=user.id,
        )
        WithdrawalRequest.objects.create(
            wallet=wallet,
            amount=10,
            status="approved",
            real_name="Test User",
            phone="123",
            id_card="123",
            bank_name="Test Bank",
            bank_account="123",
        )
        out = StringIO()

        with self.assertRaisesMessage(CommandError, "未完成积分操作"):
            call_command("preview_points_usd_conversion", stdout=out)

        self.assertIn("待处理/已批准提现 1", out.getvalue())

    @mock.patch(
        "points.management.commands.preview_points_usd_conversion."
        "Command._migration_applied",
        return_value=True,
    )
    def test_command_does_not_preview_after_migration(self, _migration_applied):
        out = StringIO()

        call_command("preview_points_usd_conversion", stdout=out)

        self.assertIn("已执行", out.getvalue())
