"""Tests for message API endpoints."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.services.jwt_tokens import create_access_token
from messages.models import Message, UserMessage
from messages.services import send_message


class MessagesApiV1Tests(TestCase):
    """Validate inbox APIs."""

    def setUp(self):
        """Create an authenticated user with one inbox message."""
        User = get_user_model()
        self.user = User.objects.create_user(
            username="message_user",
            email="message_user@example.com",
            password="StrongPass123!",
        )
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.user)}"
        }
        self.message = send_message(
            title="System Notice",
            content="Hello from the API.",
            message_type=Message.MessageType.SYSTEM,
            recipients=[self.user],
        )

    def test_list_and_detail_mark_message_as_read(self):
        """Listing and opening a message should work through the API."""
        list_response = self.client.get("/api/v1/messages/", **self.headers)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()["items"][0]["id"], self.message.id)

        detail_response = self.client.get(
            f"/api/v1/messages/{self.message.id}",
            **self.headers,
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["content"], "Hello from the API.")

        user_message = UserMessage.objects.get(user=self.user, message=self.message)
        self.assertTrue(user_message.is_read)

    def test_message_actions_update_state(self):
        """Read, unread, and delete actions should update inbox state."""
        read_response = self.client.post(
            "/api/v1/messages/mark-read",
            {"message_ids": [self.message.id]},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(read_response.status_code, 200)
        self.assertEqual(read_response.json()["updated"], 1)

        unread_response = self.client.post(
            "/api/v1/messages/mark-unread",
            {"message_ids": [self.message.id]},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(unread_response.status_code, 200)
        self.assertEqual(unread_response.json()["updated"], 1)

        delete_response = self.client.post(
            "/api/v1/messages/delete",
            {"message_ids": [self.message.id]},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.json()["deleted"], 1)

        unread_count_response = self.client.get(
            "/api/v1/messages/unread-count",
            **self.headers,
        )
        self.assertEqual(unread_count_response.status_code, 200)
        self.assertEqual(unread_count_response.json()["count"], 0)

    def test_stats_and_unread_count_filters(self):
        """Stats and unread-count endpoints should report consistent totals."""
        stats_response = self.client.get("/api/v1/messages/stats", **self.headers)
        self.assertEqual(stats_response.status_code, 200)
        stats_payload = stats_response.json()
        self.assertIn("total", stats_payload)
        self.assertEqual(stats_payload["unread"], 1)

        unread_count_response = self.client.get(
            "/api/v1/messages/unread-count",
            {"type": Message.MessageType.SYSTEM},
            **self.headers,
        )
        self.assertEqual(unread_count_response.status_code, 200)
        self.assertEqual(unread_count_response.json()["count"], 1)

    def test_mark_unread_requires_ids(self):
        """The mark-unread endpoint should reject empty message_ids."""
        response = self.client.post(
            "/api/v1/messages/mark-unread",
            {"message_ids": []},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("message_ids", response.json().get("detail", {}))

    def test_delete_requires_ids(self):
        """The delete endpoint should reject empty message_ids."""
        response = self.client.post(
            "/api/v1/messages/delete",
            {"message_ids": []},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("message_ids", response.json().get("detail", {}))
