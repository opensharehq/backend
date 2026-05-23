"""Tests for shop API endpoints."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import ShippingAddress
from accounts.services.jwt_tokens import create_access_token
from config.api_common import ApiError
from points.models import PointType, PointWallet
from points.services import grant_points
from shop.api_v1 import _raise_redemption_api_error
from shop.models import Redemption, ShopItem


class ShopApiV1Tests(TestCase):
    """Validate shop and redemption APIs."""

    def setUp(self):
        """Create authenticated users and a default redeemable item."""
        User = get_user_model()
        self.user = User.objects.create_user(
            username="shop_user",
            email="shop_user@example.com",
            password="StrongPass123!",
        )
        self.other_user = User.objects.create_user(
            username="shop_other",
            email="shop_other@example.com",
            password="StrongPass123!",
        )
        self.zero_user = User.objects.create_user(
            username="shop_zero",
            email="shop_zero@example.com",
            password="StrongPass123!",
        )
        self.headers = self._headers_for(self.user)
        self.other_headers = self._headers_for(self.other_user)
        self.zero_headers = self._headers_for(self.zero_user)

        grant_points(
            owner=self.user,
            amount=500,
            point_type=PointType.GIFT,
            reason="Test gift points",
            created_by=self.user,
        )
        self.item = ShopItem.objects.create(
            name="Sticker Pack",
            description="A small reward",
            cost=100,
            is_active=True,
            requires_shipping=False,
            stock=5,
        )

    def _headers_for(self, user):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_access_token(user)}"}

    def _create_shipping_address(self, user, *, receiver_name, phone, address):
        return ShippingAddress.objects.create(
            user=user,
            receiver_name=receiver_name,
            phone=phone,
            province="Shanghai",
            city="Shanghai",
            district="Pudong",
            address=address,
            is_default=True,
        )

    def _assert_api_error(self, response, *, status_code, code, message):
        self.assertEqual(response.status_code, status_code)
        payload = response.json()
        self.assertEqual(payload["code"], code)
        self.assertEqual(payload["message"], message)
        return payload

    def test_item_listing_and_redemption(self):
        """Users should be able to list active items and redeem one."""
        list_response = self.client.get("/api/v1/shop/items", **self.headers)
        self.assertEqual(list_response.status_code, 200)
        payload = list_response.json()
        self.assertEqual(payload["items"][0]["id"], self.item.id)
        self.assertEqual(payload["balance"]["gift"], 500)
        self.assertIn("pagination", payload)

        redeem_response = self.client.post(
            "/api/v1/shop/redemptions",
            {"item_id": self.item.id},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(redeem_response.status_code, 201)
        self.assertEqual(redeem_response.json()["item"]["id"], self.item.id)
        self.assertTrue(
            Redemption.objects.filter(item=self.item, user_profile=self.user).exists()
        )

        history_response = self.client.get("/api/v1/shop/redemptions", **self.headers)
        self.assertEqual(history_response.status_code, 200)
        history_payload = history_response.json()
        self.assertEqual(history_payload["items"][0]["item"]["name"], self.item.name)
        self.assertEqual(history_payload["pagination"]["total_items"], 1)

    def test_item_detail_for_non_shipping_item_omits_addresses(self):
        """Non-shipping item detail should not include shipping address choices."""
        response = self.client.get(f"/api/v1/shop/items/{self.item.id}", **self.headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["id"], self.item.id)
        self.assertFalse(payload["requires_shipping"])
        self.assertIsNone(payload["shipping_addresses"])

    def test_item_detail_includes_only_current_users_shipping_addresses(self):
        """Shipping item detail should expose only the current user's addresses."""
        shipping_item = ShopItem.objects.create(
            name="Bundle",
            description="Requires shipping",
            cost=50,
            is_active=True,
            requires_shipping=True,
        )
        own_address = self._create_shipping_address(
            self.user,
            receiver_name="API Receiver",
            phone="13800138001",
            address="123 API Lane",
        )
        self._create_shipping_address(
            self.other_user,
            receiver_name="Other Receiver",
            phone="13800138009",
            address="9 Other Lane",
        )

        detail_response = self.client.get(
            f"/api/v1/shop/items/{shipping_item.id}",
            **self.headers,
        )

        self.assertEqual(detail_response.status_code, 200)
        payload = detail_response.json()
        self.assertEqual(payload["id"], shipping_item.id)
        self.assertTrue(payload["requires_shipping"])
        self.assertIn("shipping_addresses", payload)
        self.assertEqual(
            [item["id"] for item in payload["shipping_addresses"]], [own_address.id]
        )

    def test_redemption_api_error_mapping_handles_remaining_business_messages(self):
        """Redemption service messages should map to stable API error codes."""
        cases = [
            (
                "商品不存在。",
                404,
                "not_found",
                "The requested item was not found.",
            ),
            (
                "此商品需要收货地址。",
                422,
                "shipping_address_required",
                "A shipping address is required for this item.",
            ),
            (
                "您没有足够的符合条件的积分来兑换此商品",
                409,
                "insufficient_points",
                "You do not have enough eligible points to redeem this item.",
            ),
            (
                "积分不足：余额类型不符合商品要求",
                409,
                "insufficient_points",
                "Not enough points to redeem this item.",
            ),
            (
                "unknown redemption failure",
                409,
                "redemption_failed",
                "The item could not be redeemed.",
            ),
        ]

        for message, status_code, code, response_message in cases:
            with self.subTest(message=message), self.assertRaises(ApiError) as cm:
                _raise_redemption_api_error(message)

            error = cm.exception
            self.assertEqual(error.status_code, status_code)
            self.assertEqual(error.code, code)
            self.assertEqual(error.message, response_message)

    def test_item_list_is_read_only_for_user_without_wallet(self):
        """Listing shop items should not create a wallet for zero-balance users."""
        self.assertFalse(
            PointWallet.objects.filter(object_id=self.zero_user.id).exists()
        )

        response = self.client.get("/api/v1/shop/items", **self.zero_headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["balance"]["total"], 0)
        self.assertFalse(
            PointWallet.objects.filter(object_id=self.zero_user.id).exists()
        )

    def test_redemption_rejects_nonexistent_shipping_address(self):
        """Redemption should reject a shipping address id that does not exist."""
        shipping_item = ShopItem.objects.create(
            name="Poster",
            description="Requires shipping",
            cost=50,
            is_active=True,
            requires_shipping=True,
            stock=3,
        )

        response = self.client.post(
            "/api/v1/shop/redemptions",
            {"item_id": shipping_item.id, "shipping_address_id": 999999},
            content_type="application/json",
            **self.headers,
        )

        self._assert_api_error(
            response,
            status_code=422,
            code="invalid_shipping_address",
            message="The shipping address is invalid.",
        )
        shipping_item.refresh_from_db()
        self.assertEqual(shipping_item.stock, 3)
        self.assertFalse(Redemption.objects.filter(item=shipping_item).exists())

    def test_redemption_rejects_other_users_shipping_address(self):
        """Redemption should not reveal or accept another user's address."""
        other_address = self._create_shipping_address(
            self.other_user,
            receiver_name="Other Receiver",
            phone="13800138009",
            address="9 Other Lane",
        )
        shipping_item = ShopItem.objects.create(
            name="Mug",
            description="Requires shipping",
            cost=50,
            is_active=True,
            requires_shipping=True,
            stock=3,
        )

        response = self.client.post(
            "/api/v1/shop/redemptions",
            {"item_id": shipping_item.id, "shipping_address_id": other_address.id},
            content_type="application/json",
            **self.headers,
        )

        self._assert_api_error(
            response,
            status_code=422,
            code="invalid_shipping_address",
            message="The shipping address is invalid.",
        )
        shipping_item.refresh_from_db()
        self.assertEqual(shipping_item.stock, 3)
        self.assertFalse(Redemption.objects.filter(item=shipping_item).exists())

    def test_redemption_rejects_out_of_stock_item(self):
        """Redemption should fail with a stable error when stock is exhausted."""
        sold_out_item = ShopItem.objects.create(
            name="Limited Reward",
            description="No inventory left",
            cost=50,
            is_active=True,
            requires_shipping=False,
            stock=0,
        )

        response = self.client.post(
            "/api/v1/shop/redemptions",
            {"item_id": sold_out_item.id},
            content_type="application/json",
            **self.headers,
        )

        self._assert_api_error(
            response,
            status_code=409,
            code="out_of_stock",
            message="This item is out of stock.",
        )
        self.assertFalse(Redemption.objects.filter(item=sold_out_item).exists())

    def test_redemption_rejects_insufficient_points(self):
        """Redemption should surface the insufficient-points business error."""
        response = self.client.post(
            "/api/v1/shop/redemptions",
            {"item_id": self.item.id},
            content_type="application/json",
            **self.zero_headers,
        )

        self._assert_api_error(
            response,
            status_code=409,
            code="insufficient_points",
            message="Not enough points to redeem this item. Required: 100, available: 0.",
        )
        self.assertFalse(
            Redemption.objects.filter(
                item=self.item, user_profile=self.zero_user
            ).exists()
        )

    def test_redemption_rejects_inactive_item(self):
        """Redemption should reject inactive shop items."""
        inactive_item = ShopItem.objects.create(
            name="Retired Reward",
            description="Unavailable",
            cost=10,
            is_active=False,
            requires_shipping=False,
        )

        response = self.client.post(
            "/api/v1/shop/redemptions",
            {"item_id": inactive_item.id},
            content_type="application/json",
            **self.headers,
        )

        self._assert_api_error(
            response,
            status_code=409,
            code="item_unavailable",
            message="This item is no longer available.",
        )
        self.assertFalse(Redemption.objects.filter(item=inactive_item).exists())

    def test_redemption_history_is_isolated_to_owner(self):
        """Each user should see only their own redemption history."""
        my_redemption = Redemption.objects.create(
            user_profile=self.user,
            item=self.item,
            points_cost_at_redemption=self.item.cost,
            status=Redemption.StatusChoices.COMPLETED,
        )
        other_item = ShopItem.objects.create(
            name="Notebook",
            description="Other user's reward",
            cost=30,
            is_active=True,
            requires_shipping=False,
        )
        other_redemption = Redemption.objects.create(
            user_profile=self.other_user,
            item=other_item,
            points_cost_at_redemption=other_item.cost,
            status=Redemption.StatusChoices.COMPLETED,
        )

        my_history_response = self.client.get(
            "/api/v1/shop/redemptions", **self.headers
        )
        other_history_response = self.client.get(
            "/api/v1/shop/redemptions",
            **self.other_headers,
        )

        self.assertEqual(my_history_response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in my_history_response.json()["items"]],
            [my_redemption.id],
        )
        self.assertEqual(my_history_response.json()["pagination"]["total_items"], 1)

        self.assertEqual(other_history_response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in other_history_response.json()["items"]],
            [other_redemption.id],
        )
        self.assertEqual(other_history_response.json()["pagination"]["total_items"], 1)

    def test_redemption_detail_is_isolated_to_owner(self):
        """Users should not be able to fetch another user's redemption detail."""
        other_redemption = Redemption.objects.create(
            user_profile=self.other_user,
            item=self.item,
            points_cost_at_redemption=self.item.cost,
            status=Redemption.StatusChoices.COMPLETED,
        )

        detail_response = self.client.get(
            f"/api/v1/shop/redemptions/{other_redemption.id}",
            **self.headers,
        )

        self._assert_api_error(
            detail_response,
            status_code=404,
            code="not_found",
            message="The requested resource was not found.",
        )

    def test_redemption_detail_returns_owned_record(self):
        """Users should be able to fetch their own redemption detail."""
        address = self._create_shipping_address(
            self.user,
            receiver_name="API Receiver",
            phone="13800138001",
            address="123 API Lane",
        )
        redemption = Redemption.objects.create(
            user_profile=self.user,
            item=self.item,
            shipping_address=address,
            points_cost_at_redemption=self.item.cost,
            status=Redemption.StatusChoices.COMPLETED,
        )

        response = self.client.get(
            f"/api/v1/shop/redemptions/{redemption.id}",
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["id"], redemption.id)
        self.assertEqual(payload["item"]["id"], self.item.id)
        self.assertEqual(payload["shipping_address"]["id"], address.id)
