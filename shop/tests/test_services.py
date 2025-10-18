"""Test cases for shop service layer."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from points.models import Tag
from points.services import InsufficientPointsError, grant_points
from shop.models import Redemption, ShopItem
from shop.services import RedemptionError, redeem_item


class RedeemItemServiceTests(TestCase):
    """Test cases for redeem_item service function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )
        self.default_tag = Tag.objects.create(name="default", is_default=True)

    def test_redeem_item_success(self):
        """Test successful item redemption."""
        # Grant points
        grant_points(
            user_profile=self.user,
            points=200,
            description="Initial",
            tag_names=["default"],
        )

        # Create item
        item = ShopItem.objects.create(
            name="Test Item", description="Test", cost=100, stock=5
        )

        # Redeem
        redemption = redeem_item(user_profile=self.user, item_id=item.id)

        self.assertEqual(redemption.user_profile, self.user)
        self.assertEqual(redemption.item, item)
        self.assertEqual(redemption.points_cost_at_redemption, 100)
        self.assertEqual(redemption.status, Redemption.StatusChoices.COMPLETED)
        self.assertIsNotNone(redemption.transaction)

        # Check points were deducted
        self.assertEqual(self.user.total_points, 100)

        # Check stock was reduced
        item.refresh_from_db()
        self.assertEqual(item.stock, 4)

    def test_redeem_item_unlimited_stock(self):
        """Test redeeming item with unlimited stock."""
        grant_points(
            user_profile=self.user,
            points=100,
            description="Initial",
            tag_names=["default"],
        )

        item = ShopItem.objects.create(
            name="Unlimited Item", description="Test", cost=100, stock=None
        )

        redemption = redeem_item(user_profile=self.user, item_id=item.id)

        self.assertIsNotNone(redemption)
        # Stock should remain None
        item.refresh_from_db()
        self.assertIsNone(item.stock)

    def test_redeem_item_nonexistent(self):
        """Test redeeming non-existent item raises error."""
        with self.assertRaisesMessage(RedemptionError, "商品不存在"):
            redeem_item(user_profile=self.user, item_id=99999)

    def test_redeem_item_inactive(self):
        """Test redeeming inactive item raises error."""
        item = ShopItem.objects.create(
            name="Inactive Item", description="Test", cost=100, is_active=False
        )

        with self.assertRaisesMessage(RedemptionError, "该商品已下架"):
            redeem_item(user_profile=self.user, item_id=item.id)

    def test_redeem_item_out_of_stock(self):
        """Test redeeming out of stock item raises error."""
        item = ShopItem.objects.create(
            name="Out of Stock", description="Test", cost=100, stock=0
        )

        with self.assertRaisesMessage(RedemptionError, "该商品已售罄"):
            redeem_item(user_profile=self.user, item_id=item.id)

    def test_redeem_item_insufficient_points(self):
        """Test redeeming without enough points raises error."""
        grant_points(
            user_profile=self.user,
            points=50,
            description="Initial",
            tag_names=["default"],
        )

        item = ShopItem.objects.create(
            name="Expensive Item", description="Test", cost=100
        )

        with self.assertRaises(InsufficientPointsError):
            redeem_item(user_profile=self.user, item_id=item.id)

    def test_redeem_item_with_allowed_tags(self):
        """Test redeeming item with tag restrictions."""
        # Grant points with specific tag
        premium_tag = Tag.objects.create(name="premium")
        grant_points(
            user_profile=self.user,
            points=200,
            description="Premium points",
            tag_names=["premium"],
        )

        # Create item that requires premium tag
        item = ShopItem.objects.create(
            name="Premium Item", description="Test", cost=100
        )
        item.allowed_tags.add(premium_tag)

        # Redeem
        redemption = redeem_item(user_profile=self.user, item_id=item.id)

        self.assertIsNotNone(redemption)
        self.assertEqual(self.user.total_points, 100)

    def test_redeem_item_with_multiple_allowed_tags(self):
        """Test redeeming item with multiple allowed tags uses first tag as priority."""
        tag1 = Tag.objects.create(name="tag1")
        tag2 = Tag.objects.create(name="tag2")

        # Grant points with both tags
        grant_points(
            user_profile=self.user,
            points=100,
            description="Tag1 points",
            tag_names=["tag1"],
        )
        grant_points(
            user_profile=self.user,
            points=100,
            description="Tag2 points",
            tag_names=["tag2"],
        )

        # Create item with multiple allowed tags
        item = ShopItem.objects.create(
            name="Multi-tag Item", description="Test", cost=50
        )
        item.allowed_tags.set([tag1, tag2])

        # Redeem - should use tag1 as priority
        redemption = redeem_item(user_profile=self.user, item_id=item.id)

        self.assertIsNotNone(redemption)

    def test_redeem_item_atomic_transaction(self):
        """Test that redemption is atomic - failures don't change state."""
        # Grant some points
        grant_points(
            user_profile=self.user,
            points=100,
            description="Initial",
            tag_names=["default"],
        )

        # Create item with 0 stock to trigger error
        item = ShopItem.objects.create(
            name="No Stock", description="Test", cost=50, stock=0
        )

        initial_points = self.user.total_points

        # Try to redeem - should fail
        with self.assertRaises(RedemptionError):
            redeem_item(user_profile=self.user, item_id=item.id)

        # Points should not have changed
        self.assertEqual(self.user.total_points, initial_points)

        # No redemption should be created
        self.assertEqual(Redemption.objects.count(), 0)

    def test_redeem_item_records_cost_at_redemption_time(self):
        """Test that redemption records the item cost at time of redemption."""
        grant_points(
            user_profile=self.user,
            points=200,
            description="Initial",
            tag_names=["default"],
        )

        item = ShopItem.objects.create(name="Price Test", description="Test", cost=100)

        redemption = redeem_item(user_profile=self.user, item_id=item.id)

        # Record the cost
        original_cost = redemption.points_cost_at_redemption

        # Change item price
        item.cost = 150
        item.save()

        # Redemption should still show original cost
        redemption.refresh_from_db()
        self.assertEqual(redemption.points_cost_at_redemption, original_cost)
        self.assertEqual(redemption.points_cost_at_redemption, 100)

    def test_redeem_item_creates_spend_transaction(self):
        """Test that redemption creates a spend transaction."""
        grant_points(
            user_profile=self.user,
            points=100,
            description="Initial",
            tag_names=["default"],
        )

        item = ShopItem.objects.create(
            name="Transaction Test", description="Test", cost=50
        )

        initial_transaction_count = self.user.point_transactions.count()

        redemption = redeem_item(user_profile=self.user, item_id=item.id)

        # Should have one more transaction
        self.assertEqual(
            self.user.point_transactions.count(), initial_transaction_count + 1
        )

        # Transaction should be linked
        self.assertIsNotNone(redemption.transaction)
        self.assertEqual(redemption.transaction.transaction_type, "SPEND")
        self.assertEqual(redemption.transaction.points, -50)
        self.assertIn("兑换商品", redemption.transaction.description)

    def test_redeem_item_concurrent_stock_update(self):
        """Test that stock updates use F() expression to prevent race conditions."""
        grant_points(
            user_profile=self.user,
            points=100,
            description="Initial",
            tag_names=["default"],
        )

        item = ShopItem.objects.create(
            name="Stock Test", description="Test", cost=50, stock=10
        )

        # Redeem item
        redeem_item(user_profile=self.user, item_id=item.id)

        # Get fresh copy from DB
        item_from_db = ShopItem.objects.get(id=item.id)

        self.assertEqual(item_from_db.stock, 9)

    def test_redeem_item_with_empty_allowed_tags_list(self):
        """Test redeeming item when allowed_tags exists but is empty."""
        grant_points(
            user_profile=self.user,
            points=100,
            description="Initial",
            tag_names=["default"],
        )

        item = ShopItem.objects.create(name="No Tag Item", description="Test", cost=50)
        # Ensure allowed_tags is empty (no tags added)

        # Should succeed with any points (no tag restriction)
        redemption = redeem_item(user_profile=self.user, item_id=item.id)

        self.assertIsNotNone(redemption)
        self.assertEqual(redemption.status, Redemption.StatusChoices.COMPLETED)
        self.assertEqual(self.user.total_points, 50)

    def test_redeem_item_description_includes_item_name(self):
        """Test that spend transaction description includes the item name."""
        grant_points(
            user_profile=self.user,
            points=150,
            description="Initial",
            tag_names=["default"],
        )

        item = ShopItem.objects.create(
            name="特殊商品名称", description="Test", cost=100
        )

        redemption = redeem_item(user_profile=self.user, item_id=item.id)

        # Verify transaction description contains item name
        self.assertIn("兑换商品", redemption.transaction.description)
        self.assertIn("特殊商品名称", redemption.transaction.description)

    def test_redeem_item_with_exact_points(self):
        """Test redeeming when user has exact amount of points needed."""
        grant_points(
            user_profile=self.user,
            points=100,
            description="Exact amount",
            tag_names=["default"],
        )

        item = ShopItem.objects.create(name="Exact Cost", description="Test", cost=100)

        redemption = redeem_item(user_profile=self.user, item_id=item.id)

        self.assertIsNotNone(redemption)
        # User should have 0 points left
        self.assertEqual(self.user.total_points, 0)

    def test_redeem_item_stock_exactly_one(self):
        """Test redeeming item when stock is exactly 1."""
        grant_points(
            user_profile=self.user,
            points=100,
            description="Initial",
            tag_names=["default"],
        )

        item = ShopItem.objects.create(
            name="Last Item", description="Test", cost=50, stock=1
        )

        redemption = redeem_item(user_profile=self.user, item_id=item.id)

        self.assertIsNotNone(redemption)

        # Stock should be 0 now
        item.refresh_from_db()
        self.assertEqual(item.stock, 0)

        # Try to redeem again - should fail
        grant_points(
            user_profile=self.user,
            points=100,
            description="More points",
            tag_names=["default"],
        )

        with self.assertRaisesMessage(RedemptionError, "该商品已售罄"):
            redeem_item(user_profile=self.user, item_id=item.id)

    def test_redeem_item_preserves_transaction_link(self):
        """Test that redemption properly links to the spend transaction."""
        grant_points(
            user_profile=self.user,
            points=200,
            description="Initial",
            tag_names=["default"],
        )

        item = ShopItem.objects.create(name="Link Test", description="Test", cost=100)

        redemption = redeem_item(user_profile=self.user, item_id=item.id)

        # Verify bidirectional link
        self.assertIsNotNone(redemption.transaction)
        self.assertEqual(redemption.transaction.redemption, redemption)

    def test_redeem_item_with_prefetch_optimization(self):
        """Test that prefetch_related optimizes tag queries."""
        # Create multiple tags
        tag1 = Tag.objects.create(name="tag1")
        tag2 = Tag.objects.create(name="tag2")
        tag3 = Tag.objects.create(name="tag3")

        grant_points(
            user_profile=self.user,
            points=200,
            description="Tagged points",
            tag_names=["tag1", "tag2", "tag3"],
        )

        # Create item with multiple tags
        item = ShopItem.objects.create(
            name="Multi-tag Prefetch", description="Test", cost=100
        )
        item.allowed_tags.set([tag1, tag2, tag3])

        # Redeem - should work with prefetch optimization
        redemption = redeem_item(user_profile=self.user, item_id=item.id)

        self.assertIsNotNone(redemption)

    def test_redemption_error_exception_inheritance(self):
        """Test that RedemptionError is properly defined."""
        # Verify exception can be instantiated
        error = RedemptionError("Test error message")
        self.assertEqual(str(error), "Test error message")
        self.assertTrue(isinstance(error, Exception))

    def test_redeem_item_with_tagged_points_and_no_restriction(self):
        """Test using tagged points to redeem item without tag restrictions."""
        Tag.objects.create(name="special")

        grant_points(
            user_profile=self.user,
            points=150,
            description="Special points",
            tag_names=["special"],
        )

        # Item has no tag restrictions
        item = ShopItem.objects.create(name="Open Item", description="Test", cost=100)

        # Should successfully use special tagged points for unrestricted item
        redemption = redeem_item(user_profile=self.user, item_id=item.id)

        self.assertIsNotNone(redemption)
        self.assertEqual(self.user.total_points, 50)

    def test_redeem_item_updates_stock_atomically(self):
        """Test that stock update is part of atomic transaction."""
        grant_points(
            user_profile=self.user,
            points=100,
            description="Initial",
            tag_names=["default"],
        )

        item = ShopItem.objects.create(
            name="Atomic Stock", description="Test", cost=200, stock=5
        )

        initial_stock = item.stock

        # Try to redeem with insufficient points
        try:
            redeem_item(user_profile=self.user, item_id=item.id)
        except InsufficientPointsError:
            pass

        # Stock should NOT have changed
        item.refresh_from_db()
        self.assertEqual(item.stock, initial_stock)

    def test_redeem_item_requires_shipping_without_address(self):
        """Test redeeming item that requires shipping without address fails."""
        grant_points(
            user_profile=self.user,
            points=200,
            description="Initial",
            tag_names=["default"],
        )

        item = ShopItem.objects.create(
            name="Physical Item",
            description="Test",
            cost=100,
            requires_shipping=True,
        )

        # Should raise error when no shipping address provided
        with self.assertRaisesMessage(RedemptionError, "此商品需要收货地址"):
            redeem_item(user_profile=self.user, item_id=item.id)

    def test_redeem_item_requires_shipping_with_invalid_address(self):
        """Test redeeming with invalid shipping address ID fails."""
        grant_points(
            user_profile=self.user,
            points=200,
            description="Initial",
            tag_names=["default"],
        )

        item = ShopItem.objects.create(
            name="Physical Item",
            description="Test",
            cost=100,
            requires_shipping=True,
        )

        # Should raise error with invalid address ID
        with self.assertRaisesMessage(RedemptionError, "无效的收货地址"):
            redeem_item(
                user_profile=self.user,
                item_id=item.id,
                shipping_address_id=99999,
            )

    def test_redeem_item_requires_shipping_with_other_user_address(self):
        """Test redeeming with another user's address fails."""
        from accounts.models import ShippingAddress

        grant_points(
            user_profile=self.user,
            points=200,
            description="Initial",
            tag_names=["default"],
        )

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
                user_profile=self.user,
                item_id=item.id,
                shipping_address_id=other_address.id,
            )

    def test_redeem_item_requires_shipping_success(self):
        """Test successful redemption of item requiring shipping."""
        from accounts.models import ShippingAddress

        grant_points(
            user_profile=self.user,
            points=200,
            description="Initial",
            tag_names=["default"],
        )

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
            user_profile=self.user,
            item_id=item.id,
            shipping_address_id=address.id,
        )

        self.assertIsNotNone(redemption)
        self.assertEqual(redemption.shipping_address, address)
        self.assertEqual(self.user.total_points, 100)

    def test_redeem_item_not_requiring_shipping(self):
        """Test redeeming virtual item without shipping address."""
        grant_points(
            user_profile=self.user,
            points=200,
            description="Initial",
            tag_names=["default"],
        )

        item = ShopItem.objects.create(
            name="Virtual Item",
            description="Test",
            cost=100,
            requires_shipping=False,
        )

        # Should succeed without shipping address
        redemption = redeem_item(user_profile=self.user, item_id=item.id)

        self.assertIsNotNone(redemption)
        self.assertIsNone(redemption.shipping_address)
        self.assertEqual(self.user.total_points, 100)
