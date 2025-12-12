"""消息视图测试."""

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from messages.models import Message, UserMessage
from messages.services import send_message

User = get_user_model()


class MessageListViewTests(TestCase):
    """消息列表视图测试."""

    def setUp(self):
        """设置测试数据."""
        self.user = User.objects.create_user(
            username="testuser", password="testpass123", email="test@example.com"
        )
        self.client.login(username="testuser", password="testpass123")

        # 创建消息
        for i in range(5):
            message = Message.objects.create(
                title=f"消息{i}",
                content=f"内容{i}",
                message_type=Message.MessageType.SYSTEM,
            )
            um = UserMessage.objects.create(user=self.user, message=message)
            if i % 2 == 0:
                um.mark_as_read()

    def test_message_list_view(self):
        """测试消息列表视图."""
        response = self.client.get(reverse("messages:list"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "messages/message_list.html")
        self.assertEqual(len(response.context["page_obj"]), 5)

    def test_message_list_requires_login(self):
        """测试消息列表需要登录."""
        self.client.logout()
        response = self.client.get(reverse("messages:list"))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/accounts/login/"))

    def test_message_list_filter_by_status_unread(self):
        """测试按状态过滤未读消息."""
        response = self.client.get(reverse("messages:list") + "?status=unread")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["page_obj"]), 2)

    def test_message_list_filter_by_status_read(self):
        """测试按状态过滤已读消息."""
        response = self.client.get(reverse("messages:list") + "?status=read")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["page_obj"]), 3)

    def test_message_list_filter_by_type(self):
        """测试按类型过滤消息."""
        # 创建支付类型的消息
        message = Message.objects.create(
            title="支付", content="内容", message_type=Message.MessageType.PAYMENT
        )
        UserMessage.objects.create(user=self.user, message=message)

        response = self.client.get(
            reverse("messages:list") + f"?type={Message.MessageType.PAYMENT}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["page_obj"]), 1)

    def test_message_list_stats(self):
        """测试消息统计."""
        response = self.client.get(reverse("messages:list"))

        stats = response.context["stats"]
        self.assertEqual(stats["total"], 5)
        self.assertEqual(stats["unread"], 2)
        self.assertEqual(stats["read"], 3)


class MessageDetailViewTests(TestCase):
    """消息详情视图测试."""

    def setUp(self):
        """设置测试数据."""
        self.user = User.objects.create_user(
            username="testuser", password="testpass123", email="test@example.com"
        )
        self.client.login(username="testuser", password="testpass123")

        self.message = Message.objects.create(
            title="测试消息",
            content="# 标题\n\n这是一条**测试**消息",
            message_type=Message.MessageType.SYSTEM,
        )
        self.user_message = UserMessage.objects.create(
            user=self.user, message=self.message
        )

    def test_message_detail_view(self):
        """测试消息详情视图."""
        response = self.client.get(reverse("messages:detail", args=[self.message.id]))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "messages/message_detail.html")
        self.assertEqual(response.context["user_message"], self.user_message)

    def test_message_detail_auto_mark_as_read(self):
        """测试查看消息自动标记为已读."""
        self.assertFalse(self.user_message.is_read)

        self.client.get(reverse("messages:detail", args=[self.message.id]))

        self.user_message.refresh_from_db()
        self.assertTrue(self.user_message.is_read)

    def test_message_detail_not_found(self):
        """测试访问不存在的消息."""
        response = self.client.get(reverse("messages:detail", args=[999]))

        self.assertEqual(response.status_code, 404)

    def test_message_detail_other_user(self):
        """测试访问其他用户的消息."""
        other_user = User.objects.create_user(
            username="other", password="pass123", email="other@example.com"
        )
        message = Message.objects.create(
            title="其他", content="内容", message_type=Message.MessageType.SYSTEM
        )
        UserMessage.objects.create(user=other_user, message=message)

        response = self.client.get(reverse("messages:detail", args=[message.id]))

        self.assertEqual(response.status_code, 404)

    def test_message_detail_deleted_message(self):
        """测试访问已删除的消息."""
        self.user_message.soft_delete()

        response = self.client.get(reverse("messages:detail", args=[self.message.id]))

        self.assertEqual(response.status_code, 404)


