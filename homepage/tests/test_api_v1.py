"""Tests for public API endpoints."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import UserProfile
from accounts.services.jwt_tokens import create_access_token


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
        self.hidden_inactive = User.objects.create_user(
            username="hidden_inactive",
            email="hidden_inactive@example.com",
            password="pass1234",
            is_active=False,
        )
        self.hidden_merged = User.objects.create_user(
            username="hidden_merged",
            email="hidden_merged@example.com",
            password="pass1234",
        )
        self.hidden_merged.merged_into = self.alice
        self.hidden_merged.save(update_fields=["merged_into"])
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.alice)}"
        }

    def test_homepage_search_rejects_blank_or_short_queries(self):
        """Name-info search should return no results for empty effective queries."""
        for query in ("", " ", "a"):
            response = self.client.get(
                "/api/v1/public/search",
                {"q": query},
                **self.headers,
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {"items": []})

    def test_homepage_search_returns_chdb_name_info_results(self):
        """Name-info search should proxy normalized ClickHouse results."""
        result = [
            {
                "platform": "GitHub",
                "id": 123,
                "name": "alice/repo",
                "name_zh": "",
                "type": "repo",
            }
        ]

        with patch(
            "chdb.services.search_name_info", return_value=result
        ) as search_mock:
            response = self.client.get(
                "/api/v1/public/search",
                {"q": " alice "},
                **self.headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"items": result})
        search_mock.assert_called_once_with("alice")

    def test_homepage_search_returns_unavailable_when_backend_fails(self):
        """Name-info backend failures should be surfaced as a stable API error."""
        with patch("chdb.services.search_name_info", side_effect=RuntimeError("boom")):
            response = self.client.get(
                "/api/v1/public/search",
                {"q": "alice"},
                **self.headers,
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "search_unavailable")

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
        self.assertNotIn("email", payload["user"])
        self.assertEqual(payload["profile"]["company"], "OpenShare")
        self.assertNotIn("birth_date", payload["profile"])
        self.assertEqual(payload["work_experiences"][0]["company_name"], "OpenShare")
        self.assertEqual(payload["educations"][0]["institution_name"], "Tsinghua")

    def test_search_without_query_returns_validation_error(self):
        """The API should reject requests missing the required query."""
        response = self.client.get("/api/v1/public/users/search", {})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "validation_error")

    def test_search_with_blank_query_returns_validation_error(self):
        """Blank search queries should be rejected after trimming."""
        response = self.client.get("/api/v1/public/users/search", {"q": " "})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["q"][0]["code"], "required")

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

    def test_search_does_not_match_email_or_hidden_accounts(self):
        """Public search should not reveal users by email or hidden account state."""
        email_response = self.client.get(
            "/api/v1/public/users/search",
            {"q": self.alice.email},
        )
        self.assertEqual(email_response.status_code, 200)
        self.assertEqual(email_response.json()["items"], [])
        self.assertIsNone(email_response.json()["exact_match_username"])

        inactive_response = self.client.get(
            "/api/v1/public/users/search",
            {"q": "hidden_inactive"},
        )
        self.assertEqual(inactive_response.status_code, 200)
        self.assertEqual(inactive_response.json()["items"], [])

        merged_response = self.client.get(
            "/api/v1/public/users/search",
            {"q": "hidden_merged"},
        )
        self.assertEqual(merged_response.status_code, 200)
        self.assertEqual(merged_response.json()["items"], [])

    def test_public_profile_returns_not_found_for_inactive_or_merged_users(self):
        """Inactive and merged users should not be visible through the public profile API."""
        inactive_response = self.client.get(
            f"/api/v1/public/users/{self.hidden_inactive.username}"
        )
        self.assertEqual(inactive_response.status_code, 404)

        merged_response = self.client.get(
            f"/api/v1/public/users/{self.hidden_merged.username}"
        )
        self.assertEqual(merged_response.status_code, 404)

    def test_public_profile_read_does_not_create_missing_profile(self):
        """Reading a user without a profile should not create one implicitly."""
        user_without_profile = get_user_model().objects.create_user(
            username="no_profile_public",
            email="no_profile_public@example.com",
            password="pass1234",
        )
        self.assertFalse(UserProfile.objects.filter(user=user_without_profile).exists())

        response = self.client.get(
            f"/api/v1/public/users/{user_without_profile.username}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["profile"],
            {
                "bio": "",
                "github_url": "",
                "homepage_url": "",
                "blog_url": "",
                "twitter_url": "",
                "linkedin_url": "",
                "company": "",
                "location": "",
            },
        )
        self.assertEqual(response.json()["work_experiences"], [])
        self.assertEqual(response.json()["educations"], [])
        self.assertFalse(UserProfile.objects.filter(user=user_without_profile).exists())
