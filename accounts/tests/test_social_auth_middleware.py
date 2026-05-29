"""Tests for social-auth helper utilities."""

from urllib.parse import parse_qs, urlparse

from django.http import HttpResponseRedirect
from django.test import RequestFactory, TestCase, override_settings
from social_core.exceptions import AuthFailed

from accounts.social_auth import (
    FrontendSocialCallbackNotConfigured,
    SocialAuthGenericExceptionMiddleware,
    build_frontend_social_callback_url,
    is_api_social_callback_target,
    social_api_callback_path,
)


class SocialAuthHelperTests(TestCase):
    """Verify the SPA-handoff helpers used by the social-login flow."""

    def test_social_api_callback_path_uses_provider_segment(self):
        """The API callback path should embed the provider name."""
        self.assertEqual(
            social_api_callback_path("github"),
            "/api/v1/auth/social/github/callback",
        )

    def test_is_api_social_callback_target_matches_path(self):
        """The helper should detect both bare paths and full URLs."""
        self.assertTrue(
            is_api_social_callback_target(
                "/api/v1/auth/social/github/callback", "github"
            ),
        )
        self.assertTrue(
            is_api_social_callback_target(
                "https://example.com/api/v1/auth/social/github/callback",
                "github",
            ),
        )
        self.assertFalse(is_api_social_callback_target(None, "github"))
        self.assertFalse(is_api_social_callback_target("/elsewhere", "github"))

    @override_settings(
        FRONTEND_APP_URL="https://frontend.example/",
        FRONTEND_SOCIAL_CALLBACK_PATH="/auth/social/callback",
    )
    def test_build_frontend_social_callback_url_includes_query_params(self):
        """Helper should encode provider and extra params into the SPA URL."""
        url = build_frontend_social_callback_url("github", error="boom")
        self.assertEqual(
            url,
            "https://frontend.example/auth/social/callback?provider=github&error=boom",
        )

    @override_settings(FRONTEND_APP_URL="")
    def test_build_frontend_social_callback_url_requires_frontend_app_url(self):
        """Missing frontend URL should raise a stable configuration error."""
        with self.assertRaises(FrontendSocialCallbackNotConfigured):
            build_frontend_social_callback_url("github")


@override_settings(
    FRONTEND_APP_URL="https://frontend.example",
    FRONTEND_SOCIAL_CALLBACK_PATH="/auth/social/callback",
)
class SocialAuthGenericExceptionMiddlewareTests(TestCase):
    """Verify the generic-exception fallback for the social-auth flow."""

    def setUp(self):
        """Build a middleware instance with an unused get_response stub."""
        self.factory = RequestFactory()
        self.middleware = SocialAuthGenericExceptionMiddleware(
            get_response=lambda request: None,
        )

    def test_redirects_to_spa_callback_on_generic_exception(self):
        """Network/HTTP errors during /complete/<provider>/ should redirect."""
        request = self.factory.get("/complete/github/")

        response = self.middleware.process_exception(
            request, ConnectionError("upstream OAuth provider unreachable")
        )

        self.assertIsInstance(response, HttpResponseRedirect)
        parsed = urlparse(response.url)
        self.assertEqual(parsed.netloc, "frontend.example")
        self.assertEqual(parsed.path, "/auth/social/callback")
        query = parse_qs(parsed.query)
        self.assertEqual(query["provider"], ["github"])
        self.assertEqual(query["error"], ["authentication_failed"])

    def test_skips_social_auth_base_exceptions(self):
        """SocialAuthBaseException must be left to social-django's middleware."""
        request = self.factory.get("/complete/github/")

        response = self.middleware.process_exception(
            request, AuthFailed("github", "denied")
        )

        self.assertIsNone(response)

    def test_ignores_non_social_paths(self):
        """Errors outside the social-auth flow must not be intercepted."""
        request = self.factory.get("/api/v1/auth/me")

        response = self.middleware.process_exception(
            request, ConnectionError("unrelated")
        )

        self.assertIsNone(response)

    def test_ignores_social_paths_without_provider(self):
        """Paths missing a provider segment should not redirect."""
        request = self.factory.get("/complete/")

        response = self.middleware.process_exception(request, ConnectionError("boom"))

        self.assertIsNone(response)

    @override_settings(FRONTEND_APP_URL="")
    def test_falls_through_when_frontend_url_not_configured(self):
        """Without a frontend URL the middleware should not mask the error."""
        request = self.factory.get("/complete/github/")

        response = self.middleware.process_exception(request, ConnectionError("boom"))

        self.assertIsNone(response)
