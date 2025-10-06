"""Tests for points management commands."""

from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from points.models import PointSource, PointTransaction, Tag


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
