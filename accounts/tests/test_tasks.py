"""Tests for accounts tasks."""

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase


class PasswordResetTaskTests(TestCase):
    """Test cases for password reset email task."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )

    def test_send_password_reset_email_task(self):
        """Test that password reset email task sends email."""
        from accounts.tasks import send_password_reset_email

        # Call the underlying function directly for testing
        send_password_reset_email.func(
            user_id=self.user.id,
            domain="testserver",
            use_https=False,
        )

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert email.to == ["test@example.com"]
        assert "重置您的 Open Share 密码" in email.subject
        assert "testuser" in email.body
        assert "testserver" in email.body

    def test_send_password_reset_email_task_with_nonexistent_user(self):
        """Test that task handles non-existent user gracefully."""
        from accounts.tasks import send_password_reset_email

        # Call the underlying function directly for testing
        send_password_reset_email.func(
            user_id=99999,
            domain="testserver",
            use_https=False,
        )

        assert len(mail.outbox) == 0

    def test_send_password_reset_email_task_with_https(self):
        """Test that task uses HTTPS when requested."""
        from accounts.tasks import send_password_reset_email

        # Call the underlying function directly for testing
        send_password_reset_email.func(
            user_id=self.user.id,
            domain="testserver",
            use_https=True,
        )

        assert len(mail.outbox) == 1
        email = mail.outbox[0]
        assert "https://" in email.body

    def test_send_password_reset_email_contains_reset_link(self):
        """Test that email contains password reset link."""
        from accounts.tasks import send_password_reset_email

        # Call the underlying function directly for testing
        send_password_reset_email.func(
            user_id=self.user.id,
            domain="testserver",
            use_https=False,
        )

        email = mail.outbox[0]
        assert "/accounts/password-reset-confirm/" in email.body
