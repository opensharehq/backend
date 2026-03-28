"""Integration tests for account-merge notifications."""

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from accounts.models import AccountMergeRequest
from common.test_utils import CacheClearTestCase
from messages.models import UserMessage

User = get_user_model()


class AccountMergeNotificationIntegrationTests(CacheClearTestCase):
    """Verify real inbox notifications around merge request lifecycle."""

    def setUp(self):
        super().setUp()
        self.source = User.objects.create_user(
            username="merge-source",
            email="merge-source@example.com",
            password="testpass123",
        )
        self.target = User.objects.create_user(
            username="merge-target",
            email="merge-target@example.com",
            password="testpass123",
        )
        self.source_client = Client()
        self.target_client = Client()
        self.source_client.force_login(self.source)
        self.target_client.force_login(self.target)

    def test_creating_merge_request_sends_real_inbox_message(self):
        response = self.source_client.post(
            reverse("accounts:merge_request"),
            {"target_username": self.target.username},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        merge_request = AccountMergeRequest.objects.get(source_user=self.source)
        inbox_message = UserMessage.objects.get(
            user=self.target,
            message__title="账号合并申请",
        )

        self.assertEqual(merge_request.message, inbox_message.message)
        self.assertIn(self.source.username, inbox_message.message.content)
        self.assertIn(merge_request.approve_token, inbox_message.message.content)

    def test_accepting_merge_request_sends_result_notifications(self):
        self.source_client.post(
            reverse("accounts:merge_request"),
            {"target_username": self.target.username},
            follow=True,
        )
        merge_request = AccountMergeRequest.objects.get(source_user=self.source)

        response = self.target_client.post(
            reverse("accounts:merge_agree", args=[merge_request.approve_token]),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        merge_request.refresh_from_db()
        self.source.refresh_from_db()

        self.assertEqual(merge_request.status, AccountMergeRequest.Status.ACCEPTED)
        self.assertFalse(self.source.is_active)
        self.assertEqual(self.source.merged_into, self.target)
        self.assertEqual(
            UserMessage.objects.filter(
                user=self.source,
                message__title="账号合并结果通知",
            ).count(),
            1,
        )
        self.assertEqual(
            UserMessage.objects.filter(
                user=self.target,
                message__title="账号合并结果通知",
            ).count(),
            1,
        )
