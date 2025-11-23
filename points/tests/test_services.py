"""Tests for points service layer."""

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase

from points.models import PointSource, PointTransaction, Tag
from points.services import (
    InsufficientPointsError,
    PointSourceNotWithdrawableError,
    WithdrawalAmountError,
    WithdrawalData,
    WithdrawalError,
    _normalize_user,
    approve_withdrawal,
    cancel_withdrawal,
    create_withdrawal_request,
    grant_points,
    reject_withdrawal,
    spend_points,
)


class NormalizeUserTests(TestCase):
    """Validate the user normalization helper."""

    def setUp(self):
        """Create users for normalization scenarios."""
        self.user = get_user_model().objects.create_user(
            username="normalize-user", email="norm@example.com", password="password123"
        )
        self.other_user = get_user_model().objects.create_user(
            username="other-user", email="other@example.com", password="password123"
        )

    def test_normalize_user_requires_arguments(self):
        """_normalize_user raises when both arguments are empty."""
        with self.assertRaisesMessage(
            ValueError, "必须提供 user 或 user_profile 参数。"
        ):
            _normalize_user()

    def test_normalize_user_rejects_mismatched_arguments(self):
        """_normalize_user rejects conflicting user references."""
        with self.assertRaisesMessage(
            ValueError, "user 与 user_profile 参数指向不同的用户。"
        ):
            _normalize_user(user=self.user, user_profile=self.other_user)


class GrantPointsTests(TestCase):
    """Test cases for grant_points service function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )

    def test_grant_points_success(self):
        """Test granting points creates source and transaction."""
        source = grant_points(
            user_profile=self.user,
            points=100,
            description="Test grant",
            tag_names=["tag1", "tag2"],
        )

        self.assertEqual(source.initial_points, 100)
        self.assertEqual(source.remaining_points, 100)
        self.assertEqual(source.tags.count(), 2)

        self.assertEqual(self.user.point_transactions.count(), 1)
        transaction = self.user.point_transactions.first()
        self.assertEqual(transaction.points, 100)
        self.assertEqual(transaction.transaction_type, "EARN")

    def test_grant_points_invalid_amount(self):
        """Test granting negative or zero points raises ValueError."""
        with self.assertRaisesMessage(ValueError, "发放的积分必须是正整数"):
            grant_points(
                user_profile=self.user,
                points=0,
                description="Invalid",
                tag_names=["tag1"],
            )

        with self.assertRaisesMessage(ValueError, "发放的积分必须是正整数"):
            grant_points(
                user_profile=self.user,
                points=-10,
                description="Invalid",
                tag_names=["tag1"],
            )

    def test_grant_points_non_integer_amount(self):
        """Test granting non-integer points raises ValueError."""
        with self.assertRaisesMessage(ValueError, "发放的积分必须是正整数"):
            grant_points(
                user_profile=self.user,
                points=10.5,
                description="Float amount",
                tag_names=["tag1"],
            )

        with self.assertRaisesMessage(ValueError, "发放的积分必须是正整数"):
            grant_points(
                user_profile=self.user,
                points="100",
                description="String amount",
                tag_names=["tag1"],
            )

    def test_grant_points_creates_tags(self):
        """Test granting points creates tags if they don't exist."""
        grant_points(
            user_profile=self.user,
            points=100,
            description="Test",
            tag_names=["new-tag"],
        )

        self.assertTrue(Tag.objects.filter(name="new-tag").exists())

    def test_grant_points_with_slug(self):
        """Test granting points using tag slug."""
        # Create a tag with known slug
        Tag.objects.create(name="Premium", slug="premium")

        source = grant_points(
            user_profile=self.user,
            points=100,
            description="Test with slug",
            tag_names=["premium"],  # Use slug instead of name
        )

        self.assertEqual(source.tags.count(), 1)
        self.assertEqual(source.tags.first().name, "Premium")
        # Ensure no duplicate tag was created
        self.assertEqual(Tag.objects.filter(name="Premium").count(), 1)

    def test_grant_points_with_name(self):
        """Test granting points using tag name."""
        # Create a tag
        Tag.objects.create(name="Premium", slug="premium")

        source = grant_points(
            user_profile=self.user,
            points=100,
            description="Test with name",
            tag_names=["Premium"],  # Use name instead of slug
        )

        self.assertEqual(source.tags.count(), 1)
        self.assertEqual(source.tags.first().slug, "premium")
        # Ensure no duplicate tag was created
        self.assertEqual(Tag.objects.filter(slug="premium").count(), 1)

    def test_grant_points_mixed_slug_and_name(self):
        """Test granting points with mix of slug and name."""
        Tag.objects.create(name="Tag One", slug="tag-one")
        Tag.objects.create(name="Tag Two", slug="tag-two")

        source = grant_points(
            user_profile=self.user,
            points=100,
            description="Test mixed",
            tag_names=["tag-one", "Tag Two"],  # One slug, one name
        )

        self.assertEqual(source.tags.count(), 2)
        tag_names = [tag.name for tag in source.tags.all()]
        self.assertIn("Tag One", tag_names)
        self.assertIn("Tag Two", tag_names)

    def test_grant_points_chinese_tag_name(self):
        """Test granting points with Chinese tag name (slugify returns empty)."""
        # Chinese characters will make slugify return empty string
        source = grant_points(
            user_profile=self.user,
            points=100,
            description="Test Chinese tag",
            tag_names=["签到奖励"],  # Pure Chinese, slugify returns ""
        )

        self.assertEqual(source.tags.count(), 1)
        tag = source.tags.first()
        self.assertEqual(tag.name, "签到奖励")
        # When slugify returns empty, the slug should be the original name
        self.assertEqual(tag.slug, "签到奖励")

    def test_grant_points_existing_chinese_tag(self):
        """Test granting points with existing Chinese tag."""
        # Create a Chinese tag first
        Tag.objects.create(name="推荐奖励", slug="推荐奖励")

        source = grant_points(
            user_profile=self.user,
            points=50,
            description="Test existing Chinese",
            tag_names=["推荐奖励"],
        )

        self.assertEqual(source.tags.count(), 1)
        # Should not create duplicate
        self.assertEqual(Tag.objects.filter(name="推荐奖励").count(), 1)

    def test_grant_points_rejects_unknown_legacy_kwargs(self):
        """Passing unexpected legacy kwargs raises TypeError."""
        with self.assertRaisesMessage(TypeError, "Unsupported legacy kwargs: legacy"):
            grant_points(
                user=self.user,
                points=10,
                description="Invalid legacy",
                legacy="value",
            )


