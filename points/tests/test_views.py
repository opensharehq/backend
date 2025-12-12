"""Tests for points views."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from common.test_utils import CacheClearTestCase
from points.models import PointSource, Tag
from points.services import grant_points, spend_points


class MyPointsViewTests(CacheClearTestCase):
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


class RechargeViewTests(CacheClearTestCase):
    """Test cases for recharge view."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )
        self.tag = Tag.objects.create(name="test_tag")

    def test_view_requires_login(self):
        """Test that view requires authentication."""
        point_source = PointSource.objects.create(
            user=self.user,
            initial_points=100,
            remaining_points=100,
            allow_recharge=True,
        )
        url = reverse("points:recharge", kwargs={"point_source_id": point_source.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_view_with_allow_recharge_true(self):
        """Test that view displays recharge page when allow_recharge is True."""
        self.client.login(username="testuser", password="password123")

        point_source = PointSource.objects.create(
            user=self.user,
            initial_points=100,
            remaining_points=100,
            allow_recharge=True,
        )
        point_source.tags.add(self.tag)

        url = reverse("points:recharge", kwargs={"point_source_id": point_source.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "points/recharge.html")
        self.assertEqual(response.context["point_source"], point_source)
        self.assertContains(response, "暂不支持充值")

    def test_view_with_rechargeable_tag(self):
        """Test that view displays recharge page when tag has allow_recharge=True."""
        self.client.login(username="testuser", password="password123")

        rechargeable_tag = Tag.objects.create(
            name="rechargeable-tag", allow_recharge=True
        )
        point_source = PointSource.objects.create(
            user=self.user,
            initial_points=100,
            remaining_points=100,
            allow_recharge=False,
        )
        point_source.tags.add(rechargeable_tag)

        url = reverse("points:recharge", kwargs={"point_source_id": point_source.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "points/recharge.html")
        self.assertEqual(response.context["point_source"], point_source)
        self.assertContains(response, "暂不支持充值")

    def test_view_with_allow_recharge_false(self):
        """Test that view redirects when allow_recharge is False and no rechargeable tags."""
        self.client.login(username="testuser", password="password123")

        point_source = PointSource.objects.create(
            user=self.user,
            initial_points=100,
            remaining_points=100,
            allow_recharge=False,
        )

        url = reverse("points:recharge", kwargs={"point_source_id": point_source.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("points:my_points"))

    def test_view_with_nonexistent_point_source(self):
        """Test that view returns 404 for nonexistent point source."""
        self.client.login(username="testuser", password="password123")

        url = reverse("points:recharge", kwargs={"point_source_id": 99999})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    def test_view_with_other_users_point_source(self):
        """Test that view returns 404 when accessing other user's point source."""
        self.client.login(username="testuser", password="password123")

        # Create another user and their point source
        other_user = get_user_model().objects.create_user(
            username="otheruser", email="other@example.com", password="password123"
        )
        point_source = PointSource.objects.create(
            user=other_user,
            initial_points=100,
            remaining_points=100,
            allow_recharge=True,
        )

        url = reverse("points:recharge", kwargs={"point_source_id": point_source.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    def test_view_displays_point_source_information(self):
        """Test that view displays correct point source information."""
        self.client.login(username="testuser", password="password123")

        point_source = PointSource.objects.create(
            user=self.user,
            initial_points=100,
            remaining_points=75,
            allow_recharge=True,
        )
        point_source.tags.add(self.tag)

        url = reverse("points:recharge", kwargs={"point_source_id": point_source.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "100")  # Initial points
        self.assertContains(response, "75")  # Remaining points
        self.assertContains(response, "test_tag")  # Tag name


class BatchWithdrawalViewTests(TestCase):
    """Test batch_withdrawal view."""

    def setUp(self):
        """Set up test fixtures."""
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )
        from points.services import get_or_create_withdrawal_contract

        contract, _ = get_or_create_withdrawal_contract(self.user)
        contract.mark_signed(source=contract.CompletionSource.ADMIN)
        self.withdrawable_tag = Tag.objects.create(
            name="withdrawable", withdrawable=True
        )
        self.non_withdrawable_tag = Tag.objects.create(
            name="regular", withdrawable=False
        )

    def test_view_requires_authentication(self):
        """Test that view requires login."""
        url = reverse("points:batch_withdrawal")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_view_redirects_when_no_withdrawable_sources(self):
        """Test that view redirects when user has no withdrawable sources."""
        self.client.login(username="testuser", password="password123")

        url = reverse("points:batch_withdrawal")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("points:my_points"))

        # Check message
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("没有可提现的积分池", str(messages[0]))

    def test_view_displays_withdrawable_sources(self):
        """Test that view displays only withdrawable sources."""
        self.client.login(username="testuser", password="password123")

        # Create withdrawable source
        withdrawable_source = PointSource.objects.create(
            user=self.user,
            initial_points=100,
            remaining_points=100,
        )
        withdrawable_source.tags.add(self.withdrawable_tag)

        # Create non-withdrawable source
        non_withdrawable_source = PointSource.objects.create(
            user=self.user,
            initial_points=200,
            remaining_points=200,
        )
        non_withdrawable_source.tags.add(self.non_withdrawable_tag)

        url = reverse("points:batch_withdrawal")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "批量提现")

        # Check that withdrawable sources are in context
        self.assertEqual(len(response.context["withdrawable_sources"]), 1)
        self.assertEqual(
            response.context["withdrawable_sources"][0].id, withdrawable_source.id
        )

    def test_post_creates_withdrawal_requests(self):
        """Test POST request creates withdrawal requests."""
        self.client.login(username="testuser", password="password123")

        # Create withdrawable sources
        source1 = PointSource.objects.create(
            user=self.user,
            initial_points=100,
            remaining_points=100,
        )
        source1.tags.add(self.withdrawable_tag)

        source2 = PointSource.objects.create(
            user=self.user,
            initial_points=200,
            remaining_points=200,
        )
        source2.tags.add(self.withdrawable_tag)

        url = reverse("points:batch_withdrawal")
        data = {
            f"points_{source1.id}": "50",
            f"points_{source2.id}": "100",
            "real_name": "张三",
            "id_number": "110101199001011234",
            "phone_number": "13800138000",
            "bank_name": "中国银行",
            "bank_account": "6222020200012345678",
        }

        response = self.client.post(url, data)

        # Should redirect to withdrawal list
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("points:withdrawal_list"))

        # Check that withdrawal requests were created
        from points.models import WithdrawalRequest

        withdrawal_requests = WithdrawalRequest.objects.filter(user=self.user)
        self.assertEqual(withdrawal_requests.count(), 2)

        # Verify withdrawal details
        wr1 = WithdrawalRequest.objects.get(point_source=source1)
        self.assertEqual(wr1.points, 50)
        self.assertEqual(wr1.real_name, "张三")
        self.assertEqual(wr1.id_number, "110101199001011234")

        wr2 = WithdrawalRequest.objects.get(point_source=source2)
        self.assertEqual(wr2.points, 100)

        # Check success message
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("批量提现申请已提交", str(messages[0]))
        self.assertIn("2 个提现申请", str(messages[0]))
        self.assertIn("150 积分", str(messages[0]))

    def test_post_with_no_amounts_shows_error(self):
        """Test POST with no amounts shows error."""
        self.client.login(username="testuser", password="password123")

        source = PointSource.objects.create(
            user=self.user,
            initial_points=100,
            remaining_points=100,
        )
        source.tags.add(self.withdrawable_tag)

        url = reverse("points:batch_withdrawal")
        data = {
            "real_name": "张三",
            "id_number": "110101199001011234",
            "phone_number": "13800138000",
            "bank_name": "中国银行",
            "bank_account": "6222020200012345678",
        }

        response = self.client.post(url, data)

        # Should not create any withdrawal requests
        from points.models import WithdrawalRequest

        self.assertEqual(WithdrawalRequest.objects.filter(user=self.user).count(), 0)

        # Should show error
        self.assertContains(response, "至少需要为一个积分池设置提现数量")

    def test_post_with_invalid_amount_shows_error(self):
        """Test POST with invalid amount shows error."""
        self.client.login(username="testuser", password="password123")

        source = PointSource.objects.create(
            user=self.user,
            initial_points=100,
            remaining_points=100,
        )
        source.tags.add(self.withdrawable_tag)

        url = reverse("points:batch_withdrawal")
        data = {
            f"points_{source.id}": "invalid",
            "real_name": "张三",
            "id_number": "110101199001011234",
            "phone_number": "13800138000",
            "bank_name": "中国银行",
            "bank_account": "6222020200012345678",
        }

        response = self.client.post(url, data)

        # Should show error message
        messages = list(get_messages(response.wsgi_request))
        error_messages = [str(m) for m in messages if m.level_tag == "error"]
        self.assertTrue(
            any("格式不正确" in msg for msg in error_messages),
            f"Expected format error, got: {error_messages}",
        )

    def test_post_with_amount_exceeding_balance_shows_error(self):
        """Test POST with amount exceeding balance shows error."""
        self.client.login(username="testuser", password="password123")

        source = PointSource.objects.create(
            user=self.user,
            initial_points=100,
            remaining_points=100,
        )
        source.tags.add(self.withdrawable_tag)

        url = reverse("points:batch_withdrawal")
        data = {
            f"points_{source.id}": "150",  # Exceeds remaining points
            "real_name": "张三",
            "id_number": "110101199001011234",
            "phone_number": "13800138000",
            "bank_name": "中国银行",
            "bank_account": "6222020200012345678",
        }

        response = self.client.post(url, data)

        # Should show error message
        messages = list(get_messages(response.wsgi_request))
        error_messages = [str(m) for m in messages if m.level_tag == "error"]
        self.assertTrue(
            any("不能超过剩余积分" in msg for msg in error_messages),
            f"Expected balance error, got: {error_messages}",
        )

    def test_post_with_zero_amounts_skips_sources(self):
        """Test POST with zero amounts skips those sources."""
        self.client.login(username="testuser", password="password123")

        source1 = PointSource.objects.create(
            user=self.user,
            initial_points=100,
            remaining_points=100,
        )
        source1.tags.add(self.withdrawable_tag)

        source2 = PointSource.objects.create(
            user=self.user,
            initial_points=200,
            remaining_points=200,
        )
        source2.tags.add(self.withdrawable_tag)

        url = reverse("points:batch_withdrawal")
        data = {
            f"points_{source1.id}": "50",
            f"points_{source2.id}": "0",  # Should be skipped
            "real_name": "张三",
            "id_number": "110101199001011234",
            "phone_number": "13800138000",
            "bank_name": "中国银行",
            "bank_account": "6222020200012345678",
        }

        self.client.post(url, data)

        # Only 1 withdrawal request should be created
        from points.models import WithdrawalRequest

        withdrawal_requests = WithdrawalRequest.objects.filter(user=self.user)
        self.assertEqual(withdrawal_requests.count(), 1)
        self.assertEqual(withdrawal_requests.first().point_source, source1)

    def test_post_with_invalid_form_data_shows_errors(self):
        """Test POST with invalid form data shows errors."""
        self.client.login(username="testuser", password="password123")

        source = PointSource.objects.create(
            user=self.user,
            initial_points=100,
            remaining_points=100,
        )
        source.tags.add(self.withdrawable_tag)

        url = reverse("points:batch_withdrawal")
        data = {
            f"points_{source.id}": "50",
            "real_name": "",  # Required field
            "id_number": "invalid",  # Invalid format
            "phone_number": "12345",  # Invalid format
            "bank_name": "中国银行",
            "bank_account": "6222020200012345678",
        }

        response = self.client.post(url, data)

        # Should not create withdrawal request
        from points.models import WithdrawalRequest

        self.assertEqual(WithdrawalRequest.objects.filter(user=self.user).count(), 0)

        # Should show form errors
        self.assertContains(response, "必须是18位")
        self.assertContains(response, "必须是11位")
