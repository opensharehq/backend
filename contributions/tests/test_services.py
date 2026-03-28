"""Tests for contribution services."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from social_django.models import UserSocialAuth

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

        # 创建 GitHub social auth
        UserSocialAuth.objects.create(user=self.user1, provider="github", uid="123456")
        UserSocialAuth.objects.create(user=self.user2, provider="github", uid="789012")

    def test_get_contributions_with_fallback(self):
        """Test getting contributions with fallback to fake data."""
        start_month = date(2024, 1, 1)
        end_month = date(2024, 12, 1)

        # Mock ClickHouse query to fail, should fallback to fake data
        with patch(
            "contributions.services.ContributionService.query_from_clickhouse"
        ) as mock_query:
            mock_query.side_effect = Exception("ClickHouse connection failed")

            contributions = ContributionService.get_contributions(
                project_identifiers=["alibaba/dubbo"],
                start_month=start_month,
                end_month=end_month,
            )

            # 应该返回一些贡献数据
            self.assertTrue(len(contributions) > 0)

            # 检查数据结构
            for contrib in contributions:
                # 应该包含平台特定的字段（github_id, github_login）
                self.assertTrue(
                    "github_id" in contrib
                    or any(k.endswith("_id") for k in contrib.keys())
                )
                self.assertIn("email", contrib)
                self.assertIn("contribution_score", contrib)
                self.assertIn("is_registered", contrib)
                self.assertIsInstance(contrib["contribution_score"], Decimal)

    def test_contributions_include_registered_users(self):
        """Test that contributions include registered users."""
        # Mock ClickHouse to fail, use fake data
        with patch(
            "contributions.services.ContributionService.query_from_clickhouse"
        ) as mock_query:
            mock_query.side_effect = Exception("ClickHouse connection failed")

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
        # Mock ClickHouse to fail, use fake data
        with patch(
            "contributions.services.ContributionService.query_from_clickhouse"
        ) as mock_query:
            mock_query.side_effect = Exception("ClickHouse connection failed")

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

    def test_enrich_with_registration_status(self):
        """Test enriching contributions with registration status."""
        # Mock 贡献数据（来自 ClickHouse）
        mock_contributions = [
            {
                "platform": "GitHub",
                "actor_id": "123456",  # 对应 user1
                "actor_login": "user_one",
                "contribution_score": 100.5,
            },
            {
                "platform": "GitHub",
                "actor_id": "789012",  # 对应 user2
                "actor_login": "user_two",
                "contribution_score": 50.3,
            },
            {
                "platform": "GitHub",
                "actor_id": "999999",  # 未注册
                "actor_login": "unknown_user",
                "contribution_score": 25.0,
            },
        ]

        # 调用函数
        results = ContributionService._enrich_with_registration_status(
            mock_contributions
        )

        # 检查结果数量
        self.assertEqual(len(results), 3)

        # 检查第一个用户（已注册）
        user1_result = results[0]
        self.assertTrue(user1_result["is_registered"])
        self.assertEqual(user1_result["user_id"], self.user1.id)
        self.assertEqual(user1_result["github_id"], "123456")
        self.assertEqual(user1_result["github_login"], "user_one")

        # 检查第二个用户（已注册）
        user2_result = results[1]
        self.assertTrue(user2_result["is_registered"])
        self.assertEqual(user2_result["user_id"], self.user2.id)

        # 检查第三个用户（未注册）
        unregistered_result = results[2]
        self.assertFalse(unregistered_result["is_registered"])
        self.assertIsNone(unregistered_result["user_id"])

    def test_enrich_with_details_preserved(self):
        """Verify _enrich_with_registration_status keeps the details payload."""

        contributions = [
            {
                "platform": "GitHub",
                "actor_id": "123456",
                "actor_login": "user_one",
                "contribution_score": 100.5,
                "details": {"repos": [("repo1", 10)]},
            }
        ]

        results = ContributionService._enrich_with_registration_status(contributions)

        self.assertEqual(len(results), 1)
        self.assertIn("details", results[0])
        self.assertEqual(results[0]["details"], contributions[0]["details"])

    @patch("chdb.services.query_contributions")
    def test_query_from_clickhouse(self, mock_query_contributions):
        """Test querying from ClickHouse."""
        # Mock ClickHouse 返回数据
        mock_query_contributions.return_value = [
            {
                "platform": "GitHub",
                "actor_id": "123456",
                "actor_login": "testuser1",
                "contribution_score": 150.5,
            },
            {
                "platform": "GitHub",
                "actor_id": "999999",
                "actor_login": "unknown",
                "contribution_score": 50.0,
            },
        ]

        # 调用函数
        start_month = date(2024, 5, 1)
        end_month = date(2024, 6, 30)
        results = ContributionService.query_from_clickhouse(
            project_identifiers=[":companies/test/project"],
            start_month=start_month,
            end_month=end_month,
        )

        # 检查结果
        self.assertEqual(len(results), 2)

        # 检查已注册用户
        registered = [r for r in results if r["is_registered"]]
        self.assertEqual(len(registered), 1)
        self.assertEqual(registered[0]["user_id"], self.user1.id)

        # 检查未注册用户
        unregistered = [r for r in results if not r["is_registered"]]
        self.assertEqual(len(unregistered), 1)
        self.assertIsNone(unregistered[0]["user_id"])

    @patch("chdb.services.query_contributions")
    def test_query_from_clickhouse_empty_returns_empty(self, mock_query_contributions):
        """Querying contributions with no results should return an empty list."""

        mock_query_contributions.return_value = []

        results = ContributionService.query_from_clickhouse(
            project_identifiers=[":companies/test/project"],
            start_month=date(2024, 5, 1),
            end_month=date(2024, 6, 30),
        )

        self.assertEqual(results, [])

    @patch("chdb.services.query_contributions")
    def test_get_contributions_success_path_uses_chdb_query(self, mock_query_contributions):
        """get_contributions should flow through ClickHouse path on success."""
        UserSocialAuth.objects.create(user=self.user2, provider="gitlab", uid="gl-42")
        mock_query_contributions.return_value = [
            {
                "platform": "GitHub",
                "actor_id": "123456",
                "actor_login": "testuser1",
                "contribution_score": 88.8,
                "details": [("repo-a", 88.8, 202405)],
            },
            {
                "platform": "GitLab",
                "actor_id": "gl-42",
                "actor_login": "testuser2",
                "contribution_score": 66.6,
                "details": [("repo-b", 66.6, 202405)],
            },
        ]

        results = ContributionService.get_contributions(
            project_identifiers=[":companies/test/project"],
            start_month=date(2024, 5, 1),
            end_month=date(2024, 6, 30),
        )

        mock_query_contributions.assert_called_once_with(
            label_ids=[":companies/test/project"],
            start_month=202405,
            end_month=202406,
        )
        self.assertEqual(len(results), 2)

        github_result = next(item for item in results if item["platform"] == "GitHub")
        self.assertEqual(github_result["github_id"], "123456")
        self.assertEqual(github_result["github_login"], "testuser1")
        self.assertTrue(github_result["is_registered"])
        self.assertEqual(github_result["user_id"], self.user1.id)
        self.assertIsInstance(github_result["contribution_score"], Decimal)
        self.assertIn("details", github_result)

        gitlab_result = next(item for item in results if item["platform"] == "GitLab")
        self.assertEqual(gitlab_result["gitlab_id"], "gl-42")
        self.assertEqual(gitlab_result["gitlab_login"], "testuser2")
        self.assertTrue(gitlab_result["is_registered"])
        self.assertEqual(gitlab_result["user_id"], self.user2.id)
        self.assertEqual(
            gitlab_result["details"],
            [("repo-b", 66.6, 202405)],
        )

    def test_enrich_with_registration_status_multi_platform_and_mixed_actor_id_types(self):
        """Enrich should support multiple providers and mixed actor_id value types."""
        UserSocialAuth.objects.create(user=self.user2, provider="gitlab", uid="gl-100")
        contributions = [
            {
                "platform": "GitHub",
                "actor_id": "123456",
                "actor_login": "testuser1",
                "contribution_score": 10.5,
            },
            {
                "platform": "GitLab",
                "actor_id": "gl-100",
                "actor_login": "testuser2",
                "contribution_score": 9.5,
                "details": [("repo-c", 9.5, 202406)],
            },
            {
                "platform": "GitLab",
                "actor_id": 987654,
                "actor_login": "unregistered-numeric-id",
                "contribution_score": 3.0,
            },
        ]

        results = ContributionService._enrich_with_registration_status(contributions)
        self.assertEqual(len(results), 3)

        github_result = next(item for item in results if item["platform"] == "GitHub")
        self.assertEqual(github_result["github_id"], "123456")
        self.assertTrue(github_result["is_registered"])
        self.assertEqual(github_result["user_id"], self.user1.id)

        gitlab_registered = next(
            item for item in results if item.get("gitlab_login") == "testuser2"
        )
        self.assertEqual(gitlab_registered["gitlab_id"], "gl-100")
        self.assertTrue(gitlab_registered["is_registered"])
        self.assertEqual(gitlab_registered["user_id"], self.user2.id)
        self.assertEqual(gitlab_registered["details"], [("repo-c", 9.5, 202406)])
        self.assertIsInstance(gitlab_registered["contribution_score"], Decimal)

        gitlab_unregistered = next(
            item
            for item in results
            if item.get("gitlab_login") == "unregistered-numeric-id"
        )
        self.assertEqual(gitlab_unregistered["gitlab_id"], 987654)
        self.assertFalse(gitlab_unregistered["is_registered"])
        self.assertIsNone(gitlab_unregistered["user_id"])
