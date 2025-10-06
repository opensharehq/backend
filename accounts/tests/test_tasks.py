"""Tests for accounts tasks."""

from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

User = get_user_model()


class PasswordResetTaskTests(TestCase):
    """Test cases for password reset email task."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
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

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["test@example.com"])
        self.assertIn("重置您的 Open Share 密码", email.subject)
        self.assertIn("testuser", email.body)
        self.assertIn("testserver", email.body)

    def test_send_password_reset_email_task_with_nonexistent_user(self):
        """Test that task handles non-existent user gracefully."""
        from accounts.tasks import send_password_reset_email

        # Call the underlying function directly for testing
        send_password_reset_email.func(
            user_id=99999,
            domain="testserver",
            use_https=False,
        )

        self.assertEqual(len(mail.outbox), 0)

    def test_send_password_reset_email_task_with_https(self):
        """Test that task uses HTTPS when requested."""
        from accounts.tasks import send_password_reset_email

        # Call the underlying function directly for testing
        send_password_reset_email.func(
            user_id=self.user.id,
            domain="testserver",
            use_https=True,
        )

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("https://", email.body)

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
        self.assertIn("/accounts/password-reset-confirm/", email.body)


# Additional comprehensive tests for edge cases and security


class TestPasswordResetEmailTask(TestCase):
    """Comprehensive test cases for password reset email task."""

    def setUp(self):
        """Set up test user for all test methods."""
        User = get_user_model()
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )

    def test_email_contains_valid_token(self):
        """Test that email contains a valid password reset token."""
        from accounts.tasks import send_password_reset_email

        send_password_reset_email.func(
            user_id=self.user.id,
            domain="example.com",
            use_https=False,
        )

        self.assertEqual(len(mail.outbox), 1)
        email_body = mail.outbox[0].body

        # Extract token from email body
        # Format: /accounts/password-reset-confirm/{uid}/{token}/
        lines = email_body.split("\n")
        reset_url = None
        for line in lines:
            if "/accounts/password-reset-confirm/" in line:
                reset_url = line.strip()
                break

        self.assertIsNotNone(reset_url)
        # Verify token is present and non-empty
        parts = reset_url.split("/")
        uid = parts[-3]
        token = parts[-2]
        self.assertTrue(uid)
        self.assertTrue(token)
        self.assertGreater(len(token), 10)  # Token should be reasonably long

    def test_email_contains_correct_uid(self):
        """Test that email contains correct base64-encoded user ID."""
        from accounts.tasks import send_password_reset_email

        send_password_reset_email.func(
            user_id=self.user.id,
            domain="example.com",
            use_https=False,
        )

        expected_uid = urlsafe_base64_encode(force_bytes(self.user.pk))

        email_body = mail.outbox[0].body
        self.assertIn(expected_uid, email_body)

    def test_email_sent_from_default_from_email(self):
        """Test that email is sent from DEFAULT_FROM_EMAIL setting."""
        from accounts.tasks import send_password_reset_email

        send_password_reset_email.func(
            user_id=self.user.id,
            domain="example.com",
            use_https=False,
        )

        email = mail.outbox[0]
        self.assertEqual(email.from_email, settings.DEFAULT_FROM_EMAIL)

    def test_email_has_both_html_and_text_versions(self):
        """Test that email contains both HTML and text versions."""
        from accounts.tasks import send_password_reset_email

        send_password_reset_email.func(
            user_id=self.user.id,
            domain="example.com",
            use_https=False,
        )

        email = mail.outbox[0]
        # Check text body exists
        self.assertTrue(email.body)
        self.assertIn("重置您的密码", email.body)

        # Check HTML alternative exists
        self.assertGreater(len(email.alternatives), 0)
        html_content = email.alternatives[0][0]
        self.assertIn("text/html", email.alternatives[0][1])
        self.assertIn("<html", html_content)
        self.assertIn("重置您的密码", html_content)
        self.assertIn(self.user.username, html_content)

    def test_email_text_version_contains_all_required_info(self):
        """Test that text version contains all required information."""
        from accounts.tasks import send_password_reset_email

        send_password_reset_email.func(
            user_id=self.user.id,
            domain="example.com",
            use_https=False,
        )

        email_body = mail.outbox[0].body

        # Verify all required elements
        self.assertIn(self.user.username, email_body)
        self.assertIn("example.com", email_body)
        self.assertIn("/accounts/password-reset-confirm/", email_body)
        self.assertIn("24 小时", email_body)  # Expiration warning
        self.assertIn("重置您的密码", email_body)

    def test_email_html_version_contains_all_required_info(self):
        """Test that HTML version contains all required information."""
        from accounts.tasks import send_password_reset_email

        send_password_reset_email.func(
            user_id=self.user.id,
            domain="example.com",
            use_https=False,
        )

        html_content = mail.outbox[0].alternatives[0][0]

        # Verify all required elements
        self.assertIn(self.user.username, html_content)
        self.assertIn("example.com", html_content)
        self.assertIn("/accounts/password-reset-confirm/", html_content)
        self.assertIn("24 小时", html_content)  # Expiration warning
        self.assertIn("重置密码", html_content)  # Button text
        self.assertIn('href="', html_content)  # Has clickable link

    def test_protocol_http_when_use_https_false(self):
        """Test that HTTP protocol is used when use_https=False."""
        from accounts.tasks import send_password_reset_email

        send_password_reset_email.func(
            user_id=self.user.id,
            domain="example.com",
            use_https=False,
        )

        email_body = mail.outbox[0].body
        self.assertIn("http://example.com/accounts/password-reset-confirm/", email_body)
        self.assertNotIn(
            "https://", email_body.replace("Open Share", "")
        )  # Exclude brand name

    def test_protocol_https_when_use_https_true(self):
        """Test that HTTPS protocol is used when use_https=True."""
        from accounts.tasks import send_password_reset_email

        send_password_reset_email.func(
            user_id=self.user.id,
            domain="example.com",
            use_https=True,
        )

        email_body = mail.outbox[0].body
        self.assertIn(
            "https://example.com/accounts/password-reset-confirm/", email_body
        )

    def test_different_domains_produce_correct_urls(self):
        """Test that different domains produce correct reset URLs."""
        from accounts.tasks import send_password_reset_email

        domains = [
            "example.com",
            "localhost:8000",
            "test.example.org",
            "192.168.1.1:3000",
        ]

        for domain in domains:
            mail.outbox.clear()

            send_password_reset_email.func(
                user_id=self.user.id,
                domain=domain,
                use_https=False,
            )

            email_body = mail.outbox[0].body
            self.assertIn(
                f"http://{domain}/accounts/password-reset-confirm/", email_body
            )
            self.assertIn(domain, email_body)

    def test_task_with_user_without_email(self):
        """Test task handles user without email address gracefully."""
        from accounts.tasks import send_password_reset_email

        user_no_email = get_user_model().objects.create_user(
            username="noemail",
            email="",  # Empty email
            password="testpass123",
        )

        # Should not raise exception, but may not send email
        send_password_reset_email.func(
            user_id=user_no_email.id,
            domain="example.com",
            use_https=False,
        )

        # Email might be sent or not depending on Django's behavior
        # The important thing is no exception is raised

    def test_task_with_inactive_user(self):
        """Test task sends email even for inactive users."""
        from accounts.tasks import send_password_reset_email

        inactive_user = get_user_model().objects.create_user(
            username="inactive",
            email="inactive@example.com",
            password="testpass123",
            is_active=False,
        )

        send_password_reset_email.func(
            user_id=inactive_user.id,
            domain="example.com",
            use_https=False,
        )

        # Django allows password reset for inactive users
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["inactive@example.com"])

    def test_token_generator_called(self):
        """Test that default token generator is used."""
        from accounts.tasks import send_password_reset_email

        with patch("accounts.tasks.default_token_generator.make_token") as mock_token:
            mock_token.return_value = "fake-token-12345"

            send_password_reset_email.func(
                user_id=self.user.id,
                domain="example.com",
                use_https=False,
            )

            mock_token.assert_called_once_with(self.user)
            self.assertIn("fake-token-12345", mail.outbox[0].body)

    def test_email_subject_in_chinese(self):
        """Test that email subject is in Chinese."""
        from accounts.tasks import send_password_reset_email

        send_password_reset_email.func(
            user_id=self.user.id,
            domain="example.com",
            use_https=False,
        )

        email = mail.outbox[0]
        self.assertEqual("重置您的 Open Share 密码", email.subject)
        # Ensure it's the exact expected subject
        self.assertNotIn("password", email.subject.lower())  # Should not have English

    def test_multiple_users_receive_different_tokens(self):
        """Test that different users receive different reset tokens."""
        from accounts.tasks import send_password_reset_email

        user2 = get_user_model().objects.create_user(
            username="testuser2",
            email="test2@example.com",
            password="testpass123",
        )

        send_password_reset_email.func(
            user_id=self.user.id,
            domain="example.com",
            use_https=False,
        )

        email1_body = mail.outbox[0].body

        mail.outbox.clear()

        send_password_reset_email.func(
            user_id=user2.id,
            domain="example.com",
            use_https=False,
        )

        email2_body = mail.outbox[0].body

        # Extract tokens from both emails
        def extract_token(body):
            lines = body.split("\n")
            for line in lines:
                if "/accounts/password-reset-confirm/" in line:
                    parts = line.strip().split("/")
                    return parts[-2]  # Token is second to last
            return None

        token1 = extract_token(email1_body)
        token2 = extract_token(email2_body)

        # Tokens should be different for different users
        self.assertNotEqual(token1, token2)
        self.assertIsNotNone(token1)
        self.assertIsNotNone(token2)

    def test_template_rendering_with_special_characters_in_username(self):
        """Test template rendering with special characters in username."""
        from accounts.tasks import send_password_reset_email

        special_user = get_user_model().objects.create_user(
            username="user_with-special.chars",
            email="special@example.com",
            password="testpass123",
        )

        send_password_reset_email.func(
            user_id=special_user.id,
            domain="example.com",
            use_https=False,
        )

        email = mail.outbox[0]
        self.assertIn("user_with-special.chars", email.body)
        self.assertEqual(len(mail.outbox), 1)

    def test_email_not_sent_when_user_deleted_after_task_queued(self):
        """Test graceful handling when user is deleted before task executes."""
        from accounts.tasks import send_password_reset_email

        user_id = self.user.id
        self.user.delete()

        # Should not raise exception
        send_password_reset_email.func(
            user_id=user_id,
            domain="example.com",
            use_https=False,
        )

        # No email should be sent
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(DEFAULT_FROM_EMAIL="custom@openshare.com")
    def test_custom_from_email_setting(self):
        """Test that custom DEFAULT_FROM_EMAIL setting is respected."""
        from accounts.tasks import send_password_reset_email

        send_password_reset_email.func(
            user_id=self.user.id,
            domain="example.com",
            use_https=False,
        )

        email = mail.outbox[0]
        self.assertEqual(email.from_email, "custom@openshare.com")

    def test_url_encoding_of_uid(self):
        """Test that UID is properly URL-safe base64 encoded."""
        from accounts.tasks import send_password_reset_email

        send_password_reset_email.func(
            user_id=self.user.id,
            domain="example.com",
            use_https=False,
        )

        email_body = mail.outbox[0].body

        # Extract UID from email
        lines = email_body.split("\n")
        for line in lines:
            if "/accounts/password-reset-confirm/" in line:
                parts = line.strip().split("/")
                uid = parts[-3]

                # Verify UID is URL-safe (no +, /, or =)
                # URL-safe base64 uses - and _ instead
                self.assertTrue("+" not in uid or "-" in uid)
                self.assertTrue("/" not in uid or "_" in uid)
                break
