"""Tests for homepage cache version utilities."""

from django.core.cache import cache
from django.test import TestCase, override_settings

from homepage.cache import (
    SEARCH_CACHE_VERSION_KEY,
    bump_search_cache_version,
    get_search_cache_version,
)


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class HomepageCacheVersionTests(TestCase):
    """Cover atomic cache version generation and rotation behavior."""

    def setUp(self):
        """Reset cache state to keep each test isolated."""
        cache.clear()

    def test_get_search_cache_version_initializes_and_reuses_value(self):
        """The version is lazily initialized once and then reused."""
        first = get_search_cache_version()
        second = get_search_cache_version()

        self.assertIsInstance(first, str)
        self.assertEqual(first, second)
        self.assertEqual(cache.get(SEARCH_CACHE_VERSION_KEY), first)

    def test_bump_search_cache_version_rotates_value(self):
        """Bumping the version invalidates prior cache keys."""
        initial = get_search_cache_version()

        bump_search_cache_version()
        updated = get_search_cache_version()

        self.assertNotEqual(initial, updated)
        self.assertEqual(cache.get(SEARCH_CACHE_VERSION_KEY), updated)

    def test_bump_search_cache_version_sets_value_when_missing(self):
        """Bump works even when no version was initialized before."""
        cache.delete(SEARCH_CACHE_VERSION_KEY)

        bump_search_cache_version()
        version = cache.get(SEARCH_CACHE_VERSION_KEY)

        self.assertIsInstance(version, str)
        self.assertTrue(version)