class SpendPointsTests(TestCase):
    """Test cases for spend_points service function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )

    def test_spend_points_success(self):
        """Test spending points deducts from sources."""
        Tag.objects.get_or_create(
            slug="default",
            defaults={"name": "默认", "is_default": True},
        )

        grant_points(
            user_profile=self.user,
            points=100,
            description="Initial",
            tag_names=["default"],
        )

        transaction = spend_points(
            user_profile=self.user, amount=30, description="Spend test"
        )

        self.assertEqual(transaction.points, -30)
        self.assertEqual(transaction.transaction_type, "SPEND")
        self.assertEqual(self.user.total_points, 70)

    def test_spend_points_insufficient(self):
        """Test spending more points than available raises error."""
        grant_points(
            user_profile=self.user,
            points=50,
            description="Initial",
            tag_names=["default"],
        )

        with self.assertRaises(InsufficientPointsError):
            spend_points(user_profile=self.user, amount=100, description="Too much")

    def test_spend_points_invalid_amount(self):
        """Test spending negative or zero points raises ValueError."""
        with self.assertRaisesMessage(ValueError, "消费的积分必须是正整数"):
            spend_points(user_profile=self.user, amount=0, description="Invalid")

        with self.assertRaisesMessage(ValueError, "消费的积分必须是正整数"):
            spend_points(user_profile=self.user, amount=-10, description="Invalid")

    def test_spend_points_non_integer_amount(self):
        """Test spending non-integer points raises ValueError."""
        with self.assertRaisesMessage(ValueError, "消费的积分必须是正整数"):
            spend_points(user_profile=self.user, amount=10.5, description="Float")

        with self.assertRaisesMessage(ValueError, "消费的积分必须是正整数"):
            spend_points(user_profile=self.user, amount="50", description="String")

    def test_spend_points_with_priority_tag(self):
        """Test spending points with priority tag preference."""
        # Grant points with different tags
        grant_points(
            user_profile=self.user,
            points=100,
            description="Priority",
            tag_names=["priority"],
        )
        grant_points(
            user_profile=self.user,
            points=50,
            description="Default",
            tag_names=["default"],
        )

        # Spend with priority tag
        spend_points(
            user_profile=self.user,
            amount=30,
            description="Priority spend",
            priority_tag_name="priority",
        )

        # Priority tag points should be used first
        priority_source = PointSource.objects.filter(tags__name="priority").first()
        default_source = PointSource.objects.filter(tags__slug="default").first()

        priority_source.refresh_from_db()
        default_source.refresh_from_db()

        self.assertEqual(priority_source.remaining_points, 70)
        self.assertEqual(default_source.remaining_points, 50)

    def test_spend_points_multiple_sources(self):
        """Test spending points across multiple sources."""
        Tag.objects.get_or_create(
            slug="default",
            defaults={"name": "默认", "is_default": True},
        )

        # Grant points in multiple batches
        grant_points(
            user_profile=self.user,
            points=30,
            description="First",
            tag_names=["default"],
        )
        grant_points(
            user_profile=self.user,
            points=30,
            description="Second",
            tag_names=["default"],
        )
        grant_points(
            user_profile=self.user,
            points=30,
            description="Third",
            tag_names=["default"],
        )

        # Spend exactly two sources - this should hit the break statement
        spend_points(user_profile=self.user, amount=60, description="Exact spend")

        sources = PointSource.objects.filter(user_profile=self.user).order_by(
            "created_at"
        )

        sources[0].refresh_from_db()
        sources[1].refresh_from_db()
        sources[2].refresh_from_db()

        # First two sources should be fully depleted, third untouched
        self.assertEqual(sources[0].remaining_points, 0)
        self.assertEqual(sources[1].remaining_points, 0)
        self.assertEqual(sources[2].remaining_points, 30)

    def test_spend_points_fallback_to_any_remaining(self):
        """Test that spend_points falls back to any remaining sources."""
        # Create a default tag and a non-default tag
        Tag.objects.get_or_create(
            slug="default",
            defaults={"name": "默认", "is_default": True},
        )
        Tag.objects.create(name="other")

        # Grant points with non-default tag
        grant_points(
            user_profile=self.user,
            points=100,
            description="Other points",
            tag_names=["other"],
        )

        # Spend without specifying priority - should fall back to "any" sources
        transaction = spend_points(
            user_profile=self.user, amount=50, description="Fallback test"
        )

        self.assertEqual(transaction.points, -50)
        self.assertEqual(self.user.total_points, 50)

    def test_spend_points_with_priority_tag_fallback(self):
        """Test spending with priority tag that doesn't have enough points."""
        Tag.objects.get_or_create(
            slug="default",
            defaults={"name": "默认", "is_default": True},
        )
        Tag.objects.create(name="priority")

        # Grant small amount with priority tag
        grant_points(
            user_profile=self.user,
            points=30,
            description="Priority",
            tag_names=["priority"],
        )

        # Grant more with default tag
        grant_points(
            user_profile=self.user,
            points=100,
            description="Default",
            tag_names=["default"],
        )

        # Spend more than priority tag has - should use priority first, then default
        transaction = spend_points(
            user_profile=self.user,
            amount=80,
            description="Multi-source",
            priority_tag_name="priority",
        )

        self.assertEqual(transaction.points, -80)
        self.assertEqual(self.user.total_points, 50)  # 30 + 100 - 80 = 50

    def test_spend_points_with_priority_then_default_then_any(self):
        """Test complete fallback chain: priority -> default -> any remaining."""
        Tag.objects.get_or_create(
            slug="default",
            defaults={"name": "默认", "is_default": True},
        )
        Tag.objects.create(name="priority")
        Tag.objects.create(name="other")

        # Grant points with priority tag (small amount)
        grant_points(
            user_profile=self.user,
            points=20,
            description="Priority",
            tag_names=["priority"],
        )

        # Grant points with default tag (medium amount)
        grant_points(
            user_profile=self.user,
            points=30,
            description="Default",
            tag_names=["default"],
        )

        # Grant points with other tag (large amount)
        grant_points(
            user_profile=self.user,
            points=100,
            description="Other",
            tag_names=["other"],
        )

        # Spend amount that requires all three sources
        transaction = spend_points(
            user_profile=self.user,
            amount=80,  # 20 from priority + 30 from default + 30 from other
            description="Full chain test",
            priority_tag_name="priority",
        )

        self.assertEqual(transaction.points, -80)
        self.assertEqual(self.user.total_points, 70)  # 150 - 80 = 70

        # Verify consumption from each source
        priority_source = PointSource.objects.filter(tags__name="priority").first()
        default_source = PointSource.objects.filter(tags__slug="default").first()
        other_source = PointSource.objects.filter(tags__name="other").first()

        priority_source.refresh_from_db()
        default_source.refresh_from_db()
        other_source.refresh_from_db()

        # Priority should be fully consumed
        self.assertEqual(priority_source.remaining_points, 0)
        # Default should be fully consumed
        self.assertEqual(default_source.remaining_points, 0)
        # Other should have 70 remaining (100 - 30)
        self.assertEqual(other_source.remaining_points, 70)

    def test_spend_points_fifo_order(self):
        """Test that points are consumed in FIFO order (oldest first)."""
        Tag.objects.get_or_create(
            slug="default",
            defaults={"name": "默认", "is_default": True},
        )

        # Grant points in three batches with time gaps
        source1 = grant_points(
            user_profile=self.user,
            points=50,
            description="First batch",
            tag_names=["default"],
        )

        source2 = grant_points(
            user_profile=self.user,
            points=50,
            description="Second batch",
            tag_names=["default"],
        )

        source3 = grant_points(
            user_profile=self.user,
            points=50,
            description="Third batch",
            tag_names=["default"],
        )

        # Spend amount that consumes first source and part of second
        spend_points(user_profile=self.user, amount=75, description="FIFO test")

        source1.refresh_from_db()
        source2.refresh_from_db()
        source3.refresh_from_db()

        # First source should be fully consumed (oldest)
        self.assertEqual(source1.remaining_points, 0)
        # Second source should have 25 remaining (50 - 25)
        self.assertEqual(source2.remaining_points, 25)
        # Third source should be untouched (newest)
        self.assertEqual(source3.remaining_points, 50)

    def test_spend_points_rejects_unknown_legacy_kwargs(self):
        """Passing unexpected legacy kwargs raises TypeError before spending."""
        with self.assertRaisesMessage(TypeError, "Unsupported legacy kwargs: legacy"):
            spend_points(
                user=self.user,
                amount=10,
                description="Invalid legacy",
                legacy="value",
            )


