"""Per-user redemption limits across admin, services and the shop API."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import (
    RequestFactory,
    TestCase,
    TransactionTestCase,
    skipUnlessDBFeature,
)

from accounts.services.jwt_tokens import create_access_token
from points.models import PointType
from points.services import get_detailed_balance_or_zero, grant_points
from shop.admin import ShopItemAdmin
from shop.api_v1 import _batch_user_redemption_counts
from shop.models import CouponCode, Redemption, ShopItem
from shop.pricing import UserTierDiscount
from shop.services import RedemptionError, redeem_item


class RedemptionLimitTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="limited-user")
        self.other_user = get_user_model().objects.create_user(username="other-user")
        grant_points(self.user, 1000, PointType.GIFT, "Test points")
        grant_points(self.other_user, 1000, PointType.GIFT, "Test points")
        self.item = ShopItem.objects.create(
            name_zh="限兑商品",
            name_en="Limited item",
            description_zh="Test",
            cost=100,
            stock=5,
            max_redemptions_per_user=2,
        )
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.user)}",
        }
        self.discount_patch = patch(
            "shop.services.resolve_user_tier_discount", return_value=UserTierDiscount()
        )
        self.discount_patch.start()
        self.addCleanup(self.discount_patch.stop)

    def record(self, status, *, user=None, item=None):
        return Redemption.objects.create(
            user_profile=user or self.user,
            item=item or self.item,
            points_cost_at_redemption=100,
            status=status,
        )

    def test_third_redemption_is_rejected_without_spending_or_stock_change(self):
        for _ in range(2):
            redeem_item(self.user, self.item.id)
        balance = get_detailed_balance_or_zero(self.user)
        with self.assertRaisesMessage(RedemptionError, "已达兑换上限"):
            redeem_item(self.user, self.item.id)
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 3)
        self.assertEqual(Redemption.objects.count(), 2)
        self.assertEqual(get_detailed_balance_or_zero(self.user), balance)
        # A different user still has their full allowance.
        redeem_item(self.other_user, self.item.id)

    def test_pending_counts_but_cancelled_and_other_items_do_not(self):
        self.record(Redemption.StatusChoices.PENDING)
        self.record(Redemption.StatusChoices.CANCELLED)
        other_item = ShopItem.objects.create(name_zh="Other", cost=100)
        self.record(Redemption.StatusChoices.COMPLETED, item=other_item)
        redeem_item(self.user, self.item.id)
        with self.assertRaisesMessage(RedemptionError, "已达兑换上限"):
            redeem_item(self.user, self.item.id)

    def test_zero_default_is_unlimited_and_limits_apply_to_existing_records(self):
        item = ShopItem.objects.create(name_zh="Unlimited", cost=10)
        self.assertEqual(item.max_redemptions_per_user, 0)
        for _ in range(3):
            redeem_item(self.user, item.id)
        item.max_redemptions_per_user = 2
        item.save()
        with self.assertRaisesMessage(RedemptionError, "已达兑换上限"):
            redeem_item(self.user, item.id)
        item.max_redemptions_per_user = 4
        item.save()
        redeem_item(self.user, item.id)
        item.max_redemptions_per_user = 0
        item.save()
        redeem_item(self.user, item.id)

    def test_limit_precedes_sold_out_and_coupon_claim(self):
        self.record(Redemption.StatusChoices.COMPLETED)
        self.record(Redemption.StatusChoices.PENDING)
        self.item.stock = 0
        self.item.save()
        with self.assertRaisesMessage(RedemptionError, "已达兑换上限"):
            redeem_item(self.user, self.item.id)
        self.item.coupon_type = "limited-coupon"
        self.item.save()
        coupon = CouponCode.objects.create(code_type=self.item.coupon_type, code="ONE")
        with self.assertRaisesMessage(RedemptionError, "已达兑换上限"):
            redeem_item(self.user, self.item.id)
        coupon.refresh_from_db()
        self.assertEqual(coupon.status, CouponCode.Status.AVAILABLE)

    def test_failed_redemption_does_not_use_allowance(self):
        self.item.max_redemptions_per_user = 1
        self.item.cost = 2000
        self.item.save()
        with self.assertRaises(RedemptionError):
            redeem_item(self.user, self.item.id)
        self.assertFalse(Redemption.objects.exists())
        self.item.cost = 100
        self.item.save()
        redeem_item(self.user, self.item.id)

    def test_api_reports_personal_count_and_dedicated_conflict(self):
        self.record(Redemption.StatusChoices.PENDING)
        self.record(Redemption.StatusChoices.CANCELLED)
        self.record(Redemption.StatusChoices.COMPLETED, user=self.other_user)
        for expected_count, reached in ((1, False), (2, True)):
            detail = self.client.get(
                f"/api/v1/shop/items/{self.item.id}", **self.headers
            )
            listing = self.client.get("/api/v1/shop/items", **self.headers)
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(listing.status_code, 200)
            for item in (detail.json(), listing.json()["items"][0]):
                self.assertEqual(item["max_redemptions_per_user"], 2)
                self.assertEqual(item["user_redemption_count"], expected_count)
                self.assertEqual(item["redemption_limit_reached"], reached)
                self.assertEqual(item["stock"], 5)
            if not reached:
                self.record(Redemption.StatusChoices.COMPLETED)
        response = self.client.post(
            "/api/v1/shop/redemptions",
            {"item_id": self.item.id},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "redemption_limit_reached")
        other_headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.other_user)}",
        }
        other_detail = self.client.get(
            f"/api/v1/shop/items/{self.item.id}", **other_headers
        ).json()
        self.assertEqual(other_detail["user_redemption_count"], 1)
        self.assertFalse(other_detail["redemption_limit_reached"])

    def test_counts_are_batched_and_unlimited_items_remain_available(self):
        other_item = ShopItem.objects.create(name_zh="Unlimited", cost=100)
        for _ in range(3):
            self.record(Redemption.StatusChoices.COMPLETED, item=other_item)
        with self.assertNumQueries(1):
            counts = _batch_user_redemption_counts([self.item, other_item], self.user)
        self.assertEqual(counts, {other_item.id: 3})
        detail = self.client.get(
            f"/api/v1/shop/items/{other_item.id}", **self.headers
        ).json()
        self.assertEqual(detail["max_redemptions_per_user"], 0)
        self.assertEqual(detail["user_redemption_count"], 3)
        self.assertFalse(detail["redemption_limit_reached"])
        with self.assertNumQueries(0):
            self.assertEqual(_batch_user_redemption_counts([], self.user), {})

    def test_admin_saves_nonnegative_integer_limit(self):
        admin = ShopItemAdmin(ShopItem, AdminSite())
        request = RequestFactory().get("/")
        request.user = get_user_model().objects.create_superuser(username="admin")
        form_class = admin.get_form(request, obj=self.item)
        data = {
            "name_zh": "限兑商品",
            "name_en": "Limited item",
            "description_zh": "Test",
            "cost": 100,
            "priority": 1,
            "max_redemptions_per_user": 2,
        }
        form = form_class(data=data, instance=self.item)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().max_redemptions_per_user, 2)
        for invalid_limit in (-1, "1.5"):
            form = form_class(
                data={**data, "max_redemptions_per_user": invalid_limit},
                instance=self.item,
            )
            self.assertFalse(form.is_valid())
            self.assertIn("max_redemptions_per_user", form.errors)


@skipUnlessDBFeature("has_select_for_update")
class ConcurrentRedemptionLimitTests(TransactionTestCase):
    def test_simultaneous_requests_cannot_exceed_limit_with_unlimited_stock(self):
        user = get_user_model().objects.create_user(username="concurrent-user")
        grant_points(user, 1000, PointType.GIFT, "Test points")
        item = ShopItem.objects.create(
            name_zh="Limited", cost=100, max_redemptions_per_user=1
        )
        barrier = Barrier(2)

        def redeem():
            close_old_connections()
            try:
                request_user = get_user_model().objects.get(pk=user.pk)
                barrier.wait(timeout=10)
                try:
                    redeem_item(request_user, item.id)
                except RedemptionError as error:
                    return str(error)
                return "success"
            finally:
                close_old_connections()

        with (
            patch(
                "shop.services.resolve_user_tier_discount",
                return_value=UserTierDiscount(),
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            results = list(executor.map(lambda _: redeem(), range(2)))
        self.assertCountEqual(results, ["success", "已达兑换上限。"])
        self.assertEqual(Redemption.objects.filter(item=item).count(), 1)
        self.assertEqual(get_detailed_balance_or_zero(user)["gift_no_tag"], 900)
