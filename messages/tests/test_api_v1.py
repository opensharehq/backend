"""Tests for message API endpoints."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.services.jwt_tokens import create_access_token
from messages.models import Message, UserMessage
from messages.services import send_message


class MessagesApiV1Tests(TestCase):
    """Validate inbox APIs."""

    def setUp(self):
        """Create authenticated users with mixed message types."""
        User = get_user_model()
        self.user = User.objects.create_user(
            username="message_user",
            email="message_user@example.com",
            password="StrongPass123!",
        )
        self.other_user = User.objects.create_user(
            username="message_peer",
            email="message_peer@example.com",
            password="StrongPass123!",
        )
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.user)}"
        }
        self.other_headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.other_user)}"
        }
        self.system_message = send_message(
            title="System Notice",
            content="Hello from the API.",
            message_type=Message.MessageType.SYSTEM,
            recipients=[self.user],
        )
        self.payment_message = send_message(
            title="Payment Notice",
            content="Payment updated.",
            message_type=Message.MessageType.PAYMENT,
            recipients=[self.user],
        )
        self.other_message = send_message(
            title="Peer Notice",
            content="Only for another user.",
            message_type=Message.MessageType.SYSTEM,
            recipients=[self.other_user],
        )

    def test_list_and_detail_do_not_mark_message_as_read(self):
        """Listing and reading message detail should not mutate read state."""
        list_response = self.client.get("/api/v1/messages/", **self.headers)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()["pagination"]["total_items"], 2)
        self.assertTrue(
            all(not item["is_read"] for item in list_response.json()["items"])
        )

        detail_response = self.client.get(
            f"/api/v1/messages/{self.system_message.id}",
            **self.headers,
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["content"], "Hello from the API.")

        user_message = UserMessage.objects.get(
            user=self.user,
            message=self.system_message,
        )
        self.assertFalse(user_message.is_read)

    def test_detail_mark_read_endpoint_is_idempotent(self):
        """Single-message mark-read should update once and then become a no-op."""
        first_response = self.client.post(
            f"/api/v1/messages/{self.system_message.id}/mark-read",
            **self.headers,
        )
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.json()["updated"], 1)

        second_response = self.client.post(
            f"/api/v1/messages/{self.system_message.id}/mark-read",
            **self.headers,
        )
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.json()["updated"], 0)

        user_message = UserMessage.objects.get(
            user=self.user,
            message=self.system_message,
        )
        self.assertTrue(user_message.is_read)
        self.assertIsNotNone(user_message.read_at)

    def test_bulk_message_actions_update_state(self):
        """Bulk read, unread, and delete actions should update inbox state."""
        read_response = self.client.post(
            "/api/v1/messages/mark-read",
            {"message_ids": [self.system_message.id]},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(read_response.status_code, 200)
        self.assertEqual(read_response.json()["updated"], 1)

        unread_response = self.client.post(
            "/api/v1/messages/mark-unread",
            {"message_ids": [self.system_message.id]},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(unread_response.status_code, 200)
        self.assertEqual(unread_response.json()["updated"], 1)

        second_read_response = self.client.post(
            "/api/v1/messages/mark-read",
            {"message_ids": [self.system_message.id]},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(second_read_response.status_code, 200)
        self.assertEqual(second_read_response.json()["updated"], 1)

        mark_all_response = self.client.post(
            "/api/v1/messages/mark-all-read",
            **self.headers,
        )
        self.assertEqual(mark_all_response.status_code, 200)
        self.assertEqual(mark_all_response.json()["updated"], 1)

        second_mark_all = self.client.post(
            "/api/v1/messages/mark-all-read",
            **self.headers,
        )
        self.assertEqual(second_mark_all.status_code, 200)
        self.assertEqual(second_mark_all.json()["updated"], 0)

        delete_response = self.client.post(
            "/api/v1/messages/delete",
            {"message_ids": [self.system_message.id]},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(delete_response.json()["deleted"], 1)

        deleted_detail = self.client.get(
            f"/api/v1/messages/{self.system_message.id}",
            **self.headers,
        )
        self.assertEqual(deleted_detail.status_code, 404)

    def test_message_type_filters_and_validation(self):
        """Message list and unread count should honor valid enum filters only."""
        stats_response = self.client.get("/api/v1/messages/stats", **self.headers)
        self.assertEqual(stats_response.status_code, 200)
        stats_payload = stats_response.json()
        self.assertEqual(stats_payload["total"], 2)
        self.assertEqual(stats_payload["unread"], 2)
        self.assertEqual(stats_payload["type_counts"][Message.MessageType.SYSTEM], 1)
        self.assertEqual(stats_payload["type_counts"][Message.MessageType.PAYMENT], 1)

        unread_count_response = self.client.get(
            "/api/v1/messages/unread-count",
            {"message_type": Message.MessageType.SYSTEM},
            **self.headers,
        )
        self.assertEqual(unread_count_response.status_code, 200)
        self.assertEqual(unread_count_response.json()["count"], 1)

        list_response = self.client.get(
            "/api/v1/messages/",
            {"message_type": Message.MessageType.PAYMENT},
            **self.headers,
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()["items"]), 1)
        self.assertEqual(
            list_response.json()["items"][0]["message_type"],
            Message.MessageType.PAYMENT,
        )
        self.assertEqual(
            list_response.json()["filters"]["message_type"],
            Message.MessageType.PAYMENT,
        )

        read_payment = UserMessage.objects.get(
            user=self.user,
            message=self.payment_message,
        )
        read_payment.is_read = True
        read_payment.save(update_fields=["is_read"])
        unread_response = self.client.get(
            "/api/v1/messages/",
            {"status": "unread"},
            **self.headers,
        )
        read_response = self.client.get(
            "/api/v1/messages/",
            {"status": "read"},
            **self.headers,
        )
        self.assertEqual(unread_response.status_code, 200)
        self.assertEqual(read_response.status_code, 200)
        self.assertTrue(
            all(not item["is_read"] for item in unread_response.json()["items"])
        )
        self.assertTrue(all(item["is_read"] for item in read_response.json()["items"]))

        invalid_list_response = self.client.get(
            "/api/v1/messages/",
            {"message_type": "unknown"},
            **self.headers,
        )
        self.assertEqual(invalid_list_response.status_code, 422)
        self.assertEqual(invalid_list_response.json()["code"], "validation_error")

        invalid_status_response = self.client.get(
            "/api/v1/messages/",
            {"status": "archived"},
            **self.headers,
        )
        self.assertEqual(invalid_status_response.status_code, 422)
        self.assertEqual(invalid_status_response.json()["code"], "validation_error")

        invalid_count_response = self.client.get(
            "/api/v1/messages/unread-count",
            {"message_type": "unknown"},
            **self.headers,
        )
        self.assertEqual(invalid_count_response.status_code, 422)
        self.assertEqual(invalid_count_response.json()["code"], "validation_error")

    def test_mark_read_requires_non_empty_message_ids(self):
        """Bulk mark-read should reject missing, null, and empty message_ids."""
        for payload in ({}, {"message_ids": None}, {"message_ids": []}):
            response = self.client.post(
                "/api/v1/messages/mark-read",
                payload,
                content_type="application/json",
                **self.headers,
            )
            self.assertEqual(response.status_code, 422)
            self.assertIn("message_ids", response.json().get("detail", {}))

    def test_other_bulk_actions_require_non_empty_message_ids(self):
        """Sibling bulk action endpoints should keep the same non-empty contract."""
        for path in ("/api/v1/messages/mark-unread", "/api/v1/messages/delete"):
            response = self.client.post(
                path,
                {"message_ids": []},
                content_type="application/json",
                **self.headers,
            )
            self.assertEqual(response.status_code, 422)
            self.assertIn("message_ids", response.json().get("detail", {}))

    def test_unauthenticated_requests_fail(self):
        """Inbox endpoints should reject requests without a bearer token."""
        endpoints = (
            ("get", "/api/v1/messages/"),
            ("get", f"/api/v1/messages/{self.system_message.id}"),
            ("post", "/api/v1/messages/mark-read"),
            ("post", f"/api/v1/messages/{self.system_message.id}/mark-read"),
            ("post", "/api/v1/messages/mark-all-read"),
        )
        for method, path in endpoints:
            response = getattr(self.client, method)(
                path,
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["code"], "invalid_token")

    def test_message_access_is_scoped_to_current_user(self):
        """Users cannot read or mutate another user's messages."""
        detail_response = self.client.get(
            f"/api/v1/messages/{self.other_message.id}",
            **self.headers,
        )
        self.assertEqual(detail_response.status_code, 404)

        mark_response = self.client.post(
            f"/api/v1/messages/{self.other_message.id}/mark-read",
            **self.headers,
        )
        self.assertEqual(mark_response.status_code, 200)
        self.assertEqual(mark_response.json()["updated"], 0)

        bulk_mark = self.client.post(
            "/api/v1/messages/mark-read",
            {"message_ids": [self.other_message.id]},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(bulk_mark.status_code, 200)
        self.assertEqual(bulk_mark.json()["updated"], 0)

        self.assertFalse(
            UserMessage.objects.get(
                user=self.other_user,
                message=self.other_message,
            ).is_read
        )
