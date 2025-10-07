"""Common test utilities and mixins for consistent test behavior."""

from django.core.cache import cache
from django.test import TestCase


class CacheClearMixin:
    """
    Mixin to clear cache before and after each test.

    This ensures cache isolation between tests, especially important
    for parallel test execution.
    """

    def setUp(self):
        """Clear cache before each test."""
        super().setUp()
        cache.clear()

    def tearDown(self):
        """Clear cache after each test."""
        cache.clear()
        super().tearDown()


class CacheClearTestCase(CacheClearMixin, TestCase):
    """
    TestCase that automatically clears cache before and after each test.

    Use this as a base class for tests that interact with cached data
    to ensure test isolation in parallel execution.
    """

    pass
