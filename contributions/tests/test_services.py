"""Regression-focused tests for contribution services."""

from decimal import Decimal

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

    def test_validate_platform_present_rejects_missing_platform(self):
        """Contributions without a platform field should be rejected at the boundary."""
        contributions = [
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
            ContributionService._validate_platform_present(contributions)

    def test_validate_platform_present_rejects_empty_string_platform(self):
        """Empty string platform should be rejected."""
        contributions = [
            {
                "platform": "",
                "actor_id": "333",
                "actor_login": "empty-platform",
                "contribution_score": 8.0,
            },
        ]

        with self.assertRaises(ContributionDataUnavailableError):
            ContributionService._validate_platform_present(contributions)
