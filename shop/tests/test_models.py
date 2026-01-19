"""Test cases for shop models."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from shop.models import Redemption, ShopItem


class ShopItemModelTests(TestCase):
    """Test cases for ShopItem model."""

    def test_shop_item_str(self):
        """Test string representation of ShopItem."""
        item = ShopItem.objects.create(
            name="Test Item", description="Test description", cost=100
        )

        self.assertEqual(str(item), "Test Item - 100 pts")

    def test_shop_item_creation(self):
        """Test creating a shop item."""
        item = ShopItem.objects.create(
            name="Test Item",
            description="Test description",
            cost=100,
            stock=10,
            is_active=True,
        )

        self.assertEqual(item.name, "Test Item")
        self.assertEqual(item.description, "Test description")
        self.assertEqual(item.cost, 100)
        self.assertEqual(item.stock, 10)
        self.assertTrue(item.is_active)

    def test_shop_item_unlimited_stock(self):
        """Test creating item with unlimited stock."""
        item = ShopItem.objects.create(
            name="Unlimited Item", description="Test", cost=50, stock=None
        )

        self.assertIsNone(item.stock)

    def test_shop_item_default_is_active(self):
        """Test that is_active defaults to True."""
        item = ShopItem.objects.create(name="Test", description="Test", cost=10)

        self.assertTrue(item.is_active)

    def test_shop_item_timestamps(self):
        """Test that created_at and updated_at are set."""
        item = ShopItem.objects.create(name="Test", description="Test", cost=10)

        self.assertIsNotNone(item.created_at)
        self.assertIsNotNone(item.updated_at)

    def test_shop_item_without_image(self):
        """Test creating shop item without image (null/blank)."""
        item = ShopItem.objects.create(
            name="Item without Image", description="Test", cost=50
        )

        self.assertFalse(item.image)

    def test_shop_item_verbose_name(self):
        """Test that verbose_name is set correctly."""
        self.assertEqual(ShopItem._meta.verbose_name, "商城商品")
        self.assertEqual(ShopItem._meta.verbose_name_plural, "商城商品")

    def test_shop_item_max_length_validation(self):
        """Test that name field respects max_length constraint."""
        # Create item with exactly 100 characters (should work)
        long_name = "A" * 100
        item = ShopItem.objects.create(name=long_name, description="Test", cost=50)
        self.assertEqual(len(item.name), 100)

        # Test with 101 characters (should fail on save)
        very_long_name = "A" * 101
        item_too_long = ShopItem(name=very_long_name, description="Test", cost=50)
        with self.assertRaises(ValidationError):
            item_too_long.full_clean()

    def test_shop_item_cost_must_be_positive(self):
        """Test that cost cannot be negative."""
        # This is enforced by PositiveIntegerField at database level
        item = ShopItem(name="Test", description="Test", cost=-10)
        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_shop_item_cost_zero_is_valid(self):
        """Test that cost can be zero (free item)."""
        item = ShopItem.objects.create(name="Free Item", description="Test", cost=0)
        self.assertEqual(item.cost, 0)

    def test_shop_item_stock_must_be_positive_or_null(self):
        """Test that stock cannot be negative."""
        item = ShopItem(name="Test", description="Test", cost=10, stock=-5)
        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_shop_item_stock_zero_is_valid(self):
        """Test that stock can be zero (out of stock)."""
        item = ShopItem.objects.create(
            name="Out of Stock", description="Test", cost=50, stock=0
        )
        self.assertEqual(item.stock, 0)

    def test_shop_item_updated_at_changes_on_update(self):
        """Test that updated_at changes when item is updated."""
        item = ShopItem.objects.create(name="Test", description="Test", cost=100)
        original_updated_at = item.updated_at

        # Wait a tiny bit and update
        item.cost = 200
        item.save()
        item.refresh_from_db()

        self.assertGreater(item.updated_at, original_updated_at)

    def test_shop_item_created_at_does_not_change_on_update(self):
        """Test that created_at remains constant after updates."""
        item = ShopItem.objects.create(name="Test", description="Test", cost=100)
        original_created_at = item.created_at

        item.cost = 200
        item.save()
        item.refresh_from_db()

        self.assertEqual(item.created_at, original_created_at)

    def test_shop_item_relationship_with_multiple_redemptions(self):
        """Test that shop item can have multiple redemptions."""
        User = get_user_model()
        user1 = User.objects.create_user(username="user1", password="pass")
        user2 = User.objects.create_user(username="user2", password="pass")
        item = ShopItem.objects.create(
            name="Popular Item", description="Test", cost=100, stock=10
        )

        redemption1 = Redemption.objects.create(
            user_profile=user1, item=item, points_cost_at_redemption=100
        )
        redemption2 = Redemption.objects.create(
            user_profile=user2, item=item, points_cost_at_redemption=100
        )

        self.assertEqual(item.redemptions.count(), 2)
        self.assertIn(redemption1, item.redemptions.all())
        self.assertIn(redemption2, item.redemptions.all())

    def test_shop_item_is_active_false(self):
        """Test creating item with is_active=False."""
        item = ShopItem.objects.create(
            name="Inactive Item", description="Test", cost=50, is_active=False
        )
        self.assertFalse(item.is_active)

    def test_shop_item_description_can_be_long(self):
        """Test that description TextField can handle long text."""
        long_description = "Test description " * 1000
        item = ShopItem.objects.create(
            name="Test", description=long_description, cost=100
        )
        self.assertGreater(len(item.description), 1000)

    def test_shop_item_str_with_special_characters(self):
        """Test string representation with special characters."""
        item = ShopItem.objects.create(
            name="特殊商品 & 测试", description="Test", cost=999
        )
        self.assertEqual(str(item), "特殊商品 & 测试 - 999 pts")


class RedemptionModelTests(TestCase):
    """Test cases for Redemption model."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )
        self.item = ShopItem.objects.create(
            name="Test Item", description="Test", cost=100
        )

    def test_redemption_str(self):
        """Test string representation of Redemption."""
        redemption = Redemption.objects.create(
            user_profile=self.user, item=self.item, points_cost_at_redemption=100
        )

        self.assertEqual(str(redemption), "testuser redeemed Test Item")

    def test_redemption_creation(self):
        """Test creating a redemption."""
        redemption = Redemption.objects.create(
            user_profile=self.user,
            item=self.item,
            points_cost_at_redemption=100,
            status=Redemption.StatusChoices.COMPLETED,
        )

        self.assertEqual(redemption.user_profile, self.user)
        self.assertEqual(redemption.item, self.item)
        self.assertEqual(redemption.points_cost_at_redemption, 100)
        self.assertEqual(redemption.status, "COMPLETED")

    def test_redemption_default_status(self):
        """Test that status defaults to PENDING."""
        redemption = Redemption.objects.create(
            user_profile=self.user, item=self.item, points_cost_at_redemption=100
        )

        self.assertEqual(redemption.status, "PENDING")

    def test_redemption_ordering(self):
        """Test that redemptions are ordered by created_at desc."""
        redemption1 = Redemption.objects.create(
            user_profile=self.user, item=self.item, points_cost_at_redemption=100
        )
        redemption2 = Redemption.objects.create(
            user_profile=self.user, item=self.item, points_cost_at_redemption=50
        )

        redemptions = Redemption.objects.all()

        self.assertEqual(redemptions[0], redemption2)
        self.assertEqual(redemptions[1], redemption1)

    def test_redemption_verbose_name(self):
        """Test that verbose_name is set correctly."""
        self.assertEqual(Redemption._meta.verbose_name, "兑换记录")
        self.assertEqual(Redemption._meta.verbose_name_plural, "兑换记录")

    def test_redemption_all_status_choices(self):
        """Test all status choices are valid."""
        statuses = [
            Redemption.StatusChoices.PENDING,
            Redemption.StatusChoices.COMPLETED,
            Redemption.StatusChoices.CANCELLED,
        ]

        for status in statuses:
            redemption = Redemption.objects.create(
                user_profile=self.user,
                item=self.item,
                points_cost_at_redemption=100,
                status=status,
            )
            self.assertEqual(redemption.status, status)

    def test_redemption_status_choices_values(self):
        """Test status choices have correct values and labels."""
        self.assertEqual(Redemption.StatusChoices.PENDING, "PENDING")
        self.assertEqual(Redemption.StatusChoices.COMPLETED, "COMPLETED")
        self.assertEqual(Redemption.StatusChoices.CANCELLED, "CANCELLED")

        # Test labels
        self.assertEqual(Redemption.StatusChoices.PENDING.label, "处理中")
        self.assertEqual(Redemption.StatusChoices.COMPLETED.label, "已完成")
        self.assertEqual(Redemption.StatusChoices.CANCELLED.label, "已取消")

    def test_redemption_created_at_auto_set(self):
        """Test that created_at is automatically set."""
        before_creation = timezone.now()
        redemption = Redemption.objects.create(
            user_profile=self.user,
            item=self.item,
            points_cost_at_redemption=100,
        )
        after_creation = timezone.now()

        self.assertIsNotNone(redemption.created_at)
        self.assertLessEqual(before_creation, redemption.created_at)
        self.assertLessEqual(redemption.created_at, after_creation)

    def test_redemption_created_at_immutable(self):
        """Test that created_at does not change on update."""
        redemption = Redemption.objects.create(
            user_profile=self.user,
            item=self.item,
            points_cost_at_redemption=100,
        )
        original_created_at = redemption.created_at

        redemption.status = Redemption.StatusChoices.COMPLETED
        redemption.save()
        redemption.refresh_from_db()

        self.assertEqual(redemption.created_at, original_created_at)

    def test_redemption_user_cascade_delete(self):
        """Test that redemptions are deleted when user is deleted."""
        redemption = Redemption.objects.create(
            user_profile=self.user,
            item=self.item,
            points_cost_at_redemption=100,
        )

        redemption_id = redemption.id
        self.user.delete()

        # Redemption should be deleted
        self.assertFalse(Redemption.objects.filter(id=redemption_id).exists())

    def test_redemption_item_protect_delete(self):
        """Test that shop item cannot be deleted if it has redemptions."""
        Redemption.objects.create(
            user_profile=self.user,
            item=self.item,
            points_cost_at_redemption=100,
        )

        # Try to delete the item - should be protected
        with self.assertRaises(ProtectedError):
            self.item.delete()

    def test_redemption_user_can_have_multiple_redemptions(self):
        """Test that one user can have multiple redemptions."""
        item1 = ShopItem.objects.create(name="Item 1", description="Test", cost=50)
        item2 = ShopItem.objects.create(name="Item 2", description="Test", cost=75)

        redemption1 = Redemption.objects.create(
            user_profile=self.user, item=item1, points_cost_at_redemption=50
        )
        redemption2 = Redemption.objects.create(
            user_profile=self.user, item=item2, points_cost_at_redemption=75
        )

        self.assertEqual(self.user.redemptions.count(), 2)
        self.assertIn(redemption1, self.user.redemptions.all())
        self.assertIn(redemption2, self.user.redemptions.all())

    def test_redemption_points_cost_can_differ_from_item_cost(self):
        """Test that points_cost_at_redemption can differ from current item cost."""
        # Item currently costs 100
        redemption = Redemption.objects.create(
            user_profile=self.user,
            item=self.item,
            points_cost_at_redemption=150,  # User paid 150 at time of redemption
        )

        self.assertEqual(redemption.points_cost_at_redemption, 150)
        self.assertEqual(self.item.cost, 100)  # Item cost unchanged

    def test_redemption_points_cost_must_be_positive(self):
        """Test that points_cost_at_redemption cannot be negative."""
        redemption = Redemption(
            user_profile=self.user,
            item=self.item,
            points_cost_at_redemption=-50,
        )

        with self.assertRaises(ValidationError):
            redemption.full_clean()

    def test_redemption_points_cost_zero_is_valid(self):
        """Test that points_cost_at_redemption can be zero (free redemption)."""
        redemption = Redemption.objects.create(
            user_profile=self.user,
            item=self.item,
            points_cost_at_redemption=0,
        )
        self.assertEqual(redemption.points_cost_at_redemption, 0)

    def test_redemption_str_with_special_characters_in_username(self):
        """Test string representation with special characters in username."""
        User = get_user_model()
        user = User.objects.create_user(username="user@test", password="pass")
        item = ShopItem.objects.create(name="特殊商品", description="Test", cost=100)
        redemption = Redemption.objects.create(
            user_profile=user, item=item, points_cost_at_redemption=100
        )

        self.assertEqual(str(redemption), "user@test redeemed 特殊商品")

    def test_redemption_ordering_with_multiple_users(self):
        """Test ordering works correctly with redemptions from different users."""
        User = get_user_model()
        user1 = User.objects.create_user(username="user1", password="pass")
        user2 = User.objects.create_user(username="user2", password="pass")

        # Create redemptions in alternating order
        r1 = Redemption.objects.create(
            user_profile=user1, item=self.item, points_cost_at_redemption=100
        )
        r2 = Redemption.objects.create(
            user_profile=user2, item=self.item, points_cost_at_redemption=100
        )
        r3 = Redemption.objects.create(
            user_profile=user1, item=self.item, points_cost_at_redemption=100
        )

        redemptions = Redemption.objects.all()
        # Should be ordered by created_at desc (newest first)
        self.assertEqual(redemptions[0], r3)
        self.assertEqual(redemptions[1], r2)
        self.assertEqual(redemptions[2], r1)

    def test_redemption_related_name_on_user(self):
        """Test that redemptions can be accessed via user.redemptions."""
        redemption = Redemption.objects.create(
            user_profile=self.user,
            item=self.item,
            points_cost_at_redemption=100,
        )

        self.assertIn(redemption, self.user.redemptions.all())
        self.assertEqual(self.user.redemptions.count(), 1)

    def test_redemption_related_name_on_item(self):
        """Test that redemptions can be accessed via item.redemptions."""
        redemption = Redemption.objects.create(
            user_profile=self.user,
            item=self.item,
            points_cost_at_redemption=100,
        )

        self.assertIn(redemption, self.item.redemptions.all())
        self.assertEqual(self.item.redemptions.count(), 1)

    def test_redemption_status_update(self):
        """Test updating redemption status."""
        redemption = Redemption.objects.create(
            user_profile=self.user,
            item=self.item,
            points_cost_at_redemption=100,
        )

        self.assertEqual(redemption.status, Redemption.StatusChoices.PENDING)

        redemption.status = Redemption.StatusChoices.COMPLETED
        redemption.save()
        redemption.refresh_from_db()

        self.assertEqual(redemption.status, Redemption.StatusChoices.COMPLETED)

    def test_redemption_max_status_length_validation(self):
        """Test that status field respects max_length constraint."""
        # Status field has max_length=10, valid statuses fit within this
        redemption = Redemption.objects.create(
            user_profile=self.user,
            item=self.item,
            points_cost_at_redemption=100,
            status=Redemption.StatusChoices.PENDING,
        )

        self.assertLessEqual(len(redemption.status), 10)

    def test_redemption_filter_by_status(self):
        """Test filtering redemptions by status."""
        r1 = Redemption.objects.create(
            user_profile=self.user,
            item=self.item,
            points_cost_at_redemption=100,
            status=Redemption.StatusChoices.PENDING,
        )
        r2 = Redemption.objects.create(
            user_profile=self.user,
            item=self.item,
            points_cost_at_redemption=100,
            status=Redemption.StatusChoices.COMPLETED,
        )
        r3 = Redemption.objects.create(
            user_profile=self.user,
            item=self.item,
            points_cost_at_redemption=100,
            status=Redemption.StatusChoices.CANCELLED,
        )

        pending = Redemption.objects.filter(status=Redemption.StatusChoices.PENDING)
        completed = Redemption.objects.filter(status=Redemption.StatusChoices.COMPLETED)
        cancelled = Redemption.objects.filter(status=Redemption.StatusChoices.CANCELLED)

        self.assertEqual(pending.count(), 1)
        self.assertIn(r1, pending)

        self.assertEqual(completed.count(), 1)
        self.assertIn(r2, completed)

        self.assertEqual(cancelled.count(), 1)
        self.assertIn(r3, cancelled)
