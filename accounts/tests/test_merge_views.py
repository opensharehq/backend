"""Coverage-focused tests for merge request views."""

from datetime import timedelta
from unittest import mock
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccountMergeRequest


class MergeViewsEdgeCaseTests(TestCase):
    """Hit rarely used branches inside merge-related views."""

    def setUp(self):
        self.User = get_user_model()
        self.source = self.User.objects.create_user(
            username="merge-src", email="src@example.com", password="pwd123456"
        )
        self.target = self.User.objects.create_user(
            username="merge-tgt", email="tgt@example.com", password="pwd123456"
        )
        self.merge_request = AccountMergeRequest.objects.create(
            id=uuid4(),
            source_user=self.source,
            target_user=self.target,
            target_username_input=self.target.username,
            status=AccountMergeRequest.Status.PENDING,
            approve_token="view-token",
            expires_at=timezone.now() + timedelta(days=1),
            asset_snapshot={},
        )

    def _login_target(self):
        self.client.force_login(self.target)

    def test_merge_request_view_handles_integrity_error(self):
        """Duplicate pending triggers IntegrityError branch."""
        self.client.force_login(self.source)
        with mock.patch("accounts.views.AccountMergeRequestForm") as form_cls:
            form_instance = mock.Mock()
            form_instance.is_valid.return_value = True
            form_instance.target_user = self.target
            form_instance.cleaned_data = {
                "target_email": "",
                "target_username": self.target.username,
            }
            form_cls.return_value = form_instance
            with mock.patch(
                "accounts.views.AccountMergeRequest.objects.create",
                side_effect=IntegrityError,
            ):
                response = self.client.post(
                    reverse("accounts:merge_request"),
                    {"target_username": self.target.username},
                    follow=False,
                )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("accounts:merge_request"))

    def test_merge_agree_redirects_on_get(self):
        """Non-POST requests are redirected to review page."""
        self._login_target()
        response = self.client.get(
            reverse("accounts:merge_agree", args=[self.merge_request.approve_token])
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse("accounts:merge_review", args=[self.merge_request.approve_token]),
        )

    def test_merge_agree_expires_pending(self):
        """Expired pending requests short-circuit with error message."""
        self._login_target()
        self.merge_request.expires_at = timezone.now() - timedelta(minutes=1)
        self.merge_request.save(update_fields=["expires_at"])
        response = self.client.post(
            reverse("accounts:merge_agree", args=[self.merge_request.approve_token])
        )
        self.assertEqual(response.status_code, 302)

    def test_merge_agree_skips_when_accepted(self):
        """Accepted requests return early with info message."""
        self._login_target()
        self.merge_request.status = AccountMergeRequest.Status.ACCEPTED
        self.merge_request.save(update_fields=["status"])
        response = self.client.post(
            reverse("accounts:merge_agree", args=[self.merge_request.approve_token])
        )
        self.assertEqual(response.status_code, 302)

    def test_merge_agree_success_path(self):
        """Successful merge triggers perform_merge and redirects."""
        self._login_target()
        with mock.patch(
            "accounts.views.perform_merge",
            side_effect=lambda mr: mr.__setattr__(
                "status", AccountMergeRequest.Status.ACCEPTED
            )
            or mr,
        ) as perform_mock:
            response = self.client.post(
                reverse("accounts:merge_agree", args=[self.merge_request.approve_token])
            )
        self.assertEqual(response.status_code, 302)
        perform_mock.assert_called_once()

    def test_merge_agree_permission_denied(self):
        """Only target user may process the merge."""
        other = self.User.objects.create_user(
            username="other", email="other@example.com", password="pwd123456"
        )
        self.client.force_login(other)
        response = self.client.post(
            reverse("accounts:merge_agree", args=[self.merge_request.approve_token])
        )
        self.assertEqual(response.status_code, 403)

    def test_merge_reject_redirects_on_get(self):
        """Reject view redirects for non-POST requests."""
        self._login_target()
        response = self.client.get(
            reverse("accounts:merge_reject", args=[self.merge_request.approve_token])
        )
        self.assertEqual(response.status_code, 302)

    def test_merge_reject_expires_pending(self):
        """Expired pending reject path shows error."""
        self._login_target()
        self.merge_request.expires_at = timezone.now() - timedelta(minutes=1)
        self.merge_request.save(update_fields=["expires_at"])
        response = self.client.post(
            reverse("accounts:merge_reject", args=[self.merge_request.approve_token])
        )
        self.assertEqual(response.status_code, 302)

    def test_merge_reject_skips_when_accepted(self):
        """Cannot reject an already accepted request."""
        self._login_target()
        self.merge_request.status = AccountMergeRequest.Status.ACCEPTED
        self.merge_request.save(update_fields=["status"])
        response = self.client.post(
            reverse("accounts:merge_reject", args=[self.merge_request.approve_token])
        )
        self.assertEqual(response.status_code, 302)

    def test_merge_reject_permission_denied(self):
        """Only target user may reject."""
        self.client.force_login(self.source)
        response = self.client.post(
            reverse("accounts:merge_reject", args=[self.merge_request.approve_token])
        )
        self.assertEqual(response.status_code, 403)

    def test_merge_reject_marks_rejected(self):
        """Pending request should be marked rejected on POST."""
        self._login_target()
        response = self.client.post(
            reverse("accounts:merge_reject", args=[self.merge_request.approve_token])
        )
        self.assertEqual(response.status_code, 302)
        self.merge_request.refresh_from_db()
        self.assertEqual(self.merge_request.status, AccountMergeRequest.Status.REJECTED)
