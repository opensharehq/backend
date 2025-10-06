"""Tests for points views."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from points.services import grant_points, spend_points


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
