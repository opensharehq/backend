"""Tests for messages admin behavior."""

from unittest.mock import Mock, patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from messages.admin import (
    MessageAdmin,
    MessageAdminForm,
    UserMessageAdmin,
    UserMessageInline,
)
from messages.models import Message, UserMessage

User = get_user_model()


class MessageAdminFormTests(TestCase):
    """Validate the custom admin form rules for broadcast vs targeted sends."""

    def setUp(self):
        """Create active recipients used by the admin form."""
        self.sender = User.objects.create_user(
            username="message-form-sender",
            email="sender@example.com",
            password="password123",
        )
        self.recipient = User.objects.create_user(
            username="message-form-recipient",
            email="recipient@example.com",
            password="password123",
        )

    def test_form_rejects_broadcast_with_explicit_recipients(self):
        """Broadcast messages cannot also target a selected recipient list."""
        form = MessageAdminForm(
            data={
                "title": "广播",
                "content": "内容",
                "message_type": Message.MessageType.SYSTEM,
                "sender": self.sender.id,
                "is_broadcast": "on",
                "recipients": [self.recipient.id],
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("广播消息不能同时指定接收用户", str(form.errors))

    def test_form_requires_recipients_for_non_broadcast_messages(self):
        """Non-broadcast messages need at least one selected recipient."""
        form = MessageAdminForm(
            data={
                "title": "定向",
                "content": "内容",
                "message_type": Message.MessageType.SYSTEM,
                "sender": self.sender.id,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("非广播消息必须指定接收用户", str(form.errors))

    def test_valid_targeted_form_returns_cleaned_data(self):
        """A targeted admin message with recipients should pass validation."""
        form = MessageAdminForm(
            data={
                "title": "定向",
                "content": "内容",
                "message_type": Message.MessageType.SYSTEM,
                "sender": self.sender.id,
                "recipients": [self.recipient.id],
            }
        )

        self.assertTrue(form.is_valid())


class MessageAdminTests(TestCase):
    """Cover the behaviorful parts of MessageAdmin."""

    def setUp(self):
        """Create admin fixtures and a registered admin instance."""
        self.site = AdminSite()
        self.factory = RequestFactory()
        self.admin_user = User.objects.create_superuser(
            username="messages-admin",
            email="messages-admin@example.com",
            password="password123",
        )
        self.recipient_one = User.objects.create_user(
            username="recipient-one",
            email="one@example.com",
            password="password123",
        )
        self.recipient_two = User.objects.create_user(
            username="recipient-two",
            email="two@example.com",
            password="password123",
        )
        self.message = Message.objects.create(
            title="系统通知",
            content="请尽快查看",
            sender=self.admin_user,
            is_broadcast=False,
        )
        self.user_message_one = UserMessage.objects.create(
            user=self.recipient_one,
            message=self.message,
            is_read=False,
        )
        self.user_message_two = UserMessage.objects.create(
            user=self.recipient_two,
            message=self.message,
            is_read=True,
        )
        self.user_message_two.mark_as_read()
        self.message_admin = MessageAdmin(Message, self.site)

    def _request(self):
        """Build a request with a logged-in superuser."""
        request = self.factory.get("/admin/site_messages/message/")
        request.user = self.admin_user
        return request

    def test_inline_and_display_helpers_reflect_message_state(self):
        """Inline permissions and display helpers should expose admin state cleanly."""
        inline = UserMessageInline(Message, self.site)

        self.assertFalse(inline.has_add_permission(self._request(), self.message))
        self.assertIn("badge", str(self.message_admin.message_type_badge(self.message)))
        self.assertEqual(
            self.message_admin.sender_display(self.message),
            self.admin_user.username,
        )

        system_message = Message.objects.create(title="系统", content="内容")
        self.assertIn(
            "text-muted", str(self.message_admin.sender_display(system_message))
        )

    def test_queryset_annotations_feed_recipient_and_unread_counts(self):
        """Annotated queryset results should drive the count columns."""
        queryset = self.message_admin.get_queryset(self._request())
        annotated_message = queryset.get(pk=self.message.pk)

        self.assertEqual(annotated_message._recipient_count, 2)
        self.assertEqual(annotated_message._unread_count, 1)
        self.assertEqual(self.message_admin.recipient_count(annotated_message), 2)
        self.assertIn(
            "bg-warning", str(self.message_admin.unread_count(annotated_message))
        )

        annotated_message.is_broadcast = True
        self.assertIn(
            "广播",
            str(self.message_admin.recipient_count(annotated_message)),
        )
        annotated_message._unread_count = 0
        self.assertEqual(self.message_admin.unread_count(annotated_message), 0)

    @patch("messages.admin.send_message")
    def test_save_model_sends_new_messages_via_service(self, mock_send_message):
        """Creating a new message through admin should delegate to send_message."""
        created_message = Message.objects.create(
            title="保存结果",
            content="正文",
            sender=self.admin_user,
        )
        mock_send_message.return_value = created_message
        form = Mock(
            cleaned_data={
                "recipients": [self.recipient_one, self.recipient_two],
                "is_broadcast": False,
            }
        )
        obj = Message(
            title="保存结果",
            content="正文",
            message_type=Message.MessageType.SYSTEM,
            sender=self.admin_user,
            is_broadcast=False,
        )

        self.message_admin.save_model(self._request(), obj, form, change=False)

        mock_send_message.assert_called_once_with(
            title="保存结果",
            content="正文",
            message_type=Message.MessageType.SYSTEM,
            sender=self.admin_user,
            recipients=[self.recipient_one, self.recipient_two],
            is_broadcast=False,
        )
        self.assertEqual(obj.pk, created_message.pk)

    def test_save_model_change_branch_uses_parent_implementation(self):
        """Editing an existing message should defer to the base ModelAdmin logic."""
        request = self._request()
        form = Mock(cleaned_data={})
        with patch("django.contrib.admin.ModelAdmin.save_model") as mock_super_save:
            self.message_admin.save_model(
                request,
                self.message,
                form,
                change=True,
            )

        mock_super_save.assert_called_once_with(request, self.message, form, True)

    def test_permissions_follow_read_only_rules(self):
        """Only list/create should be allowed; editing existing rows stays disabled."""
        request = self._request()

        self.assertTrue(self.message_admin.has_change_permission(request, obj=None))
        self.assertFalse(
            self.message_admin.has_change_permission(request, obj=self.message)
        )
        self.assertTrue(
            self.message_admin.has_delete_permission(request, obj=self.message)
        )


class UserMessageAdminTests(TestCase):
    """Cover batch actions and display helpers for user message admin."""

    def setUp(self):
        """Create a small inbox and the corresponding admin instance."""
        self.site = AdminSite()
        self.factory = RequestFactory()
        self.admin_user = User.objects.create_superuser(
            username="user-messages-admin",
            email="user-messages-admin@example.com",
            password="password123",
        )
        self.recipient = User.objects.create_user(
            username="inbox-user",
            email="inbox@example.com",
            password="password123",
        )
        self.message = Message.objects.create(title="状态", content="状态内容")
        self.user_message = UserMessage.objects.create(
            user=self.recipient,
            message=self.message,
            is_read=False,
            is_deleted=False,
        )
        self.user_message_admin = UserMessageAdmin(UserMessage, self.site)
        self.user_message_admin.message_user = Mock()

    def _request(self):
        """Build a request with a logged-in superuser."""
        request = self.factory.post("/admin/site_messages/usermessage/")
        request.user = self.admin_user
        return request

    def test_display_helpers_and_permissions_are_read_only_friendly(self):
        """Admin columns should expose message metadata while forbidding manual adds."""
        self.assertEqual(
            self.user_message_admin.message_title(self.user_message),
            self.message.title,
        )
        self.assertEqual(
            self.user_message_admin.message_type(self.user_message),
            self.message.get_message_type_display(),
        )
        self.assertFalse(self.user_message_admin.is_read_badge(self.user_message))
        self.assertFalse(self.user_message_admin.is_deleted_badge(self.user_message))
        self.assertFalse(self.user_message_admin.has_add_permission(self._request()))
        self.assertTrue(
            self.user_message_admin.has_change_permission(
                self._request(),
                self.user_message,
            )
        )

    def test_batch_actions_update_status_and_emit_messages(self):
        """Each batch action should mutate the queryset and report its outcome."""
        queryset = UserMessage.objects.filter(pk=self.user_message.pk)

        self.user_message_admin.mark_as_read(self._request(), queryset)
        self.user_message.refresh_from_db()
        self.assertTrue(self.user_message.is_read)

        self.user_message_admin.mark_as_unread(self._request(), queryset)
        self.user_message.refresh_from_db()
        self.assertFalse(self.user_message.is_read)

        self.user_message_admin.soft_delete(self._request(), queryset)
        self.user_message.refresh_from_db()
        self.assertTrue(self.user_message.is_deleted)

        self.user_message_admin.restore(self._request(), queryset)
        self.user_message.refresh_from_db()
        self.assertFalse(self.user_message.is_deleted)

        self.assertEqual(self.user_message_admin.message_user.call_count, 4)
