"""Tests for points service layer."""

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase

from points.models import PointSource, Tag
from points.services import InsufficientPointsError, grant_points, spend_points


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

        assert source.initial_points == 100
        assert source.remaining_points == 100
        assert source.tags.count() == 2

        assert self.user.point_transactions.count() == 1
        transaction = self.user.point_transactions.first()
        assert transaction.points == 100
        assert transaction.transaction_type == "EARN"

    def test_grant_points_invalid_amount(self):
        """Test granting negative or zero points raises ValueError."""
        with pytest.raises(ValueError, match="发放的积分必须是正整数"):
            grant_points(
                user_profile=self.user,
                points=0,
                description="Invalid",
                tag_names=["tag1"],
            )

        with pytest.raises(ValueError, match="发放的积分必须是正整数"):
            grant_points(
                user_profile=self.user,
                points=-10,
                description="Invalid",
                tag_names=["tag1"],
            )

    def test_grant_points_non_integer_amount(self):
        """Test granting non-integer points raises ValueError."""
        with pytest.raises(ValueError, match="发放的积分必须是正整数"):
            grant_points(
                user_profile=self.user,
                points=10.5,
                description="Float amount",
                tag_names=["tag1"],
            )

        with pytest.raises(ValueError, match="发放的积分必须是正整数"):
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

        assert Tag.objects.filter(name="new-tag").exists()

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

        assert source.tags.count() == 1
        assert source.tags.first().name == "Premium"
        # Ensure no duplicate tag was created
        assert Tag.objects.filter(name="Premium").count() == 1

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

        assert source.tags.count() == 1
        assert source.tags.first().slug == "premium"
        # Ensure no duplicate tag was created
        assert Tag.objects.filter(slug="premium").count() == 1

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

        assert source.tags.count() == 2
        tag_names = [tag.name for tag in source.tags.all()]
        assert "Tag One" in tag_names
        assert "Tag Two" in tag_names


class SpendPointsTests(TestCase):
    """Test cases for spend_points service function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )

    def test_spend_points_success(self):
        """Test spending points deducts from sources."""
        Tag.objects.create(name="default", is_default=True)

        grant_points(
            user_profile=self.user,
            points=100,
            description="Initial",
            tag_names=["default"],
        )

        transaction = spend_points(
            user_profile=self.user, amount=30, description="Spend test"
        )

        assert transaction.points == -30
        assert transaction.transaction_type == "SPEND"
        assert self.user.total_points == 70

    def test_spend_points_insufficient(self):
        """Test spending more points than available raises error."""
        grant_points(
            user_profile=self.user,
            points=50,
            description="Initial",
            tag_names=["default"],
        )

        with pytest.raises(InsufficientPointsError):
            spend_points(user_profile=self.user, amount=100, description="Too much")

    def test_spend_points_invalid_amount(self):
        """Test spending negative or zero points raises ValueError."""
        with pytest.raises(ValueError, match="消费的积分必须是正整数"):
            spend_points(user_profile=self.user, amount=0, description="Invalid")

        with pytest.raises(ValueError, match="消费的积分必须是正整数"):
            spend_points(user_profile=self.user, amount=-10, description="Invalid")

    def test_spend_points_non_integer_amount(self):
        """Test spending non-integer points raises ValueError."""
        with pytest.raises(ValueError, match="消费的积分必须是正整数"):
            spend_points(user_profile=self.user, amount=10.5, description="Float")

        with pytest.raises(ValueError, match="消费的积分必须是正整数"):
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
        default_source = PointSource.objects.filter(tags__name="default").first()

        priority_source.refresh_from_db()
        default_source.refresh_from_db()

        assert priority_source.remaining_points == 70
        assert default_source.remaining_points == 50

    def test_spend_points_multiple_sources(self):
        """Test spending points across multiple sources."""
        Tag.objects.create(name="default", is_default=True)

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
        assert sources[0].remaining_points == 0
        assert sources[1].remaining_points == 0
        assert sources[2].remaining_points == 30

    def test_spend_points_fallback_to_any_remaining(self):
        """Test that spend_points falls back to any remaining sources."""
        # Create a default tag and a non-default tag
        Tag.objects.create(name="default", is_default=True)
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

        assert transaction.points == -50
        assert self.user.total_points == 50

    def test_spend_points_with_priority_tag_fallback(self):
        """Test spending with priority tag that doesn't have enough points."""
        Tag.objects.create(name="default", is_default=True)
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

        assert transaction.points == -80
        assert self.user.total_points == 50  # 30 + 100 - 80 = 50
