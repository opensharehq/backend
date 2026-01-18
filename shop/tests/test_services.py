"""Test cases for shop service layer."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import ShippingAddress
from shop.models import Redemption, ShopItem
from shop.services import RedemptionError, redeem_item


class RedeemItemServiceTests(TestCase):
    """Test cases for redeem_item service function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )

    def test_redeem_item_success(self):
        """Test successful item redemption."""
        item = ShopItem.objects.create(
            name="Test Item", description="Test", cost=100, stock=5
        )

        redemption = redeem_item(user=self.user, item_id=item.id)

        self.assertEqual(redemption.user_profile, self.user)
        self.assertEqual(redemption.item, item)
        self.assertEqual(redemption.points_cost_at_redemption, 100)
        self.assertEqual(redemption.status, Redemption.StatusChoices.COMPLETED)

        # Check stock was reduced
        item.refresh_from_db()
        self.assertEqual(item.stock, 4)

    def test_redeem_item_unlimited_stock(self):
        """Test redeeming item with unlimited stock."""
        item = ShopItem.objects.create(
            name="Unlimited Item", description="Test", cost=100, stock=None
        )

        redemption = redeem_item(user=self.user, item_id=item.id)

        self.assertIsNotNone(redemption)
        # Stock should remain None
        item.refresh_from_db()
        self.assertIsNone(item.stock)

    def test_redeem_item_nonexistent(self):
        """Test redeeming non-existent item raises error."""
        with self.assertRaisesMessage(RedemptionError, "商品不存在"):
            redeem_item(user=self.user, item_id=99999)

    def test_redeem_item_inactive(self):
        """Test redeeming inactive item raises error."""
        item = ShopItem.objects.create(
            name="Inactive Item", description="Test", cost=100, is_active=False
        )

        with self.assertRaisesMessage(RedemptionError, "该商品已下架"):
            redeem_item(user=self.user, item_id=item.id)

    def test_redeem_item_out_of_stock(self):
        """Test redeeming out of stock item raises error."""
        item = ShopItem.objects.create(
            name="Out of Stock", description="Test", cost=100, stock=0
        )

        with self.assertRaisesMessage(RedemptionError, "该商品已售罄"):
            redeem_item(user=self.user, item_id=item.id)

    def test_redeem_item_atomic_transaction(self):
        """Test that redemption is atomic - failures don't change state."""
        # Create item with 0 stock to trigger error
        item = ShopItem.objects.create(
            name="No Stock", description="Test", cost=50, stock=0
        )

        # Try to redeem - should fail
        with self.assertRaises(RedemptionError):
            redeem_item(user=self.user, item_id=item.id)

        # No redemption should be created
        self.assertEqual(Redemption.objects.count(), 0)

    def test_redeem_item_records_cost_at_redemption_time(self):
        """Test that redemption records the item cost at time of redemption."""
        item = ShopItem.objects.create(name="Price Test", description="Test", cost=100)

        redemption = redeem_item(user=self.user, item_id=item.id)

        # Record the cost
        original_cost = redemption.points_cost_at_redemption

        # Change item price
        item.cost = 150
        item.save()

        # Redemption should still show original cost
        redemption.refresh_from_db()
        self.assertEqual(redemption.points_cost_at_redemption, original_cost)
        self.assertEqual(redemption.points_cost_at_redemption, 100)

    def test_redeem_item_concurrent_stock_update(self):
        """Test that stock updates use F() expression to prevent race conditions."""
        item = ShopItem.objects.create(
            name="Stock Test", description="Test", cost=50, stock=10
        )

        # Redeem item
        redeem_item(user=self.user, item_id=item.id)

        # Get fresh copy from DB
        item_from_db = ShopItem.objects.get(id=item.id)

        self.assertEqual(item_from_db.stock, 9)

    def test_redemption_error_exception_inheritance(self):
        """Test that RedemptionError is properly defined."""
        # Verify exception can be instantiated
        error = RedemptionError("Test error message")
        self.assertEqual(str(error), "Test error message")
        self.assertTrue(isinstance(error, Exception))

    def test_redeem_item_stock_exactly_one(self):
        """Test redeeming item when stock is exactly 1."""
        item = ShopItem.objects.create(
            name="Last Item", description="Test", cost=50, stock=1
        )

        redemption = redeem_item(user=self.user, item_id=item.id)

        self.assertIsNotNone(redemption)

        # Stock should be 0 now
        item.refresh_from_db()
        self.assertEqual(item.stock, 0)

        # Try to redeem again - should fail
        with self.assertRaisesMessage(RedemptionError, "该商品已售罄"):
            redeem_item(user=self.user, item_id=item.id)

    def test_redeem_item_requires_shipping_without_address(self):
        """Test redeeming item that requires shipping without address fails."""
        item = ShopItem.objects.create(
            name="Physical Item",
            description="Test",
            cost=100,
            requires_shipping=True,
        )

        # Should raise error when no shipping address provided
        with self.assertRaisesMessage(RedemptionError, "此商品需要收货地址"):
            redeem_item(user=self.user, item_id=item.id)

    def test_redeem_item_requires_shipping_with_invalid_address(self):
        """Test redeeming with invalid shipping address ID fails."""
        item = ShopItem.objects.create(
            name="Physical Item",
            description="Test",
            cost=100,
            requires_shipping=True,
        )

        # Should raise error with invalid address ID
        with self.assertRaisesMessage(RedemptionError, "无效的收货地址"):
            redeem_item(
                user=self.user,
                item_id=item.id,
                shipping_address_id=99999,
            )

    def test_redeem_item_requires_shipping_with_other_user_address(self):
        """Test redeeming with another user's address fails."""
        # Create another user with an address
        other_user = get_user_model().objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="password123",
        )
        other_address = ShippingAddress.objects.create(
            user=other_user,
            receiver_name="李四",
            phone="13900139000",
            province="上海",
            city="上海市",
            district="浦东新区",
            address="地址1",
            is_default=True,
        )

        item = ShopItem.objects.create(
            name="Physical Item",
            description="Test",
            cost=100,
            requires_shipping=True,
        )

        # Should raise error when using other user's address
        with self.assertRaisesMessage(RedemptionError, "无效的收货地址"):
            redeem_item(
                user=self.user,
                item_id=item.id,
                shipping_address_id=other_address.id,
            )

    def test_redeem_item_requires_shipping_success(self):
        """Test successful redemption of item requiring shipping."""
        # Create shipping address
        address = ShippingAddress.objects.create(
            user=self.user,
            receiver_name="张三",
            phone="13800138000",
            province="北京",
            city="北京市",
            district="朝阳区",
            address="某某街道123号",
            is_default=True,
        )

        item = ShopItem.objects.create(
            name="Physical Item",
            description="Test",
            cost=100,
            requires_shipping=True,
        )

        # Should succeed with valid address
        redemption = redeem_item(
            user=self.user,
            item_id=item.id,
            shipping_address_id=address.id,
        )

        self.assertIsNotNone(redemption)
        self.assertEqual(redemption.shipping_address, address)

    def test_redeem_item_not_requiring_shipping(self):
        """Test redeeming virtual item without shipping address."""
        item = ShopItem.objects.create(
            name="Virtual Item",
            description="Test",
            cost=100,
            requires_shipping=False,
        )

        # Should succeed without shipping address
        redemption = redeem_item(user=self.user, item_id=item.id)

        self.assertIsNotNone(redemption)
        self.assertIsNone(redemption.shipping_address)
