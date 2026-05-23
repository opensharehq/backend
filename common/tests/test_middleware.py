"""Tests for custom middleware behavior."""

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from common.middleware import ApiCorsMiddleware


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


@override_settings(CORS_ALLOWED_ORIGINS=["https://app.example.com"])
class ApiCorsMiddlewareTests(SimpleTestCase):
    """Exercise API CORS header handling through the middleware entrypoint."""

    def setUp(self):
        """Create reusable request and middleware helpers."""
        self.factory = RequestFactory()

    def test_options_preflight_sets_expected_cors_headers(self):
        """Allowed API preflights should short-circuit with CORS headers."""
        middleware = ApiCorsMiddleware(lambda request: HttpResponse("unreachable"))
        request = self.factory.options(
            "/api/v1/auth/login",
            HTTP_ORIGIN="https://app.example.com",
        )

        response = middleware(request)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            response["Access-Control-Allow-Origin"],
            "https://app.example.com",
        )
        self.assertEqual(
            response["Access-Control-Allow-Methods"], middleware.allowed_methods
        )
        self.assertEqual(
            response["Access-Control-Allow-Headers"], middleware.allowed_headers
        )
        self.assertNotIn("Access-Control-Allow-Credentials", response.headers)
        self.assertIn("Origin", response["Vary"])

    def test_existing_vary_header_keeps_origin(self):
        """Origin should be appended when the response already varies on headers."""

        def get_response(_request):
            response = HttpResponse("ok")
            response["Vary"] = "Accept-Encoding"
            return response

        middleware = ApiCorsMiddleware(get_response)
        request = self.factory.get(
            "/api/v1/auth/verify",
            HTTP_ORIGIN="https://app.example.com",
        )

        response = middleware(request)

        self.assertEqual(
            {value.strip() for value in response["Vary"].split(",")},
            {"Accept-Encoding", "Origin"},
        )

    def test_bearer_only_policy_strips_credentials_header(self):
        """Cross-origin API responses should not advertise credential mode."""

        def get_response(_request):
            response = HttpResponse("ok")
            response["Access-Control-Allow-Credentials"] = "true"
            return response

        middleware = ApiCorsMiddleware(get_response)
        request = self.factory.get(
            "/api/v1/auth/verify",
            HTTP_ORIGIN="https://app.example.com",
        )

        response = middleware(request)

        self.assertNotIn("Access-Control-Allow-Credentials", response.headers)

    def test_disallowed_origin_does_not_apply_cors_headers(self):
        """Requests from non-allowlisted origins should pass through untouched."""
        middleware = ApiCorsMiddleware(lambda _request: HttpResponse("ok"))
        request = self.factory.get(
            "/api/v1/auth/verify",
            HTTP_ORIGIN="https://evil.example.com",
        )

        response = middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)
