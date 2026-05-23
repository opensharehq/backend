"""OWASP-aligned HTTP security regression tests."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from messages.models import Message, UserMessage

User = get_user_model()


@override_settings(
    ALLOWED_HOSTS=["testserver"],
    SECURE_HSTS_SECONDS=31536000,
    SECURE_HSTS_INCLUDE_SUBDOMAINS=True,
    SECURE_HSTS_PRELOAD=True,
    SECURE_CONTENT_TYPE_NOSNIFF=True,
    X_FRAME_OPTIONS="DENY",
    SECURE_REFERRER_POLICY="same-origin",
    SECURE_CROSS_ORIGIN_OPENER_POLICY="same-origin",
)
class SecurityHeadersTests(TestCase):
    """Verify baseline security headers on secure responses."""

    def test_homepage_includes_core_security_headers_over_https(self):
        response = self.client.get(
            reverse("homepage:index"),
            secure=True,
            HTTP_HOST="testserver",
        )

        self.assertEqual(
            response["Strict-Transport-Security"],
            "max-age=31536000; includeSubDomains; preload",
        )
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertEqual(
            response["Cross-Origin-Opener-Policy"],
            "same-origin",
        )


@override_settings(
    ALLOWED_HOSTS=["testserver"],
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    CSRF_COOKIE_SECURE=True,
    CSRF_COOKIE_HTTPONLY=True,
    CSRF_COOKIE_SAMESITE="Lax",
)
class CookieHardeningTests(TestCase):
    """Validate cookie attributes for session and CSRF protections."""

    def setUp(self):
        self.password = "SecurePass123!"  # noqa: S105 - test fixture password
        self.user = User.objects.create_user(
            username="secure-user",
            email="secure-user@example.com",
            password=self.password,
        )

    def test_sign_in_sets_hardened_session_cookie(self):
        response = self.client.post(
            reverse("accounts:sign_in"),
            {"login-id": self.user.username, "password": self.password},
            secure=True,
            HTTP_HOST="testserver",
        )

        session_cookie = response.cookies["sessionid"]
        self.assertTrue(session_cookie["secure"])
        self.assertTrue(session_cookie["httponly"])
        self.assertEqual(session_cookie["samesite"], "Lax")

    def test_sign_in_page_sets_hardened_csrf_cookie(self):
        client = Client()
        response = client.get(
            reverse("accounts:sign_in"),
            secure=True,
            HTTP_HOST="testserver",
        )

        csrf_cookie = response.cookies["csrftoken"]
        self.assertTrue(csrf_cookie["secure"])
        self.assertTrue(csrf_cookie["httponly"])
        self.assertEqual(csrf_cookie["samesite"], "Lax")


@override_settings(ALLOWED_HOSTS=["testserver"])
class CsrfAndRedirectSecurityTests(TestCase):
    """Cover common OWASP regressions around CSRF and open redirects."""

    def setUp(self):
        self.password = "SecurePass123!"  # noqa: S105 - test fixture password
        self.user = User.objects.create_user(
            username="csrf-user",
            email="csrf-user@example.com",
            password=self.password,
        )
        message = Message.objects.create(
            title="Security message",
            content="security content",
            message_type=Message.MessageType.SYSTEM,
        )
        self.user_message = UserMessage.objects.create(user=self.user, message=message)

    def test_message_mark_read_rejects_missing_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)

        response = csrf_client.post(
            reverse("messages:mark_read"),
            {"message_ids[]": [self.user_message.message_id]},
            secure=True,
            HTTP_HOST="testserver",
        )

        self.assertEqual(response.status_code, 403)

    def test_sign_in_rejects_scheme_relative_next_target(self):
        response = self.client.post(
            reverse("accounts:sign_in") + "?next=//evil.example/collect",
            {"login-id": self.user.username, "password": self.password},
            follow=True,
            secure=True,
            HTTP_HOST="testserver",
        )

        self.assertTrue(
            response.redirect_chain[-1][0].endswith(reverse("accounts:profile"))
        )
        self.assertTrue(response.wsgi_request.user.is_authenticated)


@override_settings(ALLOWED_HOSTS=["open-share.cn"])
class HostHeaderValidationTests(TestCase):
    """Reject untrusted hosts before they can influence absolute URLs."""

    def test_untrusted_host_returns_bad_request(self):
        response = self.client.get(
            reverse("homepage:index"),
            HTTP_HOST="evil.example",
        )

        self.assertEqual(response.status_code, 400)
