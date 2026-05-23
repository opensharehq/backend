"""Common test utilities and mixins for consistent test behavior."""

import os
import re
import time
from urllib.parse import urlparse

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.cache import cache
from django.db import OperationalError
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

    checked_resource_types = {"document", "fetch", "xhr"}
    console_error_allowlist: tuple[str, ...] = ()
    page_error_allowlist: tuple[str, ...] = ()
    request_failure_allowlist: tuple[str, ...] = ()
    http_error_allowlist: tuple[str, ...] = ()

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
        self._tracked_contexts = []
        self._browser_failures = {
            "console": [],
            "page": [],
            "request": [],
            "http": [],
        }
        self.context = self.browser.new_context(ignore_https_errors=True)
        self._tracked_contexts.append(self.context)
        self.page = self._create_monitored_page(self.context)

    def tearDown(self):
        """Close per-test browser resources."""
        try:
            self.assert_browser_clean()
        finally:
            while self._tracked_contexts:
                self._tracked_contexts.pop().close()
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
        self._tracked_contexts.append(context)
        page = self._create_monitored_page(context)
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

    def wait_for_database(self, operation, *, timeout=2.0, interval=0.05):
        """
        Retry a database-backed browser assertion until the live request settles.

        SQLite can briefly report table locks when a live-server request and the
        test thread touch the same table at the same time. This helper keeps
        those waits explicit at the assertion boundary.
        """
        deadline = time.monotonic() + timeout
        last_error = None

        while True:
            try:
                return operation()
            except OperationalError as exc:
                if not self._is_sqlite_lock_error(exc):
                    raise
                last_error = exc
            except AssertionError as exc:
                last_error = exc

            if time.monotonic() >= deadline:
                raise last_error

            time.sleep(interval)

    def assert_browser_clean(self):
        """Fail the test when the browser captured unexpected frontend errors."""
        failures = []
        for key, label in (
            ("page", "page errors"),
            ("console", "console errors"),
            ("request", "request failures"),
            ("http", "server errors"),
        ):
            entries = self._browser_failures[key]
            if entries:
                failures.append(f"{label}: {'; '.join(entries)}")

        if failures:
            self.fail("Unexpected browser errors detected: " + " | ".join(failures))

    def allow_console_error(self, pattern):
        """Allow a console error matching the given regex pattern."""
        self.console_error_allowlist = (*self.console_error_allowlist, pattern)

    def allow_page_error(self, pattern):
        """Allow a page error matching the given regex pattern."""
        self.page_error_allowlist = (*self.page_error_allowlist, pattern)

    def allow_request_failure(self, pattern):
        """Allow a failed request matching the given regex pattern."""
        self.request_failure_allowlist = (*self.request_failure_allowlist, pattern)

    def allow_http_error(self, pattern):
        """Allow a same-origin 5xx response matching the given regex pattern."""
        self.http_error_allowlist = (*self.http_error_allowlist, pattern)

    def _create_monitored_page(self, context):
        """Create a page with frontend error listeners attached."""
        page = context.new_page()
        page.on("console", self._handle_console_message)
        page.on("pageerror", self._handle_page_error)
        page.on("requestfailed", self._handle_request_failed)
        page.on("response", self._handle_response)
        return page

    def _handle_console_message(self, message):
        """Record unexpected same-origin console errors."""
        if self._playwright_value(message, "type") != "error":
            return

        location = self._playwright_value(message, "location") or {}
        url = location.get("url") or self.page.url
        text = self._playwright_value(message, "text") or ""
        entry = f"{url}: {text}"

        if not self._is_same_origin(url) or self._is_allowed(
            entry, self.console_error_allowlist
        ):
            return

        self._browser_failures["console"].append(entry)

    def _handle_page_error(self, error):
        """Record unexpected page-level JavaScript errors."""
        entry = str(error)
        if self._is_allowed(entry, self.page_error_allowlist):
            return
        self._browser_failures["page"].append(entry)

    def _handle_request_failed(self, request):
        """Record failed same-origin document/xhr/fetch requests."""
        url = self._playwright_value(request, "url")
        resource_type = self._playwright_value(request, "resource_type")
        if resource_type not in self.checked_resource_types or not self._is_same_origin(
            url
        ):
            return

        failure = self._playwright_value(request, "failure") or {}
        if isinstance(failure, dict):
            failure_text = failure.get("errorText", "request failed")
        else:
            failure_text = str(failure)
        entry = f"{resource_type} {url}: {failure_text}"
        if self._is_allowed(entry, self.request_failure_allowlist):
            return
        self._browser_failures["request"].append(entry)

    def _handle_response(self, response):
        """Record same-origin 5xx document/xhr/fetch responses."""
        request = self._playwright_value(response, "request")
        resource_type = self._playwright_value(request, "resource_type")
        url = self._playwright_value(response, "url")
        status = self._playwright_value(response, "status")

        if (
            resource_type not in self.checked_resource_types
            or not self._is_same_origin(url)
            or status < 500
        ):
            return

        entry = f"{status} {resource_type} {url}"
        if self._is_allowed(entry, self.http_error_allowlist):
            return
        self._browser_failures["http"].append(entry)

    @staticmethod
    def _playwright_value(obj, attr):
        """Read Playwright values regardless of property or zero-arg method style."""
        value = getattr(obj, attr)
        return value() if callable(value) else value

    def _is_same_origin(self, url):
        """Return whether a URL belongs to the Django live server origin."""
        if not url:
            return False
        return urlparse(url).netloc == urlparse(self.live_server_url).netloc

    @staticmethod
    def _is_sqlite_lock_error(error):
        """Return whether an OperationalError is a transient SQLite lock."""
        message = str(error).lower()
        return "database table is locked" in message or "database is locked" in message

    @staticmethod
    def _is_allowed(entry, patterns):
        """Check whether an error entry matches any allowlisted regex."""
        return any(re.search(pattern, entry) for pattern in patterns)