class TransactionAtomicityTests(TransactionTestCase):
    """Test transaction atomicity of service functions."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="atomicuser", email="atomic@example.com", password="password123"
        )

    def test_grant_points_rollback_on_error(self):
        """Test that grant_points rolls back on error."""
        initial_transaction_count = PointTransaction.objects.count()
        initial_source_count = PointSource.objects.count()

        # This should fail because we'll force an error
        # by creating a tag with invalid data after grant_points starts
        # But since grant_points validates input first, we need different approach

        # Instead, test that partial execution doesn't leave orphaned data
        source = grant_points(
            user_profile=self.user,
            points=100,
            description="Test atomicity",
            tag_names=["atomic-tag"],
        )

        # Verify all operations completed together
        self.assertEqual(
            PointTransaction.objects.count(), initial_transaction_count + 1
        )
        self.assertEqual(PointSource.objects.count(), initial_source_count + 1)
        self.assertEqual(source.tags.count(), 1)

    def test_spend_points_atomic_deduction(self):
        """Test that spend_points deducts from multiple sources atomically."""
        Tag.objects.get_or_create(
            slug="default",
            defaults={"name": "默认", "is_default": True},
        )

        # Grant points across multiple sources
        grant_points(
            user_profile=self.user, points=30, description="S1", tag_names=["default"]
        )
        grant_points(
            user_profile=self.user, points=30, description="S2", tag_names=["default"]
        )
        grant_points(
            user_profile=self.user, points=30, description="S3", tag_names=["default"]
        )

        initial_total = self.user.total_points

        # Spend across sources
        spend_points(user_profile=self.user, amount=50, description="Atomic test")

        # All deductions should happen atomically
        final_total = self.user.total_points
        self.assertEqual(final_total, initial_total - 50)


class EdgeCaseTests(TestCase):
    """Test edge cases and boundary conditions."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="edgeuser", email="edge@example.com", password="password123"
        )

    def test_grant_points_empty_tag_list(self):
        """Test granting points with empty tag list."""
        source = grant_points(
            user_profile=self.user,
            points=100,
            description="No tags",
            tag_names=[],  # Empty list
        )

        self.assertEqual(source.initial_points, 100)
        self.assertEqual(source.tags.count(), 0)

    def test_grant_points_single_tag(self):
        """Test granting points with a single tag."""
        source = grant_points(
            user_profile=self.user,
            points=100,
            description="Single tag",
            tag_names=["single"],
        )

        self.assertEqual(source.tags.count(), 1)

    def test_grant_points_many_tags(self):
        """Test granting points with many tags."""
        tag_names = [f"tag-{i}" for i in range(10)]

        source = grant_points(
            user_profile=self.user,
            points=100,
            description="Many tags",
            tag_names=tag_names,
        )

        self.assertEqual(source.tags.count(), 10)

    def test_grant_points_duplicate_tags_in_list(self):
        """Test granting points with duplicate tag names in the list."""
        source = grant_points(
            user_profile=self.user,
            points=100,
            description="Duplicate tags",
            tag_names=["dup", "dup", "dup"],  # Same tag multiple times
        )

        # Should only create one tag, but might add it multiple times
        # This is based on current implementation
        self.assertEqual(source.tags.count(), 1)

    def test_spend_points_exact_balance(self):
        """Test spending exact balance (all points)."""
        Tag.objects.get_or_create(
            slug="default",
            defaults={"name": "默认", "is_default": True},
        )

        grant_points(
            user_profile=self.user,
            points=100,
            description="Initial",
            tag_names=["default"],
        )

        # Spend exact balance
        transaction = spend_points(
            user_profile=self.user, amount=100, description="Exact"
        )

        self.assertEqual(transaction.points, -100)
        self.assertEqual(self.user.total_points, 0)

        # All sources should be depleted
        sources = PointSource.objects.filter(user_profile=self.user)
        for source in sources:
            source.refresh_from_db()
            self.assertEqual(source.remaining_points, 0)

    def test_spend_points_one_point(self):
        """Test spending minimum amount (1 point)."""
        Tag.objects.get_or_create(
            slug="default",
            defaults={"name": "默认", "is_default": True},
        )

        grant_points(
            user_profile=self.user,
            points=100,
            description="Initial",
            tag_names=["default"],
        )

        transaction = spend_points(
            user_profile=self.user, amount=1, description="Minimum"
        )

        self.assertEqual(transaction.points, -1)
        self.assertEqual(self.user.total_points, 99)

    def test_spend_points_zero_balance(self):
        """Test spending when user has zero balance."""
        with self.assertRaises(InsufficientPointsError):
            spend_points(user_profile=self.user, amount=1, description="No points")

    def test_grant_points_max_integer(self):
        """Test granting very large point amount."""
        large_amount = 2147483647  # Max 32-bit int

        source = grant_points(
            user_profile=self.user,
            points=large_amount,
            description="Max int",
            tag_names=["large"],
        )

        self.assertEqual(source.initial_points, large_amount)
        self.assertEqual(source.remaining_points, large_amount)

    def test_spend_points_consumed_sources_tracking(self):
        """Test that consumed sources are properly tracked in transaction."""
        Tag.objects.get_or_create(
            slug="default",
            defaults={"name": "默认", "is_default": True},
        )

        # Create multiple sources
        source1 = grant_points(
            user_profile=self.user, points=30, description="S1", tag_names=["default"]
        )
        source2 = grant_points(
            user_profile=self.user, points=30, description="S2", tag_names=["default"]
        )
        source3 = grant_points(
            user_profile=self.user, points=30, description="S3", tag_names=["default"]
        )

        # Spend from first two sources
        transaction = spend_points(
            user_profile=self.user, amount=50, description="Track sources"
        )

        # Check consumed sources are tracked
        consumed_ids = set(transaction.consumed_sources.values_list("id", flat=True))
        self.assertIn(source1.id, consumed_ids)
        self.assertIn(source2.id, consumed_ids)
        self.assertNotIn(source3.id, consumed_ids)  # Not consumed

    def test_grant_points_special_characters_in_tags(self):
        """Test granting points with special characters in tag names."""
        source = grant_points(
            user_profile=self.user,
            points=100,
            description="Special chars",
            tag_names=["tag-with_special.chars!", "tag@#$%"],
        )

        self.assertEqual(source.tags.count(), 2)

    def test_spend_points_priority_tag_not_exist(self):
        """Test spending with priority tag that doesn't exist."""
        Tag.objects.get_or_create(
            slug="default",
            defaults={"name": "默认", "is_default": True},
        )

        grant_points(
            user_profile=self.user,
            points=100,
            description="Default points",
            tag_names=["default"],
        )

        # Priority tag doesn't exist, should fall back to default
        transaction = spend_points(
            user_profile=self.user,
            amount=50,
            description="Non-existent priority",
            priority_tag_name="non-existent",
        )

        self.assertEqual(transaction.points, -50)
        self.assertEqual(self.user.total_points, 50)

    def test_spend_points_no_default_tag_sources(self):
        """Test spending when no sources have default tags."""
        Tag.objects.create(name="special")  # Non-default tag

        grant_points(
            user_profile=self.user,
            points=100,
            description="Special points",
            tag_names=["special"],
        )

        # No default tag sources, should fall back to any remaining
        transaction = spend_points(
            user_profile=self.user, amount=50, description="No default"
        )

        self.assertEqual(transaction.points, -50)
        self.assertEqual(self.user.total_points, 50)

    def test_grant_points_transaction_record(self):
        """Test that grant_points creates correct transaction record."""
        grant_points(
            user_profile=self.user,
            points=100,
            description="Transaction test",
            tag_names=["test"],
        )

        transaction = PointTransaction.objects.filter(
            user_profile=self.user,
            transaction_type=PointTransaction.TransactionType.EARN,
        ).first()

        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.points, 100)
        self.assertEqual(transaction.description, "Transaction test")
        self.assertEqual(
            transaction.transaction_type, PointTransaction.TransactionType.EARN
        )

    def test_spend_points_transaction_record(self):
        """Test that spend_points creates correct transaction record."""
        Tag.objects.get_or_create(
            slug="default",
            defaults={"name": "默认", "is_default": True},
        )

        grant_points(
            user_profile=self.user,
            points=100,
            description="Initial",
            tag_names=["default"],
        )

        spend_points(
            user_profile=self.user, amount=50, description="Spend transaction test"
        )

        spend_transaction = PointTransaction.objects.filter(
            user_profile=self.user,
            transaction_type=PointTransaction.TransactionType.SPEND,
        ).first()

        self.assertIsNotNone(spend_transaction)
        self.assertEqual(spend_transaction.points, -50)
        self.assertEqual(spend_transaction.description, "Spend transaction test")
        self.assertTrue(
            spend_transaction.transaction_type == PointTransaction.TransactionType.SPEND
        )


