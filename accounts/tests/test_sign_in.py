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
