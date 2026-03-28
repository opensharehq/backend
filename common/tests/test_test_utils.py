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
        self.assertIs(case.context, context)
        self.assertIs(case.page, page)

        BrowserE2ETestCase.tearDown(case)

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

        new_context, new_page = BrowserE2ETestCase.new_context_page(case)

        browser.new_context.assert_called_once_with(ignore_https_errors=True)
        context.new_page.assert_called_once_with()
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
