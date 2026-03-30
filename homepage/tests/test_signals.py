"""Tests for homepage cache invalidation signals."""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from accounts.models import UserProfile
from homepage.cache import get_search_cache_version


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class HomepageSearchCacheSignalTests(TestCase):
    """Ensure user/profile mutations rotate search cache version."""

    def setUp(self):
        """Keep cache state isolated for each signal scenario."""
        cache.clear()
        self.User = get_user_model()

    def _assert_version_rotates(self, action):
        """Assert that the cache version changes after the provided mutation."""
        before = get_search_cache_version()
        action()
        after = get_search_cache_version()
        self.assertNotEqual(before, after)

    def test_user_create_rotates_search_cache_version(self):
        """Creating a user should invalidate homepage search cache."""

        def action():
            self.User.objects.create_user(
                username="signal-user-create",
                email="signal-user-create@example.com",
                password="pass1234",
            )

        self._assert_version_rotates(action)

    def test_user_update_rotates_search_cache_version(self):
        """Updating a user should invalidate homepage search cache."""
        user = self.User.objects.create_user(
            username="signal-user-update",
            email="signal-user-update@example.com",
            password="pass1234",
        )

        def action():
            user.first_name = "Updated"
            user.save(update_fields=["first_name"])

        self._assert_version_rotates(action)

    def test_user_delete_rotates_search_cache_version(self):
        """Deleting a user should invalidate homepage search cache."""
        user = self.User.objects.create_user(
            username="signal-user-delete",
            email="signal-user-delete@example.com",
            password="pass1234",
        )

        self._assert_version_rotates(user.delete)

    def test_user_profile_create_rotates_search_cache_version(self):
        """Creating a profile should invalidate homepage search cache."""
        user = self.User.objects.create_user(
            username="signal-profile-create",
            email="signal-profile-create@example.com",
            password="pass1234",
        )

        def action():
            UserProfile.objects.create(user=user, location="Shanghai")

        self._assert_version_rotates(action)

    def test_user_profile_update_rotates_search_cache_version(self):
        """Updating a profile should invalidate homepage search cache."""
        user = self.User.objects.create_user(
            username="signal-profile-update",
            email="signal-profile-update@example.com",
            password="pass1234",
        )
        profile = UserProfile.objects.create(user=user, location="Shanghai")

        def action():
            profile.location = "Hangzhou"
            profile.save(update_fields=["location"])

        self._assert_version_rotates(action)

    def test_user_profile_delete_rotates_search_cache_version(self):
        """Deleting a profile should invalidate homepage search cache."""
        user = self.User.objects.create_user(
            username="signal-profile-delete",
            email="signal-profile-delete@example.com",
            password="pass1234",
        )
        profile = UserProfile.objects.create(user=user, location="Shanghai")

        self._assert_version_rotates(profile.delete)
