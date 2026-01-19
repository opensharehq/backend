"""Tests for contribution services."""

from datetime import date
from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from contributions.services import ContributionService


class ContributionServiceTests(TestCase):
    """Tests for contribution service."""

    def setUp(self):
        """Set up test data."""
        # 创建测试用户
        self.user1 = User.objects.create_user(
            username="testuser1", email="test1@example.com"
        )
        self.user2 = User.objects.create_user(
            username="testuser2", email="test2@example.com"
        )

    def test_get_fake_contributions(self):
        """Test getting fake contributions."""
        start_month = date(2024, 1, 1)
        end_month = date(2024, 12, 1)

        contributions = ContributionService.get_contributions(
            project_identifiers=["alibaba/dubbo"],
            start_month=start_month,
            end_month=end_month,
        )

        # 应该返回一些贡献数据
        self.assertTrue(len(contributions) > 0)

        # 检查数据结构
        for contrib in contributions:
            self.assertIn("github_id", contrib)
            self.assertIn("github_login", contrib)
            self.assertIn("email", contrib)
            self.assertIn("contribution_score", contrib)
            self.assertIn("is_registered", contrib)
            self.assertIsInstance(contrib["contribution_score"], Decimal)

    def test_contributions_include_registered_users(self):
        """Test that contributions include registered users."""
        contributions = ContributionService.get_contributions(
            project_identifiers=["test/project"],
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        # 应该包含已注册的用户
        registered_users = [c for c in contributions if c["is_registered"]]
        self.assertTrue(len(registered_users) > 0)

        # 检查已注册用户有 user_id
        for user_contrib in registered_users:
            self.assertIsNotNone(user_contrib["user_id"])

    def test_contributions_include_unregistered_users(self):
        """Test that contributions include unregistered users."""
        contributions = ContributionService.get_contributions(
            project_identifiers=["test/project"],
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        # 应该包含未注册的用户
        unregistered_users = [c for c in contributions if not c["is_registered"]]
        self.assertTrue(len(unregistered_users) > 0)

        # 检查未注册用户没有 user_id
        for user_contrib in unregistered_users:
            self.assertIsNone(user_contrib["user_id"])

    def test_query_from_clickhouse_not_implemented(self):
        """Test that ClickHouse query raises NotImplementedError."""
        with self.assertRaises(NotImplementedError):
            ContributionService.query_from_clickhouse(
                project_identifiers=["test/project"],
                start_month=date(2024, 1, 1),
                end_month=date(2024, 12, 1),
            )
