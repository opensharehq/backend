"""Common test utilities and mixins for consistent test behavior."""

import os

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.cache import cache
from django.test import TestCase
from playwright.sync_api import sync_playwright


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


class BrowserE2ETestCase(CacheClearMixin, StaticLiveServerTestCase):
    """
    Shared browser test base using Django's live server and Playwright Chromium.

    Each test gets an isolated browser context so cookies, local storage, and
    session state do not leak across journeys.
    """

    @classmethod
    def setUpClass(cls):
        """Launch a shared Chromium browser for the test class."""
        super().setUpClass()
        cls._previous_async_unsafe = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        cls._playwright = sync_playwright().start()
        cls.browser = cls._playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        """Close browser resources after the class finishes."""
        cls.browser.close()
        cls._playwright.stop()
        if cls._previous_async_unsafe is None:
            os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
        else:
            os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = cls._previous_async_unsafe
        super().tearDownClass()

    def setUp(self):
        """Create a fresh browser context and page for each test."""
        super().setUp()
        self.context = self.browser.new_context(ignore_https_errors=True)
        self.page = self.context.new_page()

    def tearDown(self):
        """Close per-test browser resources."""
        self.context.close()
        super().tearDown()

    def absolute_url(self, path):
        """Build a live-server URL from either a relative path or full URL."""
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.live_server_url}{path}"

    def goto(self, path):
        """Open a page and wait for network activity to settle."""
        self.page.goto(self.absolute_url(path), wait_until="networkidle")

    def new_context_page(self):
        """Create a second isolated page, useful for multi-user flows."""
        context = self.browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        return context, page

    def login_via_ui(self, login_id, password):
        """Authenticate through the normal sign-in form."""
        self.goto("/accounts/login/")
        self.page.fill("#login-id", login_id)
        self.page.fill("#password", password)
        self.page.locator("form#loginForm button[type='submit']").click()
        self.page.wait_for_load_state("networkidle")

    def login_admin_via_ui(self, username, password):
        """Authenticate through Django Admin's login form."""
        self.goto("/admin/login/")
        self.page.fill("#id_username", username)
        self.page.fill("#id_password", password)
        self.page.locator("input[type='submit']").click()
        self.page.wait_for_load_state("networkidle")

    def assert_page_contains(self, text):
        """Assert that the current page body contains text."""
        self.assertIn(text, self.page.locator("body").inner_text())
