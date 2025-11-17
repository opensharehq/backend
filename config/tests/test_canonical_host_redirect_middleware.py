from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from common.middleware import CanonicalHostRedirectMiddleware


@override_settings(ALLOWED_HOSTS=["open-share.cn", "www.open-share.cn"])
class CanonicalHostRedirectMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = CanonicalHostRedirectMiddleware(lambda request: HttpResponse("OK"))

    def test_redirects_to_www_domain(self):
        request = self.factory.get("/", HTTP_HOST="open-share.cn")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.headers["Location"], "http://www.open-share.cn/")

    def test_preserves_https_scheme(self):
        request = self.factory.get("/", secure=True, HTTP_HOST="open-share.cn")
        response = self.middleware(request)

        self.assertEqual(response.headers["Location"], "https://www.open-share.cn/")

    def test_keeps_custom_port(self):
        request = self.factory.get("/", HTTP_HOST="open-share.cn:8443")
        response = self.middleware(request)

        self.assertEqual(response.headers["Location"], "http://www.open-share.cn:8443/")

    def test_other_hosts_pass_through(self):
        request = self.factory.get("/", HTTP_HOST="www.open-share.cn")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"OK")