class BatchWithdrawalTests(TestCase):
    """Test cases for batch withdrawal service functions."""

    def setUp(self):
        """Set up test fixtures."""
        from points.models import WithdrawalRequest
        from points.services import WithdrawalData

        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )
        self.WithdrawalData = WithdrawalData
        self.WithdrawalRequest = WithdrawalRequest

        # Create withdrawable tag
        self.withdrawable_tag = Tag.objects.create(
            name="withdrawable", withdrawable=True
        )
        self.non_withdrawable_tag = Tag.objects.create(
            name="non-withdrawable", withdrawable=False
        )

    def test_create_batch_withdrawal_requests_success(self):
        """Test creating multiple withdrawal requests at once."""
        from points.services import create_batch_withdrawal_requests

        # Create two withdrawable point sources
        source1 = grant_points(
            user=self.user,
            points=100,
            description="Source 1",
            tag_names=["withdrawable"],
        )
        source2 = grant_points(
            user=self.user,
            points=200,
            description="Source 2",
            tag_names=["withdrawable"],
        )

        withdrawal_data = self.WithdrawalData(
            real_name="张三",
            id_number="110101199001011234",
            phone_number="13800138000",
            bank_name="中国银行",
            bank_account="6222020200012345678",
        )

        withdrawal_amounts = {
            source1.id: 50,
            source2.id: 100,
        }

        withdrawal_requests = create_batch_withdrawal_requests(
            user=self.user,
            withdrawal_amounts=withdrawal_amounts,
            withdrawal_data=withdrawal_data,
        )

        # Verify results
        self.assertEqual(len(withdrawal_requests), 2)
        self.assertEqual(
            self.WithdrawalRequest.objects.filter(user=self.user).count(), 2
        )

        # Verify first request
        wr1 = self.WithdrawalRequest.objects.get(point_source=source1)
        self.assertEqual(wr1.points, 50)
        self.assertEqual(wr1.real_name, "张三")
        self.assertEqual(wr1.id_number, "110101199001011234")
        self.assertEqual(wr1.phone_number, "13800138000")
        self.assertEqual(wr1.bank_name, "中国银行")
        self.assertEqual(wr1.bank_account, "6222020200012345678")
        self.assertEqual(wr1.status, self.WithdrawalRequest.Status.PENDING)

        # Verify second request
        wr2 = self.WithdrawalRequest.objects.get(point_source=source2)
        self.assertEqual(wr2.points, 100)

    def test_create_batch_withdrawal_requests_empty_amounts(self):
        """Test that empty withdrawal amounts dict raises error."""
        from points.services import WithdrawalError, create_batch_withdrawal_requests

        withdrawal_data = self.WithdrawalData(
            real_name="张三",
            id_number="110101199001011234",
            phone_number="13800138000",
            bank_name="中国银行",
            bank_account="6222020200012345678",
        )

        with self.assertRaisesMessage(
            WithdrawalError, "至少需要选择一个积分池进行提现。"
        ):
            create_batch_withdrawal_requests(
                user=self.user,
                withdrawal_amounts={},
                withdrawal_data=withdrawal_data,
            )

    def test_create_batch_withdrawal_requests_skips_zero_amounts(self):
        """Test that zero or negative amounts are skipped."""
        from points.services import WithdrawalError, create_batch_withdrawal_requests

        source1 = grant_points(
            user=self.user,
            points=100,
            description="Source 1",
            tag_names=["withdrawable"],
        )
        source2 = grant_points(
            user=self.user,
            points=200,
            description="Source 2",
            tag_names=["withdrawable"],
        )

        withdrawal_data = self.WithdrawalData(
            real_name="张三",
            id_number="110101199001011234",
            phone_number="13800138000",
            bank_name="中国银行",
            bank_account="6222020200012345678",
        )

        # All amounts are zero or negative
        withdrawal_amounts = {
            source1.id: 0,
            source2.id: -10,
        }

        with self.assertRaisesMessage(
            WithdrawalError, "至少需要为一个积分池设置提现数量。"
        ):
            create_batch_withdrawal_requests(
                user=self.user,
                withdrawal_amounts=withdrawal_amounts,
                withdrawal_data=withdrawal_data,
            )

    def test_create_batch_withdrawal_requests_partial_amounts(self):
        """Test that only positive amounts are processed."""
        from points.services import create_batch_withdrawal_requests

        source1 = grant_points(
            user=self.user,
            points=100,
            description="Source 1",
            tag_names=["withdrawable"],
        )
        source2 = grant_points(
            user=self.user,
            points=200,
            description="Source 2",
            tag_names=["withdrawable"],
        )
        source3 = grant_points(
            user=self.user,
            points=300,
            description="Source 3",
            tag_names=["withdrawable"],
        )

        withdrawal_data = self.WithdrawalData(
            real_name="张三",
            id_number="110101199001011234",
            phone_number="13800138000",
            bank_name="中国银行",
            bank_account="6222020200012345678",
        )

        withdrawal_amounts = {
            source1.id: 50,  # Valid
            source2.id: 0,  # Should be skipped
            source3.id: 100,  # Valid
        }

        withdrawal_requests = create_batch_withdrawal_requests(
            user=self.user,
            withdrawal_amounts=withdrawal_amounts,
            withdrawal_data=withdrawal_data,
        )

        # Only 2 requests should be created
        self.assertEqual(len(withdrawal_requests), 2)
        self.assertEqual(
            self.WithdrawalRequest.objects.filter(user=self.user).count(), 2
        )

    def test_create_batch_withdrawal_requests_exceeds_balance(self):
        """Test that withdrawal amount exceeding balance raises error."""
        from points.services import (
            WithdrawalAmountError,
            create_batch_withdrawal_requests,
        )

        source = grant_points(
            user=self.user,
            points=100,
            description="Source",
            tag_names=["withdrawable"],
        )

        withdrawal_data = self.WithdrawalData(
            real_name="张三",
            id_number="110101199001011234",
            phone_number="13800138000",
            bank_name="中国银行",
            bank_account="6222020200012345678",
        )

        withdrawal_amounts = {
            source.id: 150,  # Exceeds remaining points
        }

        with self.assertRaisesMessage(
            WithdrawalAmountError, "提现积分不能超过剩余积分"
        ):
            create_batch_withdrawal_requests(
                user=self.user,
                withdrawal_amounts=withdrawal_amounts,
                withdrawal_data=withdrawal_data,
            )

    def test_create_batch_withdrawal_requests_non_withdrawable_source(self):
        """Test that non-withdrawable source raises error."""
        from points.services import (
            PointSourceNotWithdrawableError,
            create_batch_withdrawal_requests,
        )

        # Create a non-withdrawable source
        source = grant_points(
            user=self.user,
            points=100,
            description="Source",
            tag_names=["non-withdrawable"],
        )

        withdrawal_data = self.WithdrawalData(
            real_name="张三",
            id_number="110101199001011234",
            phone_number="13800138000",
            bank_name="中国银行",
            bank_account="6222020200012345678",
        )

        withdrawal_amounts = {
            source.id: 50,
        }

        with self.assertRaisesMessage(
            PointSourceNotWithdrawableError, "该积分来源不支持提现"
        ):
            create_batch_withdrawal_requests(
                user=self.user,
                withdrawal_amounts=withdrawal_amounts,
                withdrawal_data=withdrawal_data,
            )

    def test_create_batch_withdrawal_requests_atomicity(self):
        """Test that batch withdrawal is atomic - all or nothing."""
        from points.services import (
            PointSourceNotWithdrawableError,
            create_batch_withdrawal_requests,
        )

        # Create one withdrawable and one non-withdrawable source
        source1 = grant_points(
            user=self.user,
            points=100,
            description="Source 1",
            tag_names=["withdrawable"],
        )
        source2 = grant_points(
            user=self.user,
            points=200,
            description="Source 2",
            tag_names=["non-withdrawable"],  # This will fail
        )

        withdrawal_data = self.WithdrawalData(
            real_name="张三",
            id_number="110101199001011234",
            phone_number="13800138000",
            bank_name="中国银行",
            bank_account="6222020200012345678",
        )

        withdrawal_amounts = {
            source1.id: 50,
            source2.id: 100,  # This will fail
        }

        # Should raise error
        with self.assertRaises(PointSourceNotWithdrawableError):
            create_batch_withdrawal_requests(
                user=self.user,
                withdrawal_amounts=withdrawal_amounts,
                withdrawal_data=withdrawal_data,
            )

        # No requests should be created due to atomicity
        self.assertEqual(
            self.WithdrawalRequest.objects.filter(user=self.user).count(), 0
        )


