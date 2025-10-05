"""Tests for the points app."""

from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from .models import PointSource, PointTransaction, Tag
from .services import InsufficientPointsError, grant_points, spend_points


class TagModelTests(TestCase):
    """Test cases for Tag model."""

    def test_tag_str(self):
        """Test string representation of Tag."""
        tag = Tag.objects.create(name="test-tag", description="Test description")

        assert str(tag) == "test-tag"

    def test_tag_unique_name(self):
        """Test that tag names must be unique."""
        Tag.objects.create(name="unique-tag")

        with pytest.raises(IntegrityError):
            Tag.objects.create(name="unique-tag")

    def test_tag_auto_generates_slug(self):
        """Test that Tag automatically generates slug on save."""
        tag = Tag.objects.create(name="Test Tag")

        assert tag.slug == "test-tag"

    def test_tag_slug_for_chinese(self):
        """Test that Chinese names fallback to name for slug."""
        tag = Tag.objects.create(name="测试标签")

        assert tag.slug == "测试标签"

    def test_tag_unique_slug(self):
        """Test that tag slugs must be unique."""
        Tag.objects.create(name="tag-one", slug="unique-slug")

        with pytest.raises(IntegrityError):
            Tag.objects.create(name="tag-two", slug="unique-slug")

    def test_tag_custom_slug(self):
        """Test creating tag with custom slug."""
        tag = Tag.objects.create(name="Custom Tag", slug="my-custom-slug")

        assert tag.slug == "my-custom-slug"


class PointSourceModelTests(TestCase):
    """Test cases for PointSource model."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )
        self.tag = Tag.objects.create(name="test-tag")

    def test_point_source_creation(self):
        """Test creating a point source."""
        source = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=100
        )
        source.tags.add(self.tag)

        assert source.initial_points == 100
        assert source.remaining_points == 100
        assert source.tags.count() == 1

    def test_point_source_ordering(self):
        """Test that point sources are ordered by created_at."""
        source1 = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=100
        )
        source2 = PointSource.objects.create(
            user_profile=self.user, initial_points=50, remaining_points=50
        )

        sources = PointSource.objects.all()

        assert sources[0] == source1
        assert sources[1] == source2


class PointTransactionModelTests(TestCase):
    """Test cases for PointTransaction model."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )

    def test_transaction_creation(self):
        """Test creating a transaction."""
        transaction = PointTransaction.objects.create(
            user_profile=self.user,
            points=100,
            transaction_type=PointTransaction.TransactionType.EARN,
            description="Test earn",
        )

        assert transaction.points == 100
        assert transaction.transaction_type == "EARN"
        assert transaction.description == "Test earn"

    def test_transaction_ordering(self):
        """Test that transactions are ordered by created_at desc."""
        trans1 = PointTransaction.objects.create(
            user_profile=self.user,
            points=100,
            transaction_type=PointTransaction.TransactionType.EARN,
            description="First",
        )
        trans2 = PointTransaction.objects.create(
            user_profile=self.user,
            points=50,
            transaction_type=PointTransaction.TransactionType.EARN,
            description="Second",
        )

        transactions = PointTransaction.objects.all()

        assert transactions[0] == trans2
        assert transactions[1] == trans1


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


