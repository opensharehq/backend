"""Authentication flow tests for username/email sign-in."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class SignInViewTests(TestCase):
    """Validate manual username/email login works."""

    def setUp(self):
        """Create a user for sign-in tests."""
        self.User = get_user_model()
        self.password = "MergeTest123!"  # noqa: S105 - test fixture password
        self.user = self.User.objects.create_user(
            username="signin_user",
            email="signin_user@example.com",
            password=self.password,
        )

    def test_login_with_username(self):
        """User can sign in via username + password."""
        resp = self.client.post(
            reverse("accounts:sign_in"),
            {"login-id": self.user.username, "password": self.password},
            follow=True,
        )
        assert resp.wsgi_request.user.is_authenticated
        assert resp.redirect_chain

    def test_login_with_email(self):
        """User can sign in via email + password."""
        resp = self.client.post(
            reverse("accounts:sign_in"),
            {"login-id": self.user.email, "password": self.password},
            follow=True,
        )
        assert resp.wsgi_request.user.is_authenticated

    def test_login_with_wrong_password(self):
        """Invalid credentials should not authenticate user."""
        resp = self.client.post(
            reverse("accounts:sign_in"),
            {"login-id": self.user.username, "password": "wrong"},
            follow=True,
        )
        assert not resp.wsgi_request.user.is_authenticated

    def test_login_for_merged_account_shows_hint(self):
        """Merged source account cannot log in and shows redirect hint."""
        target = self.User.objects.create_user(
            username="merged_target",
            email="merged_target@example.com",
            password=self.password,
        )
        source = self.User.objects.create_user(
            username="merged_source",
            email="merged_source@example.com",
            password=self.password,
            is_active=False,
        )
        source.merged_into = target
        source.save(update_fields=["merged_into", "is_active"])

        resp = self.client.post(
            reverse("accounts:sign_in"),
            {"login-id": source.username, "password": self.password},
            follow=True,
        )

        assert not resp.wsgi_request.user.is_authenticated
        assert "已合并到" in resp.content.decode()

    def test_malicious_next_is_rejected(self):
        """Open redirects are blocked and fallback to profile."""
        resp = self.client.post(
            reverse("accounts:sign_in") + "?next=https://evil.com/phish",
            {"login-id": self.user.username, "password": self.password},
            follow=True,
        )
        # final redirected path should be profile, not external
        assert resp.redirect_chain[-1][0].endswith(reverse("accounts:profile"))
        assert resp.wsgi_request.user.is_authenticated

    def test_safe_next_relative_redirects(self):
        """Relative next path should be honored after login."""
        target = "/profile/"
        resp = self.client.post(
            reverse("accounts:sign_in") + f"?next={target}",
            {"login-id": self.user.username, "password": self.password},
            follow=True,
        )
        assert resp.redirect_chain[-1][0].endswith(target)
        assert resp.wsgi_request.user.is_authenticated

    def test_safe_next_same_host_absolute_redirects(self):
        """Absolute URL on same host should be allowed."""
        target = "http://testserver/profile/"
        resp = self.client.post(
            reverse("accounts:sign_in") + f"?next={target}",
            {"login-id": self.user.username, "password": self.password},
            follow=True,
            HTTP_HOST="testserver",
        )
        assert resp.redirect_chain[-1][0] == target
        assert resp.wsgi_request.user.is_authenticated

    def test_inactive_account_shows_disabled_message(self):
        """Inactive users receive specific hint instead of generic failure."""
        inactive = self.User.objects.create_user(
            username="inactive_user",
            email="inactive@example.com",
            password=self.password,
            is_active=False,
        )

        resp = self.client.post(
            reverse("accounts:sign_in"),
            {"login-id": inactive.username, "password": self.password},
            follow=True,
        )

        assert not resp.wsgi_request.user.is_authenticated
        assert "已被停用" in resp.content.decode()