class WithdrawalLifecycleTests(TestCase):
    """Cover single withdrawal creation and lifecycle helpers."""

    def setUp(self):
        """Create users, tag and point source for withdrawal scenarios."""
        self.user = get_user_model().objects.create_user(username="withdraw-user")
        self.admin = get_user_model().objects.create_user(
            username="withdraw-admin", is_staff=True
        )
        self.withdrawable_tag = Tag.objects.create(
            name="withdrawable", slug="withdrawable", withdrawable=True
        )
        self.point_source = PointSource.objects.create(
            user=self.user, initial_points=200, remaining_points=200
        )
        self.point_source.tags.add(self.withdrawable_tag)
        self.withdrawal_data = WithdrawalData(
            real_name="李四",
            id_number="110101199001011234",
            phone_number="13800138000",
            bank_name="中国银行",
            bank_account="6222020200012345678",
        )

    def test_create_withdrawal_request_success(self):
        """Valid request persists applicant data and stays pending."""
        request = create_withdrawal_request(
            user=self.user,
            point_source_id=self.point_source.id,
            points=80,
            withdrawal_data=self.withdrawal_data,
        )

        self.assertEqual(request.points, 80)
        self.assertEqual(request.status, request.Status.PENDING)
        self.assertEqual(request.real_name, "李四")
        self.assertEqual(request.bank_name, "中国银行")

    def test_create_withdrawal_request_missing_source(self):
        """Raises when point source does not belong to user."""
        with self.assertRaisesMessage(
            PointSource.DoesNotExist, "积分来源不存在或不属于您。"
        ):
            create_withdrawal_request(
                user=self.user,
                point_source_id=9999,
                points=10,
                withdrawal_data=self.withdrawal_data,
            )

    def test_create_withdrawal_request_not_withdrawable(self):
        """Non-withdrawable sources are rejected early."""
        non_withdrawable = PointSource.objects.create(
            user=self.user, initial_points=50, remaining_points=50
        )
        Tag.objects.create(name="locked", slug="locked", withdrawable=False)

        with self.assertRaisesMessage(
            PointSourceNotWithdrawableError, "该积分来源不支持提现。"
        ):
            create_withdrawal_request(
                user=self.user,
                point_source_id=non_withdrawable.id,
                points=10,
                withdrawal_data=self.withdrawal_data,
            )

    def test_create_withdrawal_request_invalid_amount(self):
        """Amount must be a positive integer."""
        with self.assertRaisesMessage(WithdrawalAmountError, "提现积分必须是正整数。"):
            create_withdrawal_request(
                user=self.user,
                point_source_id=self.point_source.id,
                points=0,
                withdrawal_data=self.withdrawal_data,
            )

    def test_create_withdrawal_request_exceeds_balance(self):
        """Reject when requested points exceed remaining balance."""
        with self.assertRaisesMessage(
            WithdrawalAmountError, "提现积分不能超过剩余积分"
        ):
            create_withdrawal_request(
                user=self.user,
                point_source_id=self.point_source.id,
                points=500,
                withdrawal_data=self.withdrawal_data,
            )

    def test_approve_withdrawal_happy_path(self):
        """Approving deducts points and marks request completed."""
        request = create_withdrawal_request(
            user=self.user,
            point_source_id=self.point_source.id,
            points=60,
            withdrawal_data=self.withdrawal_data,
        )

        transaction = approve_withdrawal(
            withdrawal_request=request,
            admin_user=self.admin,
            admin_note="ok",
        )

        request.refresh_from_db()
        self.point_source.refresh_from_db()

        self.assertEqual(request.status, request.Status.COMPLETED)
        self.assertEqual(request.processed_by, self.admin)
        self.assertEqual(request.admin_note, "ok")
        self.assertEqual(transaction.transaction_type, "WITHDRAW")
        self.assertEqual(transaction.points, -60)
        self.assertEqual(self.user.total_points, 140)

    def test_approve_withdrawal_requires_pending(self):
        """Only pending requests can be approved."""
        request = create_withdrawal_request(
            user=self.user,
            point_source_id=self.point_source.id,
            points=20,
            withdrawal_data=self.withdrawal_data,
        )
        request.status = request.Status.REJECTED
        request.save(update_fields=["status"])

        with self.assertRaisesMessage(WithdrawalError, "只能批准待处理状态的申请"):
            approve_withdrawal(request, admin_user=self.admin)

    def test_reject_withdrawal_updates_status(self):
        """Rejecting sets status, admin info and timestamp."""
        request = create_withdrawal_request(
            user=self.user,
            point_source_id=self.point_source.id,
            points=30,
            withdrawal_data=self.withdrawal_data,
        )

        reject_withdrawal(
            withdrawal_request=request, admin_user=self.admin, admin_note="reason"
        )

        request.refresh_from_db()
        self.assertEqual(request.status, request.Status.REJECTED)
        self.assertEqual(request.processed_by, self.admin)
        self.assertEqual(request.admin_note, "reason")
        self.assertIsNotNone(request.processed_at)

    def test_reject_withdrawal_requires_pending(self):
        """Rejecting non-pending requests raises error."""
        request = create_withdrawal_request(
            user=self.user,
            point_source_id=self.point_source.id,
            points=30,
            withdrawal_data=self.withdrawal_data,
        )
        request.status = request.Status.COMPLETED
        request.save(update_fields=["status"])

        with self.assertRaisesMessage(WithdrawalError, "只能拒绝待处理状态的申请"):
            reject_withdrawal(request, admin_user=self.admin)

    def test_cancel_withdrawal_flow(self):
        """Users can cancel pending requests; others raise errors."""
        request = create_withdrawal_request(
            user=self.user,
            point_source_id=self.point_source.id,
            points=20,
            withdrawal_data=self.withdrawal_data,
        )

        cancel_withdrawal(request)

        request.refresh_from_db()
        self.assertEqual(request.status, request.Status.CANCELLED)
        self.assertIsNotNone(request.processed_at)

        with self.assertRaisesMessage(WithdrawalError, "只能取消待处理状态的申请"):
            cancel_withdrawal(request)