class MyPointsViewTests(TestCase):
    """Test cases for my_points view."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )
        self.url = reverse("points:my_points")

    def test_view_requires_login(self):
        """Test that view requires authentication."""
        response = self.client.get(self.url)

        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_view_displays_points(self):
        """Test that view displays user's points correctly."""
        self.client.login(username="testuser", password="password123")

        grant_points(
            user_profile=self.user,
            points=100,
            description="Test",
            tag_names=["tag1"],
        )

        response = self.client.get(self.url)

        assert response.status_code == 200
        assert "total_points" in response.context
        assert response.context["total_points"] == 100
        assert "points_by_tag" in response.context
        assert len(response.context["points_by_tag"]) == 1

    def test_view_displays_transactions(self):
        """Test that view displays transaction history."""
        self.client.login(username="testuser", password="password123")

        grant_points(
            user_profile=self.user,
            points=100,
            description="Test grant",
            tag_names=["tag1"],
        )
        spend_points(user_profile=self.user, amount=30, description="Test spend")

        response = self.client.get(self.url)

        assert response.status_code == 200
        assert "page_obj" in response.context
        assert len(response.context["page_obj"]) == 2

    def test_view_pagination(self):
        """Test that view paginates transactions."""
        self.client.login(username="testuser", password="password123")

        # Create 25 transactions
        for i in range(25):
            grant_points(
                user_profile=self.user,
                points=10,
                description=f"Test {i}",
                tag_names=["tag1"],
            )

        response = self.client.get(self.url)

        assert response.status_code == 200
        assert len(response.context["page_obj"]) == 20

        response = self.client.get(f"{self.url}?page=2")

        assert response.status_code == 200
        assert len(response.context["page_obj"]) == 5

    def test_view_with_no_points(self):
        """Test that view works when user has no points."""
        self.client.login(username="testuser", password="password123")

        response = self.client.get(self.url)

        assert response.status_code == 200
        assert response.context["total_points"] == 0
        assert len(response.context["points_by_tag"]) == 0


class URLTests(TestCase):
    """Test URL configuration."""

    def test_my_points_url_resolves(self):
        """Test that my_points URL resolves correctly."""
        url = reverse("points:my_points")

        assert url == "/accounts/points/"


class GrantPointsCommandTests(TestCase):
    """Test cases for grant_points management command."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )

    def test_command_grants_points_by_username(self):
        """Test granting points using username."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            stdout=out,
        )

        assert "Successfully granted 100 points to testuser" in out.getvalue()
        assert self.user.total_points == 100

    def test_command_grants_points_by_email(self):
        """Test granting points using email."""
        out = StringIO()
        call_command(
            "grant_points",
            "test@example.com",
            "50",
            stdout=out,
        )

        assert "Successfully granted 50 points to testuser" in out.getvalue()
        assert self.user.total_points == 50

    def test_command_with_tag_name(self):
        """Test granting points with tag name."""
        Tag.objects.create(name="Premium", slug="premium")

        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--tags=Premium",
            stdout=out,
        )

        assert self.user.total_points == 100
        source = PointSource.objects.first()
        assert source.tags.filter(name="Premium").exists()
        # Ensure no duplicate tag was created
        assert Tag.objects.filter(name="Premium").count() == 1

    def test_command_with_tag_slug(self):
        """Test granting points with tag slug."""
        Tag.objects.create(name="Premium", slug="premium")

        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--tags=premium",
            stdout=out,
        )

        assert self.user.total_points == 100
        source = PointSource.objects.first()
        assert source.tags.filter(slug="premium").exists()
        # Ensure no duplicate tag was created
        assert Tag.objects.filter(slug="premium").count() == 1

    def test_command_with_multiple_tags(self):
        """Test granting points with multiple tags (mix of name and slug)."""
        Tag.objects.create(name="Tag One", slug="tag-one")
        Tag.objects.create(name="Tag Two", slug="tag-two")

        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--tags=tag-one,Tag Two",
            stdout=out,
        )

        assert self.user.total_points == 100
        source = PointSource.objects.first()
        assert source.tags.count() == 2

    def test_command_with_description(self):
        """Test granting points with custom description."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--description=Custom description",
            stdout=out,
        )

        transaction = PointTransaction.objects.first()
        assert transaction.description == "Custom description"

    def test_command_user_not_found(self):
        """Test granting points to non-existent user."""
        from django.core.management.base import CommandError

        with pytest.raises(CommandError, match="User not found"):
            call_command(
                "grant_points",
                "nonexistent",
                "100",
            )

    def test_command_invalid_points(self):
        """Test granting invalid points amount."""
        from django.core.management.base import CommandError

        with pytest.raises(CommandError, match="发放的积分必须是正整数"):
            call_command(
                "grant_points",
                "testuser",
                "0",
            )
