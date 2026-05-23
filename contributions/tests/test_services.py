"""Regression-focused tests for contribution services."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from social_django.models import UserSocialAuth

from accounts.models import User
from contributions.services import ContributionDataUnavailableError, ContributionService


class ContributionServiceTests(TestCase):
    """Tests that lock contribution payload semantics and integration boundaries."""

    def setUp(self):
        """Create registered users used across the contribution scenarios."""
        self.user1 = User.objects.create_user(
            username="testuser1",
            email="test1@example.com",
        )
        self.user2 = User.objects.create_user(
            username="testuser2",
            email="test2@example.com",
        )
        UserSocialAuth.objects.create(user=self.user1, provider="github", uid="123456")
        UserSocialAuth.objects.create(user=self.user2, provider="github", uid="789012")

    @patch(
        "chdb.services.query_contributions",
        side_effect=Exception("ClickHouse connection failed"),
    )
    def test_get_contributions_raises_when_clickhouse_is_unavailable(self, _mock_query):
        """ClickHouse failures should fail explicitly instead of falling back to fake data."""
        with (
            self.assertLogs("contributions.services", level="ERROR") as cm,
            self.assertRaises(ContributionDataUnavailableError),
        ):
            ContributionService.get_contributions(
                project_identifiers=["repo:github:test"],
                start_month=date(2024, 1, 1),
                end_month=date(2024, 12, 1),
            )

        self.assertEqual(len(cm.output), 1)
        self.assertIn("查询 ClickHouse 失败", cm.output[0])

    @patch("chdb.services.query_contributions", return_value=[])
    def test_get_contributions_preserves_empty_success_result(self, _mock_query):
        """An empty ClickHouse response is still a successful query, not a fallback case."""
        results = ContributionService.get_contributions(
            project_identifiers=["repo:github:empty"],
            start_month=date(2024, 1, 1),
            end_month=date(2024, 1, 31),
        )

        self.assertEqual(results, [])

    @patch("chdb.services.query_contributions")
    def test_query_from_clickhouse_formats_months_and_registration_payload(
        self, mock_query_contributions
    ):
        """ClickHouse rows should be normalized into the exact public payload contract."""
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

        results = ContributionService.query_from_clickhouse(
            project_identifiers=[":companies/test/project"],
            start_month=date(2024, 5, 1),
            end_month=date(2024, 6, 30),
        )

        mock_query_contributions.assert_called_once_with(
            label_ids=[":companies/test/project"],
            start_month=202405,
            end_month=202406,
        )
        self.assertEqual(
            results,
            [
                {
                    "platform": "GitHub",
                    "actor_id": "123456",
                    "actor_login": "testuser1",
                    "github_id": "123456",
                    "github_login": "testuser1",
                    "email": "",
                    "contribution_score": Decimal("88.8"),
                    "is_registered": True,
                    "user_id": self.user1.id,
                    "details": [("repo-a", 88.8, 202405)],
                },
                {
                    "platform": "GitLab",
                    "actor_id": "gl-42",
                    "actor_login": "testuser2",
                    "gitlab_id": "gl-42",
                    "gitlab_login": "testuser2",
                    "email": "",
                    "contribution_score": Decimal("66.6"),
                    "is_registered": True,
                    "user_id": self.user2.id,
                    "details": [("repo-b", 66.6, 202405)],
                },
            ],
        )

    @patch("chdb.services.query_contributions", return_value=[])
    def test_query_from_clickhouse_empty_returns_empty(self, mock_query_contributions):
        """No contribution rows should return an empty result without enrichment work."""
        results = ContributionService.query_from_clickhouse(
            project_identifiers=[":companies/test/project"],
            start_month=date(2024, 5, 1),
            end_month=date(2024, 6, 30),
        )

        mock_query_contributions.assert_called_once_with(
            label_ids=[":companies/test/project"],
            start_month=202405,
            end_month=202406,
        )
        self.assertEqual(results, [])

    def test_enrich_with_registration_status_supports_multiple_platforms_without_n_plus_one(
        self,
    ):
        """Registration enrichment should batch by platform instead of querying per row."""
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

        with self.assertNumQueries(2):
            results = ContributionService._enrich_with_registration_status(
                contributions
            )

        self.assertEqual(
            results,
            [
                {
                    "platform": "GitHub",
                    "actor_id": "123456",
                    "actor_login": "testuser1",
                    "github_id": "123456",
                    "github_login": "testuser1",
                    "email": "",
                    "contribution_score": Decimal("10.5"),
                    "is_registered": True,
                    "user_id": self.user1.id,
                },
                {
                    "platform": "GitLab",
                    "actor_id": "gl-100",
                    "actor_login": "testuser2",
                    "gitlab_id": "gl-100",
                    "gitlab_login": "testuser2",
                    "email": "",
                    "contribution_score": Decimal("9.5"),
                    "is_registered": True,
                    "user_id": self.user2.id,
                    "details": [("repo-c", 9.5, 202406)],
                },
                {
                    "platform": "GitLab",
                    "actor_id": "987654",
                    "actor_login": "unregistered-numeric-id",
                    "gitlab_id": 987654,
                    "gitlab_login": "unregistered-numeric-id",
                    "email": "",
                    "contribution_score": Decimal("3.0"),
                    "is_registered": False,
                    "user_id": None,
                },
            ],
        )

    def test_get_fake_contributions_synthesizes_actor_id_without_social_auth(self):
        """Registered users without GitHub auth should still get deterministic fake IDs."""
        user_without_social = User.objects.create_user(
            username="nosocial",
            email="nosocial@example.com",
        )

        results = ContributionService._get_fake_contributions(
            project_identifiers=["repo:github:test"],
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        user_result = next(
            item for item in results if item["user_id"] == user_without_social.id
        )
        self.assertEqual(user_result["github_login"], user_without_social.username)
        self.assertEqual(user_result["github_id"], str(1000000 + 2))
        self.assertEqual(user_result["contribution_score"], Decimal("210.5"))
        self.assertTrue(user_result["is_registered"])

    def test_get_contributions_rejects_missing_date_range(self):
        """Missing month bounds should fail loudly instead of silently changing behavior."""
        with self.assertRaises(ValueError):
            ContributionService.get_contributions(
                project_identifiers=["repo:github:test"],
                start_month=None,
                end_month=None,
            )

    @patch("chdb.services.query_contributions")
    def test_validate_platform_present_rejects_missing_platform(
        self, mock_query_contributions
    ):
        """Contributions without a platform field should be rejected at the boundary."""
        mock_query_contributions.return_value = [
            {
                "platform": "GitHub",
                "actor_id": "111",
                "actor_login": "valid-user",
                "contribution_score": 10.0,
            },
            {
                "actor_id": "222",
                "actor_login": "no-platform-user",
                "contribution_score": 5.0,
            },
        ]

        with self.assertRaises(ContributionDataUnavailableError):
            ContributionService.get_contributions(
                project_identifiers=["repo:github:test"],
                start_month=date(2024, 1, 1),
                end_month=date(2024, 12, 1),
            )

    @patch("chdb.services.query_contributions")
    def test_validate_platform_present_rejects_empty_string_platform(
        self, mock_query_contributions
    ):
        """Empty string platform should be rejected."""
        mock_query_contributions.return_value = [
            {
                "platform": "",
                "actor_id": "333",
                "actor_login": "empty-platform",
                "contribution_score": 8.0,
            },
        ]

        with self.assertRaises(ContributionDataUnavailableError):
            ContributionService.get_contributions(
                project_identifiers=["repo:github:test"],
                start_month=date(2024, 1, 1),
                end_month=date(2024, 12, 1),
            )
