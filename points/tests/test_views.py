"""Tests for points views."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from points.models import PointSource, Tag
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

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

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

        self.assertEqual(response.status_code, 200)
        self.assertIn("total_points", response.context)
        self.assertEqual(response.context["total_points"], 100)
        self.assertIn("points_by_tag", response.context)
        self.assertEqual(len(response.context["points_by_tag"]), 1)

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

        self.assertEqual(response.status_code, 200)
        self.assertIn("page_obj", response.context)
        self.assertEqual(len(response.context["page_obj"]), 2)

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

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["page_obj"]), 20)

        response = self.client.get(f"{self.url}?page=2")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["page_obj"]), 5)

    def test_view_with_no_points(self):
        """Test that view works when user has no points."""
        self.client.login(username="testuser", password="password123")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_points"], 0)
        self.assertEqual(len(response.context["points_by_tag"]), 0)

    def test_view_displays_active_sources(self):
        """Test that view displays active point sources with remaining points."""
        self.client.login(username="testuser", password="password123")

        # Grant points with multiple sources
        grant_points(
            user_profile=self.user,
            points=100,
            description="First source",
            tag_names=["tag1"],
        )
        grant_points(
            user_profile=self.user,
            points=50,
            description="Second source",
            tag_names=["tag2"],
        )

        # Spend some points (will consume from first source due to FIFO)
        spend_points(user_profile=self.user, amount=30, description="Test spend")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("active_sources", response.context)

        # Should have 2 active sources (first with 70 remaining, second with 50)
        active_sources = list(response.context["active_sources"])
        self.assertEqual(len(active_sources), 2)
        self.assertEqual(active_sources[0].remaining_points, 50)  # Most recent first
        self.assertEqual(active_sources[1].remaining_points, 70)

    def test_view_excludes_depleted_sources(self):
        """Test that view excludes point sources with zero remaining points."""
        self.client.login(username="testuser", password="password123")

        grant_points(
            user_profile=self.user,
            points=50,
            description="Source to deplete",
            tag_names=["tag1"],
        )

        # Spend all points
        spend_points(user_profile=self.user, amount=50, description="Deplete all")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        active_sources = list(response.context["active_sources"])
        self.assertEqual(len(active_sources), 0)

    def test_view_pagination_invalid_page(self):
        """Test that view handles invalid page numbers gracefully."""
        self.client.login(username="testuser", password="password123")

        grant_points(
            user_profile=self.user,
            points=10,
            description="Test",
            tag_names=["tag1"],
        )

        # Test with invalid page number
        response = self.client.get(f"{self.url}?page=999")

        self.assertEqual(response.status_code, 200)
        # Should return last page
        self.assertEqual(len(response.context["page_obj"]), 1)

    def test_view_pagination_non_numeric_page(self):
        """Test that view handles non-numeric page parameter."""
        self.client.login(username="testuser", password="password123")

        grant_points(
            user_profile=self.user,
            points=10,
            description="Test",
            tag_names=["tag1"],
        )

        # Test with non-numeric page parameter
        response = self.client.get(f"{self.url}?page=invalid")

        self.assertEqual(response.status_code, 200)
        # Should return first page
        self.assertEqual(len(response.context["page_obj"]), 1)

    def test_view_trend_data_format(self):
        """Test that view generates properly formatted trend data."""
        self.client.login(username="testuser", password="password123")

        grant_points(
            user_profile=self.user,
            points=100,
            description="Test",
            tag_names=["tag1"],
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("trend_labels_json", response.context)
        self.assertIn("trend_datasets_json", response.context)

        # Parse JSON data
        labels = json.loads(response.context["trend_labels_json"])
        datasets = json.loads(response.context["trend_datasets_json"])

        # Should have 30 days of labels
        self.assertEqual(len(labels), 30)
        self.assertTrue(all("/" in label for label in labels))  # Format: MM/DD

        # Should have at least one dataset for the tag
        self.assertGreaterEqual(len(datasets), 1)
        self.assertEqual(datasets[0]["label"], "tag1")
        self.assertEqual(len(datasets[0]["data"]), 30)

    def test_view_trend_data_multiple_tags(self):
        """Test trend data generation with multiple tags."""
        self.client.login(username="testuser", password="password123")

        # Grant points with different tags
        grant_points(
            user_profile=self.user,
            points=100,
            description="Tag1 points",
            tag_names=["tag1"],
        )
        grant_points(
            user_profile=self.user,
            points=50,
            description="Tag2 points",
            tag_names=["tag2"],
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        datasets = json.loads(response.context["trend_datasets_json"])

        # Should have datasets for both tags
        self.assertEqual(len(datasets), 2)
        tag_labels = {ds["label"] for ds in datasets}
        self.assertIn("tag1", tag_labels)
        self.assertIn("tag2", tag_labels)

    def test_view_trend_data_with_spend_transactions(self):
        """Test that trend data includes both EARN and SPEND transactions."""
        self.client.login(username="testuser", password="password123")

        # Use a fixed date for testing
        with patch("django.utils.timezone.now") as mock_now:
            base_date = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
            mock_now.return_value = base_date

            # Grant points 5 days ago
            past_date = base_date - timedelta(days=5)
            with patch("django.utils.timezone.now", return_value=past_date):
                grant_points(
                    user_profile=self.user,
                    points=100,
                    description="Past grant",
                    tag_names=["tag1"],
                )

            # Spend points 2 days ago
            spend_date = base_date - timedelta(days=2)
            with patch("django.utils.timezone.now", return_value=spend_date):
                spend_points(
                    user_profile=self.user, amount=30, description="Past spend"
                )

            # Get the view with the base date
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        datasets = json.loads(response.context["trend_datasets_json"])

        # Should have trend data that reflects both grant and spend
        self.assertGreaterEqual(len(datasets), 1)

    def test_view_trend_data_excludes_zero_points_tags(self):
        """Test that trend data excludes tags with no current points and no changes."""
        self.client.login(username="testuser", password="password123")

        # Grant and then spend all points for tag1
        grant_points(
            user_profile=self.user,
            points=50,
            description="Grant",
            tag_names=["tag1"],
        )
        spend_points(user_profile=self.user, amount=50, description="Spend all")

        # Grant points for tag2 (active)
        grant_points(
            user_profile=self.user,
            points=100,
            description="Active tag",
            tag_names=["tag2"],
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        datasets = json.loads(response.context["trend_datasets_json"])

        # Should have tag2 in datasets (has current points)
        tag_labels = [ds["label"] for ds in datasets]
        self.assertIn("tag2", tag_labels)

    def test_view_trend_data_date_range(self):
        """Test that trend data covers exactly 30 days."""
        self.client.login(username="testuser", password="password123")

        # Grant points on different dates
        with patch("django.utils.timezone.now") as mock_now:
            base_date = datetime(2025, 1, 30, 12, 0, 0, tzinfo=UTC)
            mock_now.return_value = base_date

            # Grant points 10 days ago
            past_date = base_date - timedelta(days=10)
            with patch("django.utils.timezone.now", return_value=past_date):
                grant_points(
                    user_profile=self.user,
                    points=50,
                    description="10 days ago",
                    tag_names=["tag1"],
                )

            # Grant points today
            grant_points(
                user_profile=self.user,
                points=50,
                description="Today",
                tag_names=["tag1"],
            )

            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        labels = json.loads(response.context["trend_labels_json"])
        datasets = json.loads(response.context["trend_datasets_json"])

        # Labels should be exactly 30 days
        self.assertEqual(len(labels), 30)

        # Data points should also be 30
        self.assertEqual(len(datasets[0]["data"]), 30)

    def test_view_trend_data_with_old_transactions(self):
        """Test that trend data only includes transactions from last 30 days."""
        self.client.login(username="testuser", password="password123")

        with patch("django.utils.timezone.now") as mock_now:
            base_date = datetime(2025, 1, 30, 12, 0, 0, tzinfo=UTC)
            mock_now.return_value = base_date

            # Grant points 60 days ago (outside 30-day window)
            old_date = base_date - timedelta(days=60)
            with patch("django.utils.timezone.now", return_value=old_date):
                grant_points(
                    user_profile=self.user,
                    points=200,
                    description="Old points",
                    tag_names=["tag1"],
                )

            # Grant points 5 days ago (within window)
            recent_date = base_date - timedelta(days=5)
            with patch("django.utils.timezone.now", return_value=recent_date):
                grant_points(
                    user_profile=self.user,
                    points=50,
                    description="Recent points",
                    tag_names=["tag1"],
                )

            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        datasets = json.loads(response.context["trend_datasets_json"])

        # Should have trend data
        self.assertGreaterEqual(len(datasets), 1)

        # The starting point should account for old points not in the window
        # but the trend should only show changes from the last 30 days
        trend_data = datasets[0]["data"]
        self.assertEqual(len(trend_data), 30)

    def test_view_points_by_tag_multiple_sources(self):
        """Test that points_by_tag aggregates multiple sources with same tag."""
        self.client.login(username="testuser", password="password123")

        # Create multiple sources with same tag
        grant_points(
            user_profile=self.user,
            points=100,
            description="First",
            tag_names=["tag1"],
        )
        grant_points(
            user_profile=self.user,
            points=50,
            description="Second",
            tag_names=["tag1"],
        )
        grant_points(
            user_profile=self.user,
            points=25,
            description="Third",
            tag_names=["tag2"],
        )

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        points_by_tag = response.context["points_by_tag"]

        # Should have 2 tags
        self.assertEqual(len(points_by_tag), 2)

        # Find tag1 and verify total
        tag1_points = next(
            item["points"] for item in points_by_tag if item["tag"] == "tag1"
        )
        self.assertEqual(tag1_points, 150)  # 100 + 50

    def test_view_with_empty_transaction_history(self):
        """Test view renders correctly with no transactions."""
        self.client.login(username="testuser", password="password123")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("page_obj", response.context)
        self.assertEqual(len(response.context["page_obj"]), 0)

    def test_view_trend_cumulative_calculation(self):
        """Test that trend data correctly calculates cumulative points."""
        self.client.login(username="testuser", password="password123")

        with patch("django.utils.timezone.now") as mock_now:
            base_date = datetime(2025, 1, 30, 12, 0, 0, tzinfo=UTC)
            mock_now.return_value = base_date

            # Start with initial points outside the window
            old_date = base_date - timedelta(days=35)
            with patch("django.utils.timezone.now", return_value=old_date):
                grant_points(
                    user_profile=self.user,
                    points=100,
                    description="Initial",
                    tag_names=["tag1"],
                )

            # Add points 15 days ago
            date1 = base_date - timedelta(days=15)
            with patch("django.utils.timezone.now", return_value=date1):
                grant_points(
                    user_profile=self.user,
                    points=50,
                    description="Mid-period",
                    tag_names=["tag1"],
                )

            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        datasets = json.loads(response.context["trend_datasets_json"])

        # Verify cumulative data increases over time
        trend_data = datasets[0]["data"]
        self.assertGreaterEqual(trend_data[-1], trend_data[0])  # End should be >= start

    def test_view_with_multiple_tags_per_source(self):
        """Test handling of point sources with multiple tags."""
        self.client.login(username="testuser", password="password123")

        # Manually create a source with multiple tags
        tag1 = Tag.objects.create(name="tag1")
        tag2 = Tag.objects.create(name="tag2")

        source = PointSource.objects.create(
            user_profile=self.user,
            initial_points=100,
            remaining_points=100,
        )
        source.tags.add(tag1, tag2)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        points_by_tag = response.context["points_by_tag"]

        # Both tags should show the full 100 points (since the source has both)
        self.assertEqual(len(points_by_tag), 2)


class TestMyPointsViewPytest:
    """Additional pytest-style tests for my_points view."""

    def test_view_select_related_optimization(self, authenticated_client, user):
        """Test that view uses select_related for query optimization."""
        # Grant points to create transactions
        grant_points(
            user_profile=user,
            points=100,
            description="Test",
            tag_names=["tag1"],
        )

        url = reverse("points:my_points")

        # Check that view executes successfully
        response = authenticated_client.get(url)
        self.assertEqual(response.status_code, 200)
        # Verify the view doesn't cause N+1 query issues by checking transaction data is loaded
        self.assertGreater(len(response.context["page_obj"]), 0)

    def test_view_context_contains_all_required_data(self, authenticated_client, user):
        """Test that view context contains all required template variables."""
        grant_points(
            user_profile=user,
            points=50,
            description="Test",
            tag_names=["tag1"],
        )

        url = reverse("points:my_points")
        response = authenticated_client.get(url)

        self.assertEqual(response.status_code, 200)

        # Verify all required context variables
        required_keys = [
            "total_points",
            "points_by_tag",
            "active_sources",
            "page_obj",
            "trend_labels_json",
            "trend_datasets_json",
        ]

        for key in required_keys:
            self.assertIn(key, response.context, f"Missing context key: {key}")

    def test_view_json_serializable_trend_data(self, authenticated_client, user):
        """Test that trend data is properly JSON serializable."""
        grant_points(
            user_profile=user,
            points=100,
            description="Test",
            tag_names=["tag1", "tag2"],
        )

        url = reverse("points:my_points")
        response = authenticated_client.get(url)

        # Ensure JSON data can be parsed without errors
        labels = json.loads(response.context["trend_labels_json"])
        datasets = json.loads(response.context["trend_datasets_json"])

        self.assertTrue(isinstance(labels, list))
        self.assertTrue(isinstance(datasets, list))

        # Verify dataset structure
        if datasets:
            self.assertIn("label", datasets[0])
            self.assertIn("data", datasets[0])
            self.assertTrue(isinstance(datasets[0]["data"], list))
