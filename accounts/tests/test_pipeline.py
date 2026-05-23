"""Tests for social auth pipeline functions."""

from unittest.mock import Mock

from django.test import TestCase

from accounts.models import User, UserProfile
from accounts.pipeline import (
    prevent_duplicate_email_signup,
    update_user_profile_from_github,
)
from accounts.social_auth import EmailConflictRequiresBinding


class UpdateUserProfileFromGithubTests(TestCase):
    """Tests for update_user_profile_from_github pipeline function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser")
        self.backend_github = Mock()
        self.backend_github.name = "github"
        self.backend_other = Mock()
        self.backend_other.name = "google"

    def test_creates_profile_if_not_exists(self):
        """Test that profile is created if it doesn't exist."""
        response = {
            "login": "testuser",
            "bio": "Test bio",
            "location": "Test City",
            "company": "Test Company",
            "html_url": "https://github.com/testuser",
            "blog": "https://example.com",
        }

        update_user_profile_from_github(
            backend=self.backend_github,
            details={},
            response=response,
            user=self.user,
        )

        # Profile should be created
        self.assertTrue(UserProfile.objects.filter(user=self.user).exists())
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.bio, "Test bio")
        self.assertEqual(profile.location, "Test City")
        self.assertEqual(profile.company, "Test Company")
        self.assertEqual(profile.github_url, "https://github.com/testuser")
        self.assertEqual(profile.homepage_url, "https://example.com")

    def test_updates_empty_fields_only(self):
        """Test that only empty fields are updated."""
        # Create profile with existing data
        profile = UserProfile.objects.create(
            user=self.user,
            bio="Existing bio",
            location="",
            company="",
        )

        response = {
            "login": "testuser",
            "bio": "New bio from GitHub",
            "location": "New City",
            "company": "New Company",
        }

        update_user_profile_from_github(
            backend=self.backend_github,
            details={},
            response=response,
            user=self.user,
        )

        profile.refresh_from_db()
        # Existing bio should not be overwritten
        self.assertEqual(profile.bio, "Existing bio")
        # Empty fields should be updated
        self.assertEqual(profile.location, "New City")
        self.assertEqual(profile.company, "New Company")

    def test_strips_at_symbol_from_company(self):
        """Test that @ symbol is stripped from company name."""
        response = {
            "company": "@TestCompany",
        }

        update_user_profile_from_github(
            backend=self.backend_github,
            details={},
            response=response,
            user=self.user,
        )

        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.company, "TestCompany")

    def test_adds_https_to_blog_url(self):
        """Test that https:// is added to blog URL if missing."""
        response = {
            "blog": "example.com",
        }

        update_user_profile_from_github(
            backend=self.backend_github,
            details={},
            response=response,
            user=self.user,
        )

        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.homepage_url, "https://example.com")

    def test_skips_empty_blog_url(self):
        """Test that empty blog URL is skipped."""
        response = {
            "blog": "",
        }

        update_user_profile_from_github(
            backend=self.backend_github,
            details={},
            response=response,
            user=self.user,
        )

        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.homepage_url, "")

    def test_skips_whitespace_blog_url(self):
        """Test that whitespace-only blog URL is skipped."""
        response = {
            "blog": "   ",
        }

        update_user_profile_from_github(
            backend=self.backend_github,
            details={},
            response=response,
            user=self.user,
        )

        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.homepage_url, "")

    def test_preserves_existing_protocol_in_blog_url(self):
        """Test that existing protocol in blog URL is preserved."""
        for url in ["http://example.com", "https://example.com"]:
            with self.subTest(url=url):
                user = User.objects.create_user(username=f"user_{url}")
                response = {
                    "blog": url,
                }

                update_user_profile_from_github(
                    backend=self.backend_github,
                    details={},
                    response=response,
                    user=user,
                )

                profile = UserProfile.objects.get(user=user)
                self.assertEqual(profile.homepage_url, url)

    def test_skips_non_github_backend(self):
        """Test that pipeline is skipped for non-GitHub backends."""
        response = {
            "bio": "Test bio",
            "location": "Test City",
        }

        update_user_profile_from_github(
            backend=self.backend_other,
            details={},
            response=response,
            user=self.user,
        )

        # Profile should not be created or updated
        self.assertFalse(UserProfile.objects.filter(user=self.user).exists())

    def test_skips_if_no_user(self):
        """Test that pipeline is skipped if no user is provided."""
        response = {
            "bio": "Test bio",
        }

        result = update_user_profile_from_github(
            backend=self.backend_github,
            details={},
            response=response,
            user=None,
        )

        # Should return None and not create any profiles
        self.assertIsNone(result)
        self.assertEqual(UserProfile.objects.count(), 0)

    def test_handles_missing_fields_in_response(self):
        """Test that pipeline handles missing fields in response gracefully."""
        response = {}  # Empty response

        update_user_profile_from_github(
            backend=self.backend_github,
            details={},
            response=response,
            user=self.user,
        )

        # Profile should be created but with empty fields
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.bio, "")
        self.assertEqual(profile.location, "")
        self.assertEqual(profile.company, "")
        self.assertEqual(profile.github_url, "")
        self.assertEqual(profile.homepage_url, "")

    def test_handles_partial_response_data(self):
        """Test that pipeline handles partial response data."""
        response = {
            "bio": "Test bio",
            "location": "Test City",
            # Missing company, html_url, blog
        }

        update_user_profile_from_github(
            backend=self.backend_github,
            details={},
            response=response,
            user=self.user,
        )

        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.bio, "Test bio")
        self.assertEqual(profile.location, "Test City")

    def test_prevent_duplicate_email_signup_blocks_existing_email(self):
        """Social signup should stop when the email already belongs to an account."""
        User.objects.create_user(
            username="taken",
            email="taken@example.com",
            password="password123",
        )

        with self.assertRaises(EmailConflictRequiresBinding):
            prevent_duplicate_email_signup(
                backend=self.backend_github,
                details={"email": "Taken@example.com"},
                response={},
                user=None,
                new_association=True,
            )

    def test_prevent_duplicate_email_signup_allows_binding_same_user(self):
        """Connecting a provider to the current account should allow the same email."""
        self.user.email = "taken@example.com"
        self.user.save(update_fields=["email"])

        result = prevent_duplicate_email_signup(
            backend=self.backend_github,
            details={"email": "Taken@example.com"},
            response={},
            user=self.user,
            new_association=True,
        )

        self.assertIsNone(result)

    def test_prevent_duplicate_email_signup_skips_existing_associations(self):
        """Existing social associations should not run duplicate email checks."""
        result = prevent_duplicate_email_signup(
            backend=self.backend_github,
            details={"email": "taken@example.com"},
            response={},
            user=self.user,
            new_association=False,
        )

        self.assertIsNone(result)

    def test_prevent_duplicate_email_signup_skips_missing_email(self):
        """Social signup without an email should not trigger conflict checks."""
        result = prevent_duplicate_email_signup(
            backend=self.backend_github,
            details={},
            response={},
            user=None,
            new_association=True,
        )

        self.assertIsNone(result)

    def test_idempotent_multiple_calls(self):
        """Test that multiple calls with same data don't cause issues."""
        response = {
            "bio": "Test bio",
            "location": "Test City",
        }

        # Call twice
        update_user_profile_from_github(
            backend=self.backend_github,
            details={},
            response=response,
            user=self.user,
        )
        update_user_profile_from_github(
            backend=self.backend_github,
            details={},
            response=response,
            user=self.user,
        )

        # Should still have same data
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.bio, "Test bio")
        self.assertEqual(profile.location, "Test City")
        self.assertEqual(UserProfile.objects.count(), 1)

    def test_does_not_update_if_all_fields_filled(self):
        """Test that no update occurs if all fields are already filled."""
        # Create profile with all fields filled
        profile = UserProfile.objects.create(
            user=self.user,
            bio="Existing bio",
            location="Existing City",
            company="Existing Company",
            github_url="https://github.com/existing",
            homepage_url="https://existing.com",
        )

        response = {
            "bio": "New bio",
            "location": "New City",
            "company": "New Company",
            "html_url": "https://github.com/new",
            "blog": "https://new.com",
        }

        update_user_profile_from_github(
            backend=self.backend_github,
            details={},
            response=response,
            user=self.user,
        )

        profile.refresh_from_db()
        # All fields should remain unchanged
        self.assertEqual(profile.bio, "Existing bio")
        self.assertEqual(profile.location, "Existing City")
        self.assertEqual(profile.company, "Existing Company")
        self.assertEqual(profile.github_url, "https://github.com/existing")
        self.assertEqual(profile.homepage_url, "https://existing.com")
