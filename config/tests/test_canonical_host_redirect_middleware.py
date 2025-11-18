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

    def test_redirects_to_www_domain(self):
        """Requests for the bare domain move to the www host."""
        request = self.factory.get("/", HTTP_HOST="open-share.cn")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], "http://www.open-share.cn/")

    def test_preserves_https_scheme(self):
        """HTTPS requests remain HTTPS after redirection."""
        request = self.factory.get("/", secure=True, HTTP_HOST="open-share.cn")
        response = self.middleware(request)

        self.assertEqual(response.headers["Location"], "https://www.open-share.cn/")

    def test_forwarded_proto_marks_request_secure(self):
        """Trusted forwarded proto headers trigger secure redirects."""
        request = self.factory.get(
            "/",
            HTTP_HOST="open-share.cn",
            HTTP_X_FORWARDED_PROTO="https",
        )
        response = self.middleware(request)

        self.assertEqual(response.headers["Location"], "https://www.open-share.cn/")

    def test_does_not_append_backend_port_when_host_omits_it(self):
        """When the host omits a port, the redirect should omit it as well."""
        request = self.factory.get("/", HTTP_HOST="open-share.cn", SERVER_PORT="8000")
        request.META["SERVER_PORT"] = "8000"
        response = self.middleware(request)

        self.assertEqual(response.headers["Location"], "http://www.open-share.cn/")

    def test_keeps_custom_port(self):
        """Ports specified in the host header persist after redirection."""
        request = self.factory.get("/", HTTP_HOST="open-share.cn:8443")
        response = self.middleware(request)

        self.assertEqual(response.headers["Location"], "http://www.open-share.cn:8443/")

    def test_uses_forwarded_port_header_when_present(self):
        """Forwarded-port headers override the backend port when provided."""
        request = self.factory.get(
            "/",
            secure=True,
            HTTP_HOST="open-share.cn",
            HTTP_X_FORWARDED_PORT="8443",
        )
        response = self.middleware(request)

        self.assertEqual(
            response.headers["Location"], "https://www.open-share.cn:8443/"
        )

    def test_other_hosts_pass_through(self):
        """Requests that already target the canonical host pass through."""
        request = self.factory.get("/", HTTP_HOST="www.open-share.cn")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"OK")
