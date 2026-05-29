"""Tests for social-auth helper utilities."""

from django.test import TestCase, override_settings

from accounts.social_auth import (
    FrontendSocialCallbackNotConfigured,
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
            is_api_social_callback_target("/api/v1/auth/social/github/callback", "github"),
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
