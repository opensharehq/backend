"""Tests for social-auth exception handling middleware."""

from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.social_auth import EMAIL_CONFLICT_ERROR_CODE, EmailConflictRequiresBinding


class SocialAuthExceptionMiddlewareTests(TestCase):
    """Verify known social-auth exceptions redirect to the right surface."""

    @staticmethod
    def _raise_email_conflict(backend, *args, **kwargs):
        """Raise the custom social-auth conflict exception."""
        raise EmailConflictRequiresBinding(backend)

    @patch("social_django.views.do_complete")
    def test_web_social_conflict_redirects_to_sign_in_with_message(
        self,
        do_complete_mock,
    ):
        """Web social login conflicts should return users to the sign-in page."""
        do_complete_mock.side_effect = self._raise_email_conflict

        response = self.client.get(
            reverse("social:complete", args=["github"]),
            follow=True,
        )

        self.assertRedirects(response, reverse("accounts:sign_in"))
        messages = list(response.context["messages"])
        self.assertTrue(
            any("该邮箱已绑定现有账号" in str(message) for message in messages)
        )

    @override_settings(
        FRONTEND_APP_URL="https://frontend.example",
        FRONTEND_SOCIAL_CALLBACK_PATH="/auth/social/callback",
    )
    @patch("social_django.views.do_complete")
    def test_api_social_conflict_redirects_to_frontend_callback(
        self,
        do_complete_mock,
    ):
        """API-initiated social login conflicts should return to the SPA callback."""
        do_complete_mock.side_effect = self._raise_email_conflict

        response = self.client.get(
            f"{reverse('social:complete', args=['github'])}"
            "?next=/api/v1/auth/social/github/callback"
        )

        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlparse(response.url).query)
        self.assertEqual(query["provider"], ["github"])
        self.assertEqual(query["error"], [EMAIL_CONFLICT_ERROR_CODE])
