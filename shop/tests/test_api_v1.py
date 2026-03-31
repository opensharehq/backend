"""Tests for shop API endpoints."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import ShippingAddress
from accounts.services.jwt_tokens import create_access_token
from points.models import PointType
from points.services import grant_points
from shop.models import Redemption, ShopItem


class ShopApiV1Tests(TestCase):
    """Validate shop and redemption APIs."""

    def setUp(self):
        """Create an authenticated user with redeemable points."""
        User = get_user_model()
        self.user = User.objects.create_user(
            username="shop_user",
            email="shop_user@example.com",
            password="StrongPass123!",
        )
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.user)}"
        }
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
        )

    def test_item_listing_and_redemption(self):
        """Users should be able to list active items and redeem one."""
        list_response = self.client.get("/api/v1/shop/items", **self.headers)
        self.assertEqual(list_response.status_code, 200)
        payload = list_response.json()
        self.assertEqual(payload["items"][0]["id"], self.item.id)
        self.assertIn("pagination", payload)

        redeem_response = self.client.post(
            "/api/v1/shop/redemptions",
            {"item_id": self.item.id},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(redeem_response.status_code, 200)
        self.assertEqual(redeem_response.json()["item"]["id"], self.item.id)
        self.assertTrue(
            Redemption.objects.filter(item=self.item, user_profile=self.user).exists()
        )

        history_response = self.client.get("/api/v1/shop/redemptions", **self.headers)
        self.assertEqual(history_response.status_code, 200)
        history_payload = history_response.json()
        self.assertEqual(history_payload["items"][0]["item"]["name"], self.item.name)
        self.assertEqual(history_payload["pagination"]["total_items"], 1)

    def test_item_detail_includes_shipping_addresses(self):
        """Tariff-required items should expose the user's shipping addresses."""
        shipping_item = ShopItem.objects.create(
            name="Bundle",
            description="Requires shipping",
            cost=50,
            is_active=True,
            requires_shipping=True,
        )
        ShippingAddress.objects.create(
            user=self.user,
            receiver_name="API Receiver",
            phone="13800138001",
            province="Shanghai",
            city="Shanghai",
            district="Pudong",
            address="123 API Lane",
            is_default=True,
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
        self.assertEqual(len(payload["shipping_addresses"]), 1)
