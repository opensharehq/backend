"""Tests for trusted frontend-site request resolution."""

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from common.frontend_sites import (
    FrontendSite,
    default_frontend_site,
    frontend_app_url,
    frontend_site_from_request,
    parse_frontend_site,
    request_frontend_site,
)
from common.middleware import FrontendSiteMiddleware


@override_settings(
    FRONTEND_APP_URL="",
    FRONTEND_CN_APP_URL="https://preview-cn.example",
    FRONTEND_GLOBAL_APP_URL="https://preview-global.example",
    FRONTEND_DEFAULT_SITE="cn",
    CORS_ALLOWED_ORIGINS=["http://localhost:5173"],
)
class FrontendSiteResolutionTests(SimpleTestCase):
    """Resolve canonical domains while rejecting untrusted site markers."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_canonical_origin_selects_site(self):
        cn_request = self.factory.get(
            "/api/v1/shop/items", HTTP_ORIGIN="https://open-share.cn"
        )
        global_request = self.factory.get(
            "/api/v1/shop/items", HTTP_ORIGIN="https://open-share.com"
        )

        self.assertEqual(frontend_site_from_request(cn_request), FrontendSite.CN)
        self.assertEqual(
            frontend_site_from_request(global_request), FrontendSite.GLOBAL
        )

    def test_configured_preview_origin_selects_site(self):
        request = self.factory.get(
            "/api/v1/shop/items", HTTP_ORIGIN="https://preview-global.example"
        )

        self.assertEqual(frontend_site_from_request(request), FrontendSite.GLOBAL)

    def test_referer_is_used_when_origin_is_absent(self):
        request = self.factory.get(
            "/api/v1/auth/social/github/start",
            HTTP_REFERER="https://open-share.com/login",
        )

        self.assertEqual(frontend_site_from_request(request), FrontendSite.GLOBAL)

    def test_production_origin_cannot_be_overridden_by_marker(self):
        request = self.factory.get(
            "/api/v1/shop/items",
            HTTP_ORIGIN="https://open-share.com",
            HTTP_X_OPENSHARE_SITE="cn",
        )

        self.assertEqual(frontend_site_from_request(request), FrontendSite.GLOBAL)

    def test_allowlisted_local_origin_can_use_build_marker(self):
        request = self.factory.get(
            "/api/v1/shop/items",
            HTTP_ORIGIN="http://localhost:5173",
            HTTP_X_OPENSHARE_SITE="global",
        )

        self.assertEqual(frontend_site_from_request(request), FrontendSite.GLOBAL)

    @override_settings(FRONTEND_CN_APP_URL="http://localhost:5173")
    def test_local_configured_origin_can_be_overridden_by_build_marker(self):
        request = self.factory.get(
            "/api/v1/shop/items",
            HTTP_ORIGIN="http://localhost:5173",
            HTTP_X_OPENSHARE_SITE="global",
        )

        self.assertEqual(frontend_site_from_request(request), FrontendSite.GLOBAL)

    def test_unknown_browser_origin_fails_closed(self):
        request = self.factory.get(
            "/api/v1/shop/items",
            HTTP_ORIGIN="https://attacker.example",
            HTTP_X_OPENSHARE_SITE="cn",
        )

        self.assertIsNone(frontend_site_from_request(request))

    def test_no_origin_uses_default_site(self):
        request = self.factory.get("/api/v1/shop/items")

        self.assertEqual(frontend_site_from_request(request), FrontendSite.CN)

    def test_no_origin_accepts_valid_header_marker(self):
        request = self.factory.get("/api/v1/shop/items", HTTP_X_OPENSHARE_SITE="global")

        self.assertEqual(frontend_site_from_request(request), FrontendSite.GLOBAL)

    def test_oauth_query_marker_is_opt_in(self):
        request = self.factory.get(
            "/api/v1/auth/social/github/start?frontend_site=global"
        )

        self.assertEqual(frontend_site_from_request(request), FrontendSite.CN)
        self.assertEqual(
            frontend_site_from_request(request, allow_query_marker=True),
            FrontendSite.GLOBAL,
        )

    def test_middleware_attaches_site_to_request(self):
        def get_response(request):
            self.assertEqual(request.frontend_site, FrontendSite.GLOBAL)
            return HttpResponse("ok")

        request = self.factory.get(
            "/api/v1/shop/items", HTTP_ORIGIN="https://open-share.com"
        )

        response = FrontendSiteMiddleware(get_response)(request)

        self.assertEqual(response.status_code, 200)

    def test_site_value_helpers_cover_invalid_and_legacy_configuration(self):
        self.assertEqual(parse_frontend_site(" CN "), FrontendSite.CN)
        self.assertIsNone(parse_frontend_site("unknown"))
        self.assertEqual(frontend_app_url("global"), "https://preview-global.example")
        self.assertEqual(frontend_app_url("invalid"), "")

        with self.settings(
            FRONTEND_CN_APP_URL="",
            FRONTEND_GLOBAL_APP_URL="",
            FRONTEND_APP_URL="https://legacy.example/",
        ):
            self.assertEqual(frontend_app_url("cn"), "https://legacy.example")
            self.assertEqual(frontend_app_url("global"), "")

        with self.settings(FRONTEND_DEFAULT_SITE="invalid"):
            self.assertEqual(default_frontend_site(), FrontendSite.CN)

    def test_invalid_source_url_and_invalid_allowlist_entries_fail_closed(self):
        request = self.factory.get(
            "/api/v1/shop/items",
            HTTP_ORIGIN="not-an-origin",
            HTTP_X_OPENSHARE_SITE="cn",
        )
        with self.settings(CORS_ALLOWED_ORIGINS=["also-invalid"]):
            self.assertIsNone(frontend_site_from_request(request))

    def test_request_helper_prefers_middleware_value_and_can_resolve_lazily(self):
        attached_request = self.factory.get("/api/v1/shop/items")
        attached_request.frontend_site = "global"
        lazy_request = self.factory.get(
            "/api/v1/shop/items", HTTP_ORIGIN="https://open-share.cn"
        )

        self.assertEqual(request_frontend_site(attached_request), FrontendSite.GLOBAL)
        self.assertEqual(request_frontend_site(lazy_request), FrontendSite.CN)
