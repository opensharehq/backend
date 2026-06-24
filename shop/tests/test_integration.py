"""Integration tests for shop app workflows."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from points import services as points_services
from points.models import PointType
from shop.models import Redemption, ShopItem
from shop.services import RedemptionError, redeem_item


class ShopRedemptionFlowTests(TestCase):
    """Test complete shop item redemption workflow."""

    def setUp(self):
        """Set up test fixtures."""
        User = get_user_model()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        # Grant gift points for redemption tests
        points_services.grant_points(self.user, 10000, PointType.GIFT, "Test points")

    def test_complete_redemption_flow(self):
        """Test complete flow: user redeems item."""
        # Create shop item
        item = ShopItem.objects.create(
            name_zh="Premium Sticker Pack",
            name_en="Premium Sticker Pack",
            description_zh="Exclusive sticker collection",
            cost=100,
            stock=10,
            is_active=True,
        )

        # Redeem item
        result = redeem_item(
            user=self.user,
            item_id=item.id,
        )
        redemption = result["redemption"]

        # Verify redemption was created
        self.assertEqual(redemption.user_profile, self.user)
        self.assertEqual(redemption.item, item)
        self.assertEqual(redemption.points_cost_at_redemption, 100)
        self.assertEqual(redemption.status, "COMPLETED")

        # Verify stock was decremented
        item.refresh_from_db()
        self.assertEqual(item.stock, 9)

    def test_redemption_when_out_of_stock_fails(self):
        """Test redemption fails when item is out of stock."""
        # Create item with no stock
        item = ShopItem.objects.create(
            name_zh="Sold Out Item",
            name_en="Sold Out Item",
            description_zh="No longer available",
            cost=50,
            stock=0,  # Out of stock
            is_active=True,
        )

        with self.assertRaises(RedemptionError) as exc_info:
            redeem_item(user=self.user, item_id=item.id)

        self.assertTrue(
            "库存不足" in str(exc_info.exception).lower()
            or "out of stock" in str(exc_info.exception).lower()
            or "售罄" in str(exc_info.exception)
        )

    def test_redemption_when_item_inactive_fails(self):
        """Test redemption fails when item is not active."""
        # Create inactive item
        item = ShopItem.objects.create(
            name_zh="Inactive Item",
            name_en="Inactive Item",
            description_zh="Not available",
            cost=50,
            stock=10,
            is_active=False,  # Inactive
        )

        with self.assertRaises(RedemptionError) as exc_info:
            redeem_item(user=self.user, item_id=item.id)

        self.assertTrue(
            "商品已下架" in str(exc_info.exception)
            or "下架" in str(exc_info.exception)
            or "not available" in str(exc_info.exception).lower()
        )

    def test_multiple_redemptions_from_same_user(self):
        """Test user can make multiple redemptions."""
        # Create two items
        item1 = ShopItem.objects.create(
            name_zh="Item 1",
            name_en="Item 1",
            description_zh="First item",
            cost=100,
            stock=10,
            is_active=True,
        )

        item2 = ShopItem.objects.create(
            name_zh="Item 2",
            name_en="Item 2",
            description_zh="Second item",
            cost=150,
            stock=10,
            is_active=True,
        )

        # Redeem first item
        redemption1 = redeem_item(user=self.user, item_id=item1.id)["redemption"]

        # Redeem second item
        redemption2 = redeem_item(user=self.user, item_id=item2.id)["redemption"]

        # Verify both redemptions exist
        self.assertEqual(Redemption.objects.filter(user_profile=self.user).count(), 2)

        # Verify different redemptions
        self.assertEqual(redemption1.item, item1)
        self.assertEqual(redemption2.item, item2)
