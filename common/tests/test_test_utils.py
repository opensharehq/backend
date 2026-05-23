"""Focused coverage for shared test helpers."""

import os
from unittest.mock import Mock, call, patch

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import SimpleTestCase

from common.test_utils import BrowserE2ETestCase


class DummyBrowserCase(BrowserE2ETestCase):
    """Minimal subclass used to exercise BrowserE2ETestCase helpers."""

    def runTest(self):
        """Satisfy unittest.TestCase initialization for helper instances."""
        return None


class BrowserE2ETestCaseTests(SimpleTestCase):
    """Cover helper branches without starting a real live server or browser."""

    def make_case(self):
        """Create a lightweight BrowserE2ETestCase instance for helper tests."""
        case = DummyBrowserCase(methodName="runTest")
        case.live_server_url = "http://localhost:8000"
        return case

    @patch.object(StaticLiveServerTestCase, "tearDownClass")
    @patch.object(StaticLiveServerTestCase, "setUpClass")
    @patch("common.test_utils.sync_playwright")
    def test_setup_and_teardown_class_manage_browser_and_env(
        self,
        mock_sync_playwright,
        mock_parent_setup,
        mock_parent_teardown,
    ):
        """Class lifecycle launches and stops Playwright while restoring env."""
        browser = Mock()
        playwright = Mock()
        playwright.chromium.launch.return_value = browser
        mock_sync_playwright.return_value.start.return_value = playwright

        previous_value = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "preserve-me"
        try:
            DummyBrowserCase.setUpClass()

            self.assertEqual(os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"], "true")
            playwright.chromium.launch.assert_called_once_with(headless=True)
            mock_parent_setup.assert_called_once()

            DummyBrowserCase.tearDownClass()

            browser.close.assert_called_once()
            playwright.stop.assert_called_once()
            self.assertEqual(os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"], "preserve-me")
            mock_parent_teardown.assert_called_once()
        finally:
            if previous_value is None:
                os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
            else:
                os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = previous_value

    @patch("common.test_utils.CacheClearMixin.tearDown")
    @patch("common.test_utils.CacheClearMixin.setUp")
    def test_setup_and_teardown_manage_context_lifecycle(
        self,
        mock_parent_setup,
        mock_parent_teardown,
    ):
        """Per-test lifecycle creates and closes an isolated browser context."""
        page = Mock()
        context = Mock()
        context.new_page.return_value = page
        browser = Mock()
        browser.new_context.return_value = context

        case = self.make_case()
        case.browser = browser

        BrowserE2ETestCase.setUp(case)

        mock_parent_setup.assert_called_once()
        browser.new_context.assert_called_once_with(ignore_https_errors=True)
        context.new_page.assert_called_once_with()
        self.assertEqual(
            page.on.call_args_list,
            [
                call("console", case._handle_console_message),
                call("pageerror", case._handle_page_error),
                call("requestfailed", case._handle_request_failed),
                call("response", case._handle_response),
            ],
        )
        self.assertIs(case.context, context)
        self.assertIs(case.page, page)
        self.assertEqual(case._tracked_contexts, [context])

        case.assert_browser_clean = Mock()
        BrowserE2ETestCase.tearDown(case)

        case.assert_browser_clean.assert_called_once_with()
        context.close.assert_called_once_with()
        mock_parent_teardown.assert_called_once()

    def test_new_context_page_returns_fresh_page_pair(self):
        """Secondary page helper returns both the new context and page."""
        page = Mock()
        context = Mock()
        context.new_page.return_value = page
        browser = Mock()
        browser.new_context.return_value = context

        case = self.make_case()
        case.browser = browser
        case._tracked_contexts = []

        new_context, new_page = BrowserE2ETestCase.new_context_page(case)

        browser.new_context.assert_called_once_with(ignore_https_errors=True)
        context.new_page.assert_called_once_with()
        self.assertEqual(
            page.on.call_args_list,
            [
                call("console", case._handle_console_message),
                call("pageerror", case._handle_page_error),
                call("requestfailed", case._handle_request_failed),
                call("response", case._handle_response),
            ],
        )
        self.assertEqual(case._tracked_contexts, [context])
        self.assertIs(new_context, context)
        self.assertIs(new_page, page)

    def test_login_helpers_fill_forms_and_submit(self):
        """User and admin login helpers drive the expected page interactions."""
        page = Mock()
        submit_button = Mock()
        page.locator.return_value = submit_button

        case = self.make_case()
        case.page = page
        case.goto = Mock()

        BrowserE2ETestCase.login_via_ui(case, "demo-user", "UserPass123!")

        case.goto.assert_called_once_with("/accounts/login/")
        page.fill.assert_has_calls(
            [
                call("#login-id", "demo-user"),
                call("#password", "UserPass123!"),
            ]
        )
        page.locator.assert_called_with("form#loginForm button[type='submit']")
        submit_button.click.assert_called_once_with()
        page.wait_for_load_state.assert_called_once_with("networkidle")

        page.reset_mock()
        submit_button.reset_mock()
        case.goto.reset_mock()

        BrowserE2ETestCase.login_admin_via_ui(case, "admin-user", "AdminPass123!")

        case.goto.assert_called_once_with("/admin/login/")
        page.fill.assert_has_calls(
            [
                call("#id_username", "admin-user"),
                call("#id_password", "AdminPass123!"),
            ]
        )
        page.locator.assert_called_with("input[type='submit']")
        submit_button.click.assert_called_once_with()
        page.wait_for_load_state.assert_called_once_with("networkidle")

    def test_url_navigation_and_text_assertion_helpers(self):
        """URL helpers should normalize paths and page text assertions."""
        page = Mock()
        page.locator.return_value.inner_text.return_value = "Hello OpenShare"
        case = self.make_case()
        case.page = page

        self.assertEqual(
            BrowserE2ETestCase.absolute_url(case, "https://example.com/a"),
            "https://example.com/a",
        )
        self.assertEqual(
            BrowserE2ETestCase.absolute_url(case, "/dashboard/"),
            "http://localhost:8000/dashboard/",
        )

        BrowserE2ETestCase.goto(case, "/dashboard/")
        page.goto.assert_called_once_with(
            "http://localhost:8000/dashboard/",
            wait_until="networkidle",
        )
        BrowserE2ETestCase.assert_page_contains(case, "OpenShare")

    def test_assert_browser_clean_reports_collected_failures(self):
        """Collected browser failures should fail the test with readable output."""
        case = self.make_case()
        case._browser_failures = {
            "console": ["http://localhost:8000/page: boom"],
            "page": ["ReferenceError: broken"],
            "request": ["fetch http://localhost:8000/api/: net::ERR_FAILED"],
            "http": ["500 fetch http://localhost:8000/api/"],
        }

        with self.assertRaises(AssertionError) as exc:
            BrowserE2ETestCase.assert_browser_clean(case)

        message = str(exc.exception)
        self.assertIn("console errors", message)
        self.assertIn("page errors", message)
        self.assertIn("request failures", message)
        self.assertIn("server errors", message)

    def test_allowlist_helpers_append_patterns(self):
        """Allowlist helpers should extend the regex pattern tuples."""
        case = self.make_case()

        BrowserE2ETestCase.allow_console_error(case, r"console")
        BrowserE2ETestCase.allow_page_error(case, r"page")
        BrowserE2ETestCase.allow_request_failure(case, r"request")
        BrowserE2ETestCase.allow_http_error(case, r"http")

        self.assertEqual(case.console_error_allowlist, (r"console",))
        self.assertEqual(case.page_error_allowlist, (r"page",))
        self.assertEqual(case.request_failure_allowlist, (r"request",))
        self.assertEqual(case.http_error_allowlist, (r"http",))

    def test_console_handler_records_same_origin_errors_only(self):
        """Console errors should be filtered by origin and allowlist."""
        case = self.make_case()
        case.page = Mock(url="http://localhost:8000/current/")
        case._browser_failures = {"console": [], "page": [], "request": [], "http": []}
        console_message = Mock()
        console_message.type.return_value = "error"
        console_message.text.return_value = "boom"
        console_message.location.return_value = {"url": "http://localhost:8000/app.js"}

        BrowserE2ETestCase._handle_console_message(case, console_message)

        self.assertEqual(
            case._browser_failures["console"],
            ["http://localhost:8000/app.js: boom"],
        )

        case._browser_failures["console"].clear()
        console_message.location.return_value = {"url": "https://cdn.example/app.js"}
        BrowserE2ETestCase._handle_console_message(case, console_message)
        self.assertEqual(case._browser_failures["console"], [])

        case.allow_console_error(r"boom")
        console_message.location.return_value = {"url": "http://localhost:8000/app.js"}
        BrowserE2ETestCase._handle_console_message(case, console_message)
        self.assertEqual(case._browser_failures["console"], [])

        case._browser_failures["console"].clear()
        console_message.type.return_value = "warning"
        BrowserE2ETestCase._handle_console_message(case, console_message)
        self.assertEqual(case._browser_failures["console"], [])

    def test_page_and_request_handlers_respect_allowlists(self):
        """Page, request, and HTTP handlers should capture unexpected failures."""
        case = self.make_case()
        case._browser_failures = {"console": [], "page": [], "request": [], "http": []}

        BrowserE2ETestCase._handle_page_error(case, RuntimeError("broken page"))
        self.assertEqual(case._browser_failures["page"], ["broken page"])

        case._browser_failures["page"].clear()
        case.allow_page_error(r"ignored")
        BrowserE2ETestCase._handle_page_error(case, RuntimeError("ignored issue"))
        self.assertEqual(case._browser_failures["page"], [])

        request = Mock()
        request.url.return_value = "http://localhost:8000/api/preview/"
        request.resource_type.return_value = "fetch"
        request.failure.return_value = {"errorText": "net::ERR_FAILED"}
        BrowserE2ETestCase._handle_request_failed(case, request)
        self.assertEqual(
            case._browser_failures["request"],
            ["fetch http://localhost:8000/api/preview/: net::ERR_FAILED"],
        )

        response = Mock()
        response.url.return_value = "http://localhost:8000/api/preview/"
        response.status.return_value = 500
        response.request.return_value = request
        BrowserE2ETestCase._handle_response(case, response)
        self.assertEqual(
            case._browser_failures["http"],
            ["500 fetch http://localhost:8000/api/preview/"],
        )

        case._browser_failures["request"].clear()
        case._browser_failures["http"].clear()
        case.allow_request_failure(r"ERR_FAILED")
        case.allow_http_error(r"500")
        BrowserE2ETestCase._handle_request_failed(case, request)
        BrowserE2ETestCase._handle_response(case, response)
        self.assertEqual(case._browser_failures["request"], [])
        self.assertEqual(case._browser_failures["http"], [])

        case._browser_failures["request"].clear()
        request.failure.return_value = "socket hang up"
        BrowserE2ETestCase._handle_request_failed(case, request)
        self.assertEqual(
            case._browser_failures["request"],
            ["fetch http://localhost:8000/api/preview/: socket hang up"],
        )

        case._browser_failures["request"].clear()
        request.resource_type.return_value = "image"
        BrowserE2ETestCase._handle_request_failed(case, request)
        self.assertEqual(case._browser_failures["request"], [])

        request.resource_type.return_value = "fetch"
        request.url.return_value = "https://cdn.example/api/preview/"
        BrowserE2ETestCase._handle_request_failed(case, request)
        self.assertEqual(case._browser_failures["request"], [])

        case._browser_failures["http"].clear()
        request.resource_type.return_value = "fetch"
        response.url.return_value = "http://localhost:8000/api/preview/"
        response.status.return_value = 499
        BrowserE2ETestCase._handle_response(case, response)
        self.assertEqual(case._browser_failures["http"], [])

    def test_helper_utilities_cover_origin_and_regex_helpers(self):
        """Static helpers should normalize common checks."""
        case = self.make_case()

        self.assertTrue(
            BrowserE2ETestCase._is_same_origin(case, "http://localhost:8000/a")
        )
        self.assertFalse(
            BrowserE2ETestCase._is_same_origin(case, "https://example.com")
        )
        self.assertFalse(BrowserE2ETestCase._is_same_origin(case, ""))
        self.assertTrue(BrowserE2ETestCase._is_allowed("boom", [r"boom"]))
        self.assertEqual(
            BrowserE2ETestCase._playwright_value(
                Mock(answer=Mock(return_value=3)), "answer"
            ),
            3,
        )
