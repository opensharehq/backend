"""Tests for social auth pipeline functions."""

from unittest.mock import Mock

from django.test import TestCase

from accounts.models import User, UserProfile
from accounts.pipeline import (
    ATOMGIT_USERNAME_PREFIX,
    assign_social_username,
    update_user_profile_from_github,
)


class AssignSocialUsernameTests(TestCase):
    """Tests for the custom username allocation pipeline."""

    def setUp(self):
        """Set up test fixtures."""
        self.strategy = Mock()
        self.github_backend = Mock()
        self.github_backend.name = "github"
        self.atomgit_backend = Mock()
        self.atomgit_backend.name = "atomgit"

    def test_returns_none_when_user_already_exists(self):
        """Existing users (binding/relogin) keep their current username."""
        user = User.objects.create_user(username="existing")

        result = assign_social_username(
            self.strategy,
            details={"username": "ignored"},
            backend=self.github_backend,
            user=user,
        )

        self.assertIsNone(result)

    def test_github_uses_login_directly_when_available(self):
        """GitHub signup should use the GitHub login as username when free."""
        result = assign_social_username(
            self.strategy,
            details={"username": "octocat"},
            backend=self.github_backend,
            user=None,
            response={},
        )

        self.assertEqual(result, {"username": "octocat"})

    def test_github_falls_back_to_response_login_field(self):
        """When details.username is empty, response.login should be used."""
        result = assign_social_username(
            self.strategy,
            details={},
            backend=self.github_backend,
            user=None,
            response={"login": "octocat"},
        )

        self.assertEqual(result, {"username": "octocat"})

    def test_github_appends_3_digit_suffix_on_conflict(self):
        """When the GitHub username is taken, append a 3-digit numeric suffix."""
        User.objects.create_user(username="octocat")

        result = assign_social_username(
            self.strategy,
            details={"username": "octocat"},
            backend=self.github_backend,
            user=None,
            response={},
        )

        username = result["username"]
        self.assertTrue(username.startswith("octocat-"))
        suffix = username.split("-")[-1]
        self.assertEqual(len(suffix), 3)
        self.assertTrue(suffix.isdigit())
        self.assertGreaterEqual(int(suffix), 100)
        self.assertLessEqual(int(suffix), 999)

    def test_atomgit_username_uses_ag_prefix(self):
        """AtomGit signups should be prefixed with ``ag-``."""
        result = assign_social_username(
            self.strategy,
            details={"username": "alice"},
            backend=self.atomgit_backend,
            user=None,
            response={},
        )

        self.assertEqual(result, {"username": f"{ATOMGIT_USERNAME_PREFIX}alice"})

    def test_atomgit_appends_3_digit_suffix_on_conflict(self):
        """AtomGit signups append a 3-digit suffix when the prefixed name is taken."""
        User.objects.create_user(username=f"{ATOMGIT_USERNAME_PREFIX}alice")

        result = assign_social_username(
            self.strategy,
            details={"username": "alice"},
            backend=self.atomgit_backend,
            user=None,
            response={},
        )

        username = result["username"]
        self.assertTrue(username.startswith(f"{ATOMGIT_USERNAME_PREFIX}alice-"))
        suffix = username.rsplit("-", 1)[-1]
        self.assertEqual(len(suffix), 3)
        self.assertTrue(suffix.isdigit())

    def test_keeps_retrying_until_unique_suffix_found(self):
        """If the random suffix collides, the pipeline should keep retrying."""
        # Pre-create users that occupy candidate-NNN to exercise the retry loop.
        User.objects.create_user(username="alice")
        for digits in range(100, 110):
            User.objects.create_user(username=f"alice-{digits}")

        result = assign_social_username(
            self.strategy,
            details={"username": "alice"},
            backend=self.github_backend,
            user=None,
            response={},
        )

        username = result["username"]
        self.assertNotEqual(username, "alice")
        self.assertFalse(
            User.objects.filter(username=username).exclude(username=username).exists(),
            "Allocated username must not collide with existing accounts",
        )

    def test_falls_back_to_backend_name_when_no_username_available(self):
        """If neither details nor response carry a login, fall back gracefully."""
        result = assign_social_username(
            self.strategy,
            details={},
            backend=self.github_backend,
            user=None,
            response={},
        )

        self.assertEqual(result, {"username": "github"})


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

        self.assertTrue(UserProfile.objects.filter(user=self.user).exists())
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.bio, "Test bio")
        self.assertEqual(profile.location, "Test City")
        self.assertEqual(profile.company, "Test Company")
        self.assertEqual(profile.github_url, "https://github.com/testuser")
        self.assertEqual(profile.homepage_url, "https://example.com")

    def test_updates_empty_fields_only(self):
        """Test that only empty fields are updated."""
        profile = UserProfile.objects.create(
            user=self.user,
            bio="Existing bio",
            location="",
            company="",
        )

        response = {
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
        self.assertEqual(profile.bio, "Existing bio")
        self.assertEqual(profile.location, "New City")
        self.assertEqual(profile.company, "New Company")

    def test_strips_at_symbol_from_company(self):
        """Test that @ symbol is stripped from company name."""
        update_user_profile_from_github(
            backend=self.backend_github,
            details={},
            response={"company": "@TestCompany"},
            user=self.user,
        )

        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.company, "TestCompany")

    def test_adds_https_to_blog_url(self):
        """Test that https:// is added to blog URL if missing."""
        update_user_profile_from_github(
            backend=self.backend_github,
            details={},
            response={"blog": "example.com"},
            user=self.user,
        )

        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.homepage_url, "https://example.com")

    def test_skips_empty_blog_url(self):
        """Test that empty blog URL is skipped."""
        update_user_profile_from_github(
            backend=self.backend_github,
            details={},
            response={"blog": ""},
            user=self.user,
        )

        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.homepage_url, "")

    def test_skips_whitespace_blog_url(self):
        """Test that whitespace-only blog URL is skipped."""
        update_user_profile_from_github(
            backend=self.backend_github,
            details={},
            response={"blog": "   "},
            user=self.user,
        )

        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.homepage_url, "")

    def test_preserves_existing_protocol_in_blog_url(self):
        """Test that existing protocol in blog URL is preserved."""
        for url in ["http://example.com", "https://example.com"]:
            with self.subTest(url=url):
                user = User.objects.create_user(username=f"user_{url}")
                update_user_profile_from_github(
                    backend=self.backend_github,
                    details={},
                    response={"blog": url},
                    user=user,
                )
                profile = UserProfile.objects.get(user=user)
                self.assertEqual(profile.homepage_url, url)

    def test_skips_non_github_backend(self):
        """Test that pipeline is skipped for non-GitHub backends."""
        update_user_profile_from_github(
            backend=self.backend_other,
            details={},
            response={"bio": "Test bio", "location": "Test City"},
            user=self.user,
        )

        self.assertFalse(UserProfile.objects.filter(user=self.user).exists())

    def test_skips_if_no_user(self):
        """Test that pipeline is skipped if no user is provided."""
        result = update_user_profile_from_github(
            backend=self.backend_github,
            details={},
            response={"bio": "Test bio"},
            user=None,
        )

        self.assertIsNone(result)
        self.assertEqual(UserProfile.objects.count(), 0)

    def test_handles_missing_fields_in_response(self):
        """Test that pipeline handles missing fields in response gracefully."""
        update_user_profile_from_github(
            backend=self.backend_github,
            details={},
            response={},
            user=self.user,
        )

        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.bio, "")
        self.assertEqual(profile.location, "")
        self.assertEqual(profile.company, "")
        self.assertEqual(profile.github_url, "")
        self.assertEqual(profile.homepage_url, "")

    def test_idempotent_multiple_calls(self):
        """Test that multiple calls with same data don't cause issues."""
        response = {"bio": "Test bio", "location": "Test City"}

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

        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.bio, "Test bio")
        self.assertEqual(profile.location, "Test City")
        self.assertEqual(UserProfile.objects.count(), 1)

    def test_does_not_update_if_all_fields_filled(self):
        """Test that no update occurs if all fields are already filled."""
        profile = UserProfile.objects.create(
            user=self.user,
            bio="Existing bio",
            location="Existing City",
            company="Existing Company",
            github_url="https://github.com/existing",
            homepage_url="https://existing.com",
        )

        update_user_profile_from_github(
            backend=self.backend_github,
            details={},
            response={
                "bio": "New bio",
                "location": "New City",
                "company": "New Company",
                "html_url": "https://github.com/new",
                "blog": "https://new.com",
            },
            user=self.user,
        )

        profile.refresh_from_db()
        self.assertEqual(profile.bio, "Existing bio")
        self.assertEqual(profile.location, "Existing City")
        self.assertEqual(profile.company, "Existing Company")
        self.assertEqual(profile.github_url, "https://github.com/existing")
        self.assertEqual(profile.homepage_url, "https://existing.com")
