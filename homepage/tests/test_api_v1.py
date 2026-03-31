"""Tests for public API endpoints."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import UserProfile


class HomepageApiV1Tests(TestCase):
    """Validate public search and profile APIs."""

    def setUp(self):
        """Create public user fixtures."""
        User = get_user_model()
        self.alice = User.objects.create_user(
            username="alice_api",
            email="alice_api@example.com",
            password="pass1234",
            first_name="Alice",
        )
        UserProfile.objects.create(
            user=self.alice,
            company="OpenShare",
            location="Shanghai",
            bio="Core contributor",
        )

        self.bob = User.objects.create_user(
            username="bob_api",
            email="bob_api@example.com",
            password="pass1234",
            first_name="Bob",
        )
        UserProfile.objects.create(
            user=self.bob,
            company="Example Inc",
            location="Beijing",
            bio="Community member",
        )
        self.bob.profile.birth_date = "1990-01-01"
        self.bob.profile.save(update_fields=["birth_date"])
        self.work = self.alice.profile.work_experiences.create(
            company_name="OpenShare",
            title="Engineer",
            start_date="2020-01-01",
            end_date="2022-01-01",
            description="Building APIs",
        )
        self.education = self.alice.profile.educations.create(
            institution_name="Tsinghua",
            degree="Master",
            field_of_study="Computer Science",
            start_date="2016-09-01",
            end_date="2018-07-01",
        )

    def test_public_search_returns_filtered_results(self):
        """Public search should return JSON results with filters applied."""
        response = self.client.get(
            "/api/v1/public/users/search",
            {"q": "api", "location": "Shanghai"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_matches"], 1)
        self.assertEqual(payload["items"][0]["username"], self.alice.username)
        self.assertEqual(payload["available_locations"], ["Shanghai"])
        self.assertEqual(payload["available_companies"], ["OpenShare"])
        self.assertEqual(payload["filters"]["location"], "Shanghai")

    def test_public_profile_returns_user_details(self):
        """Public profile API should expose profile details."""
        response = self.client.get(f"/api/v1/public/users/{self.alice.username}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["user"]["username"], self.alice.username)
        self.assertEqual(payload["profile"]["company"], "OpenShare")
        self.assertEqual(payload["work_experiences"][0]["company_name"], "OpenShare")
        self.assertEqual(payload["educations"][0]["institution_name"], "Tsinghua")

    def test_search_without_query_returns_validation_error(self):
        """The API should reject requests missing the required query."""
        response = self.client.get("/api/v1/public/users/search", {})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "validation_error")

    def test_search_invalid_sort_falls_back(self):
        """Unsupported sort values revert to the default ordering."""
        response = self.client.get(
            "/api/v1/public/users/search",
            {"q": "api", "sort": "unsupported"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["filters"]["sort"], "relevance")

    def test_search_supports_exact_match_metadata(self):
        """Exact username matches appear as part of the payload."""
        response = self.client.get(
            "/api/v1/public/users/search",
            {"q": "alice_api"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["exact_match_username"], "alice_api")
