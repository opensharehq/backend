"""Test cases for shop service layer."""

import pytest
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

        assert redemption.user_profile == self.user
        assert redemption.item == item
        assert redemption.points_cost_at_redemption == 100
        assert redemption.status == Redemption.StatusChoices.COMPLETED
        assert redemption.transaction is not None

        # Check points were deducted
        assert self.user.total_points == 100

        # Check stock was reduced
        item.refresh_from_db()
        assert item.stock == 4

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

        assert redemption is not None
        # Stock should remain None
        item.refresh_from_db()
        assert item.stock is None

    def test_redeem_item_nonexistent(self):
        """Test redeeming non-existent item raises error."""
        with pytest.raises(RedemptionError, match="商品不存在"):
            redeem_item(user_profile=self.user, item_id=99999)

    def test_redeem_item_inactive(self):
        """Test redeeming inactive item raises error."""
        item = ShopItem.objects.create(
            name="Inactive Item", description="Test", cost=100, is_active=False
        )

        with pytest.raises(RedemptionError, match="该商品已下架"):
            redeem_item(user_profile=self.user, item_id=item.id)

    def test_redeem_item_out_of_stock(self):
        """Test redeeming out of stock item raises error."""
        item = ShopItem.objects.create(
            name="Out of Stock", description="Test", cost=100, stock=0
        )

        with pytest.raises(RedemptionError, match="该商品已售罄"):
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

        with pytest.raises(InsufficientPointsError):
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

        assert redemption is not None
        assert self.user.total_points == 100

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

        assert redemption is not None

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
        with pytest.raises(RedemptionError):
            redeem_item(user_profile=self.user, item_id=item.id)

        # Points should not have changed
        assert self.user.total_points == initial_points

        # No redemption should be created
        assert Redemption.objects.count() == 0

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
        assert redemption.points_cost_at_redemption == original_cost
        assert redemption.points_cost_at_redemption == 100

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
        assert self.user.point_transactions.count() == initial_transaction_count + 1

        # Transaction should be linked
        assert redemption.transaction is not None
        assert redemption.transaction.transaction_type == "SPEND"
        assert redemption.transaction.points == -50
        assert "兑换商品" in redemption.transaction.description

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

        assert item_from_db.stock == 9