class MarkReadViewTests(TestCase):
    """标记已读视图测试."""

    def setUp(self):
        """设置测试数据."""
        self.user = User.objects.create_user(
            username="testuser", password="testpass123", email="test@example.com"
        )
        self.client.login(username="testuser", password="testpass123")

        self.messages = []
        for i in range(3):
            message = Message.objects.create(
                title=f"消息{i}",
                content=f"内容{i}",
                message_type=Message.MessageType.SYSTEM,
            )
            UserMessage.objects.create(user=self.user, message=message)
            self.messages.append(message)

    def test_mark_all_as_read(self):
        """测试标记所有消息为已读."""
        response = self.client.post(
            reverse("messages:mark_read"), HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data["success"])
        self.assertEqual(data["count"], 3)

    def test_mark_specific_messages_as_read(self):
        """测试标记指定消息为已读."""
        response = self.client.post(
            reverse("messages:mark_read"),
            {"message_ids[]": [self.messages[0].id, self.messages[1].id]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data["success"])
        self.assertEqual(data["count"], 2)

    def test_mark_read_redirect(self):
        """测试非 AJAX 请求重定向."""
        response = self.client.post(reverse("messages:mark_read"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("messages:list"))

    def test_mark_read_requires_post(self):
        """测试标记已读需要 POST 请求."""
        response = self.client.get(reverse("messages:mark_read"))

        self.assertEqual(response.status_code, 405)


class MarkUnreadViewTests(TestCase):
    """标记未读视图测试."""

    def setUp(self):
        """设置测试数据."""
        self.user = User.objects.create_user(
            username="testuser", password="testpass123", email="test@example.com"
        )
        self.client.login(username="testuser", password="testpass123")

        self.message = Message.objects.create(
            title="测试", content="内容", message_type=Message.MessageType.SYSTEM
        )
        self.user_message = UserMessage.objects.create(
            user=self.user, message=self.message
        )
        self.user_message.mark_as_read()

    def test_mark_as_unread(self):
        """测试标记为未读."""
        response = self.client.post(
            reverse("messages:mark_unread"),
            {"message_ids[]": [self.message.id]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data["success"])
        self.assertEqual(data["count"], 1)

    def test_mark_unread_without_ids(self):
        """测试没有指定消息 ID."""
        response = self.client.post(
            reverse("messages:mark_unread"), HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertFalse(data["success"])

    def test_mark_unread_redirects_for_non_ajax(self):
        """非 AJAX 请求应重定向到消息列表."""
        response = self.client.post(
            reverse("messages:mark_unread"), {"message_ids[]": [self.message.id]}
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("messages:list"))


class DeleteMessageViewTests(TestCase):
    """删除消息视图测试."""

    def setUp(self):
        """设置测试数据."""
        self.user = User.objects.create_user(
            username="testuser", password="testpass123", email="test@example.com"
        )
        self.client.login(username="testuser", password="testpass123")

        self.message = Message.objects.create(
            title="测试", content="内容", message_type=Message.MessageType.SYSTEM
        )
        self.user_message = UserMessage.objects.create(
            user=self.user, message=self.message
        )

    def test_delete_message(self):
        """测试删除消息."""
        response = self.client.post(
            reverse("messages:delete"),
            {"message_ids[]": [self.message.id]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data["success"])
        self.assertEqual(data["count"], 1)

        # 验证消息被软删除
        self.user_message.refresh_from_db()
        self.assertTrue(self.user_message.is_deleted)

    def test_delete_without_ids(self):
        """测试没有指定消息 ID."""
        response = self.client.post(
            reverse("messages:delete"), HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )

        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertFalse(data["success"])

    def test_delete_redirects_for_non_ajax(self):
        """非 AJAX 请求应重定向到消息列表."""
        response = self.client.post(
            reverse("messages:delete"), {"message_ids[]": [self.message.id]}
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("messages:list"))


class UnreadCountViewTests(TestCase):
    """未读消息数量视图测试."""

    def setUp(self):
        """设置测试数据."""
        self.user = User.objects.create_user(
            username="testuser", password="testpass123", email="test@example.com"
        )
        self.client.login(username="testuser", password="testpass123")

        for i in range(5):
            message = Message.objects.create(
                title=f"消息{i}",
                content=f"内容{i}",
                message_type=Message.MessageType.SYSTEM,
            )
            um = UserMessage.objects.create(user=self.user, message=message)
            if i < 2:
                um.mark_as_read()

    def test_get_unread_count(self):
        """测试获取未读数量."""
        response = self.client.get(reverse("messages:unread_count"))

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["count"], 3)

    def test_get_unread_count_by_type(self):
        """测试按类型获取未读数量."""
        # 创建支付类型的消息
        message = Message.objects.create(
            title="支付", content="内容", message_type=Message.MessageType.PAYMENT
        )
        UserMessage.objects.create(user=self.user, message=message)

        response = self.client.get(
            reverse("messages:unread_count") + f"?type={Message.MessageType.PAYMENT}"
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["count"], 1)


class MessageIntegrationTests(TestCase):
    """消息集成测试."""

    def setUp(self):
        """设置测试数据."""
        self.user = User.objects.create_user(
            username="testuser", password="testpass123", email="test@example.com"
        )
        self.client.login(username="testuser", password="testpass123")

    def test_complete_message_flow(self):
        """测试完整的消息流程."""
        # 1. 发送消息
        message = send_message(
            title="完整流程测试",
            content="这是一条测试消息",
            message_type=Message.MessageType.SYSTEM,
            recipients=[self.user],
        )

        # 2. 查看消息列表
        response = self.client.get(reverse("messages:list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["page_obj"]), 1)

        # 3. 查看消息详情
        response = self.client.get(reverse("messages:detail", args=[message.id]))
        self.assertEqual(response.status_code, 200)

        # 4. 验证自动标记为已读
        user_message = UserMessage.objects.get(user=self.user, message=message)
        self.assertTrue(user_message.is_read)

        # 5. 标记为未读
        response = self.client.post(
            reverse("messages:mark_unread"),
            {"message_ids[]": [message.id]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)

        # 6. 删除消息
        response = self.client.post(
            reverse("messages:delete"),
            {"message_ids[]": [message.id]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)

        # 7. 验证消息被删除
        user_message.refresh_from_db()
        self.assertTrue(user_message.is_deleted)

        # 8. 消息列表应该为空
        response = self.client.get(reverse("messages:list"))
        self.assertEqual(len(response.context["page_obj"]), 0)
