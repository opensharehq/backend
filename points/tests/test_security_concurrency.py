"""Real database concurrency regressions; SQLite cannot exercise row locks."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.db import connections
from django.test import (
    Client,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)

from accounts.models import User
from accounts.services import profile_completion_reward as rewards
from accounts.services.jwt_tokens import create_access_token
from points import services as points
from points.models import PointSource, PointType, WithdrawalRefund
from points.tests import test_security_regressions as fixtures
from shenbianyun import services as payments
from shenbianyun.models import PaymentRecord
from shop.models import Redemption
from shop.pricing import UserTierDiscount
from shop.services import RedemptionError, redeem_item


@skipUnlessDBFeature("has_select_for_update")
@override_settings(SBY_TASK_ID="1", SBY_PROVIDER_ID="1")
class PointsConcurrencyTests(TransactionTestCase):
    user = fixtures.PointsSecurityTests.user
    item = fixtures.PointsSecurityTests.item
    approved = fixtures.PointsSecurityTests.approved
    allocation_payload = fixtures.PointsSecurityTests.allocation_payload

    def concurrent(self, operation):
        ready = Barrier(2)

        def run(index):
            connections.close_all()
            try:
                ready.wait(timeout=10)
                return operation(index)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, i) for i in range(2)]
            return [future.result(timeout=20) for future in futures]

    def test_concurrent_reward_issues_once(self):
        user = self.user("concurrent_reward", complete=True)
        calculating = Barrier(2)

        def calculate(_user):
            calculating.wait(timeout=10)
            return {"points": 200}

        with patch.object(rewards, "calculate_reward_points", side_effect=calculate):
            results = self.concurrent(
                lambda _: rewards.grant_profile_completion_reward(
                    User.objects.get(pk=user.pk)
                )
            )
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(points.get_balance(user), 200)
        self.assertEqual(
            PointSource.objects.filter(
                reference_id=f"profile_completion_reward:{user.pk}"
            ).count(),
            1,
        )

    def test_concurrent_refund_issues_once(self):
        user, withdrawal = self.approved("concurrent_refund")
        results = self.concurrent(lambda _: points.refund_withdrawal(withdrawal))
        self.assertCountEqual(results, [True, False])
        self.assertEqual(points.get_balance(user), 200)
        self.assertEqual(
            WithdrawalRefund.objects.filter(withdrawal=withdrawal).count(), 1
        )

    def test_concurrent_payment_tasks_submit_once(self):
        user, withdrawal = self.approved("concurrent_payment")
        with patch.object(
            payments.ShenbianyunClient, "request", return_value={"res_data": {}}
        ) as provider:
            self.concurrent(lambda _: payments.batch_payment())
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(
            PaymentRecord.objects.filter(withdrawal_request=withdrawal).count(), 1
        )
        self.assertEqual(points.get_balance(user), 0)

    def test_concurrent_allocations_cannot_spend_same_lot(self):
        sender = self.user("concurrent_allocator")
        receivers = [self.user(f"concurrent_receiver_{i}") for i in range(2)]
        points.grant_points(sender, 100, PointType.GIFT, "funding")
        token = create_access_token(sender)

        def allocate(index):
            response = Client().post(
                "/api/v1/points/allocations",
                self.allocation_payload(receivers[index]),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )
            return response.status_code

        self.assertCountEqual(self.concurrent(allocate), [201, 409])
        self.assertEqual(sum(points.get_balance(user) for user in receivers), 100)
        self.assertEqual(points.get_balance(sender), 0)

    def test_concurrent_redemptions_of_different_items_cannot_overspend(self):
        user = self.user("concurrent_shopper")
        points.grant_points(user, 100, PointType.GIFT, "funding")
        items = [self.item() for _ in range(2)]

        def redeem(index):
            try:
                redeem_item(User.objects.get(pk=user.pk), items[index].pk)
            except RedemptionError:
                return False
            return True

        with patch(
            "shop.services.resolve_user_tier_discount", return_value=UserTierDiscount()
        ):
            self.assertCountEqual(self.concurrent(redeem), [True, False])
        self.assertEqual(Redemption.objects.filter(user_profile=user).count(), 1)
        self.assertEqual(points.get_balance(user), 0)
