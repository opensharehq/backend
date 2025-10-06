"""Tests for points models."""

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from points.models import PointSource, PointTransaction, Tag


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
