"""Integration tests for canonical host redirection middleware."""

from django.test import TestCase, override_settings


@override_settings(ALLOWED_HOSTS=["open-share.cn", "www.open-share.cn"])
class CanonicalHostRedirectIntegrationTests(TestCase):
    """Exercise the middleware through Django's real request stack."""

    def test_www_requests_redirect_to_apex_domain(self):
        """Requests for the www host should redirect before the view runs."""
        response = self.client.get("/", HTTP_HOST="www.open-share.cn")

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "https://open-share.cn/")

    def test_redirect_preserves_path_and_query_string(self):
        """Redirect responses should keep the original path and query string."""
        response = self.client.get(
            "/search/?q=django",
            HTTP_HOST="www.open-share.cn",
        )

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "https://open-share.cn/search/?q=django")
