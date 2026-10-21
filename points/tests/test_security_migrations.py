"""Verify upgrade safety for existing reward, refund and payment history."""

from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from social_django.models import UserSocialAuth

from accounts.models import ProfileRewardIdentity, User
from points import services
from points.models import PointType, WithdrawalRefund
from points.tests import test_security_regressions as fixtures
from shenbianyun.models import PaymentRecord


class HistoricalClaimsMigrationTests(TestCase):
    user = fixtures.PointsSecurityTests.user
    approved = fixtures.PointsSecurityTests.approved

    def test_reward_migration_preserves_ledger_and_old_merge_chain(self):
        source = self.user("old_claim")
        intermediate = self.user("old_merge")
        target = self.user("old_target")
        User.objects.filter(pk=source.pk).update(
            merged_into=intermediate, is_active=False
        )
        User.objects.filter(pk=intermediate.pk).update(
            merged_into=target, is_active=False
        )
        UserSocialAuth.objects.create(
            user=target, provider="github", uid="legacy-identity"
        )
        services.grant_points(
            source,
            200,
            PointType.GIFT,
            "legacy claim",
            reference_id=f"profile_completion_reward:{source.pk}",
        )
        migration = import_module("accounts.migrations.0020_profilerewardidentity")
        with self.subTest(upgrade="historical backfill"):
            editor = SimpleNamespace(connection=connection)
            migration.preserve_existing_claims(apps, editor)
            migration.preserve_existing_claims(apps, editor)
        for user in (source, intermediate, target):
            user.profile.refresh_from_db()
            self.assertTrue(user.profile.profile_completion_rewarded)
        self.assertEqual(
            ProfileRewardIdentity.objects.filter(uid="legacy-identity").count(), 1
        )
        self.assertEqual(services.get_balance(source), 200)
        self.assertEqual(services.get_balance(target), 0)

    def test_refund_migration_marks_history_without_reissuing_points(self):
        user, withdrawal = self.approved("old_refund")
        services.grant_points(
            user,
            200,
            PointType.CASH,
            "legacy",
            reference_id=f"refund:withdrawal:{withdrawal.pk}",
        )
        migration = import_module(
            "points.migrations.0009_alter_pointsource_options_withdrawalrefund"
        )
        with self.subTest(upgrade="historical backfill"):
            editor = SimpleNamespace(connection=connection)
            migration.preserve_existing_refunds(apps, editor)
            migration.preserve_existing_refunds(apps, editor)
        self.assertEqual(
            WithdrawalRefund.objects.filter(withdrawal=withdrawal).count(), 1
        )
        self.assertFalse(services.refund_withdrawal(withdrawal))
        self.assertEqual(services.get_balance(user), 200)


class HistoricalPaymentMigrationTests(TransactionTestCase):
    user = fixtures.PointsSecurityTests.user
    approved = fixtures.PointsSecurityTests.approved
    record = fixtures.PointsSecurityTests.record

    def test_duplicate_payments_block_upgrade_without_deleting_history(self):
        old_target = [("shenbianyun", "0002_paymentrecord")]
        new_target = [("shenbianyun", "0003_alter_paymentrecord_state_and_more")]
        MigrationExecutor(connection).migrate(old_target)
        duplicate = None
        try:
            _, withdrawal = self.approved("old_payment")
            self.record(withdrawal, "historical-one")
            duplicate = self.record(withdrawal, "historical-two")
            with self.assertRaisesMessage(RuntimeError, "require reconciliation"):
                MigrationExecutor(connection).migrate(new_target)
            self.assertEqual(
                PaymentRecord.objects.filter(withdrawal_request=withdrawal).count(), 2
            )
        finally:
            # Test-only cleanup restores the schema; production migration never deletes.
            if duplicate:
                duplicate.delete()
            MigrationExecutor(connection).migrate(new_target)
