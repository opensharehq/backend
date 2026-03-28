"""Tests for CanonicalHostRedirectMiddleware to ensure canonical host enforcement."""

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from common.middleware import CanonicalHostRedirectMiddleware


@override_settings(
    ALLOWED_HOSTS=["open-share.cn", "www.open-share.cn"],
    USE_X_FORWARDED_HOST=True,
    USE_X_FORWARDED_PORT=True,
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
)
class CanonicalHostRedirectMiddlewareTests(SimpleTestCase):
    """Validate the canonical host middleware behavior across host/port variations."""

    def setUp(self):
        """Build a request factory and middleware instance shared by each test."""
        self.factory = RequestFactory()
        self.middleware = CanonicalHostRedirectMiddleware(
            lambda request: HttpResponse("OK")
        )

    def test_redirects_from_www_to_apex_domain(self):
        """Requests for the www domain are redirected to the apex host."""
        request = self.factory.get("/", HTTP_HOST="www.open-share.cn")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], "https://open-share.cn/")

    def test_preserves_https_scheme(self):
        """HTTPS requests remain HTTPS after redirection."""
        request = self.factory.get("/", secure=True, HTTP_HOST="www.open-share.cn")
        response = self.middleware(request)

        self.assertEqual(response.headers["Location"], "https://open-share.cn/")

    def test_forwarded_proto_marks_request_secure(self):
        """Trusted forwarded proto headers trigger secure redirects."""
        request = self.factory.get(
            "/",
            HTTP_HOST="www.open-share.cn",
            HTTP_X_FORWARDED_PROTO="https",
        )
        response = self.middleware(request)

        self.assertEqual(response.headers["Location"], "https://open-share.cn/")

    def test_preserves_path_and_query_string(self):
        """Redirects should keep the original path and query string."""
        request = self.factory.get(
            "/community/search/",
            {"q": "django", "location": "上海"},
            HTTP_HOST="www.open-share.cn",
        )
        response = self.middleware(request)

        self.assertEqual(
            response.headers["Location"],
            "https://open-share.cn/community/search/?q=django&location=%E4%B8%8A%E6%B5%B7",
        )

    def test_redirect_is_case_insensitive_for_matching_host(self):
        """Uppercase host headers should still redirect to the canonical host."""
        request = self.factory.get("/team/", HTTP_HOST="WWW.OPEN-SHARE.CN")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], "https://open-share.cn/team/")

    def test_does_not_append_backend_port_when_host_omits_it(self):
        """When the host omits a port, the redirect should omit it as well."""
        request = self.factory.get(
            "/", HTTP_HOST="www.open-share.cn", SERVER_PORT="8000"
        )
        request.META["SERVER_PORT"] = "8000"
        response = self.middleware(request)

        self.assertEqual(response.headers["Location"], "https://open-share.cn/")

    def test_keeps_custom_port(self):
        """Ports specified in the host header persist after redirection."""
        request = self.factory.get("/", HTTP_HOST="www.open-share.cn:8443")
        response = self.middleware(request)

        self.assertEqual(response.headers["Location"], "https://open-share.cn/")

    def test_uses_forwarded_port_header_when_present(self):
        """Forwarded-port headers override the backend port when provided."""
        request = self.factory.get(
            "/",
            secure=True,
            HTTP_HOST="www.open-share.cn",
            HTTP_X_FORWARDED_PORT="8443",
        )
        response = self.middleware(request)

        self.assertEqual(response.headers["Location"], "https://open-share.cn/")

    def test_other_hosts_pass_through(self):
        """Requests that already target the canonical host pass through."""
        request = self.factory.get("/", HTTP_HOST="open-share.cn")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"OK")

    @override_settings(
        ALLOWED_HOSTS=["open-share.cn", "www.open-share.cn", "blog.open-share.cn"]
    )
    def test_non_www_subdomains_pass_through(self):
        """Hosts outside the configured www alias should not be redirected."""
        request = self.factory.get("/", HTTP_HOST="blog.open-share.cn")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"OK")

    def test_determine_port_prefers_host_port(self):
        """Explicit host port should be returned before forwarded headers."""
        request = self.factory.get("/", HTTP_HOST="www.open-share.cn:8443")
        self.assertEqual(self.middleware._determine_port("8443", request), "8443")

    def test_determine_port_uses_forwarded_when_no_host_port(self):
        """Forwarded port header is used when host header omits a port."""
        request = self.factory.get(
            "/",
            HTTP_HOST="www.open-share.cn",
            HTTP_X_FORWARDED_PORT="9000",
        )
        self.assertEqual(self.middleware._determine_port("", request), "9000")

    def test_determine_port_defaults_to_empty_string(self):
        """If neither host nor forwarded ports are set, return an empty string."""
        request = self.factory.get("/", HTTP_HOST="www.open-share.cn")
        self.assertEqual(self.middleware._determine_port("", request), "")
