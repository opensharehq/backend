"""消息服务层测试."""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from messages.models import Message, UserMessage
from messages.services import (
    MessageError,
    delete_messages,
    get_message_stats,
    get_unread_count,
    get_user_messages,
    mark_as_read,
    mark_as_unread,
    send_message,
)

User = get_user_model()


class SendMessageTests(TestCase):
    """发送消息测试."""

    def setUp(self):
        """设置测试数据."""
        self.user1 = User.objects.create_user(
            username="user1", email="user1@example.com"
        )
        self.user2 = User.objects.create_user(
            username="user2", email="user2@example.com"
        )
        self.sender = User.objects.create_user(
            username="sender", email="sender@example.com"
        )

    def test_send_message_to_users(self):
        """测试发送消息给指定用户."""
        message = send_message(
            title="测试消息",
            content="这是一条测试消息",
            message_type=Message.MessageType.SYSTEM,
            recipients=[self.user1, self.user2],
        )

        self.assertIsNotNone(message)
        self.assertEqual(message.title, "测试消息")
        self.assertEqual(message.get_recipient_count(), 2)

        # 验证用户消息创建
        self.assertTrue(
            UserMessage.objects.filter(user=self.user1, message=message).exists()
        )
        self.assertTrue(
            UserMessage.objects.filter(user=self.user2, message=message).exists()
        )

    def test_send_broadcast_message(self):
        """测试发送广播消息."""
        # 创建更多用户
        User.objects.create_user(username="user3", email="user3@example.com")

        message = send_message(
            title="广播消息",
            content="这是一条广播消息",
            message_type=Message.MessageType.ANNOUNCEMENT,
            is_broadcast=True,
        )

        self.assertTrue(message.is_broadcast)
        # 应该发送给所有激活的用户（user1, user2, user3, sender）
        self.assertEqual(message.get_recipient_count(), 4)

    def test_send_message_with_sender(self):
        """测试发送带发送者的消息."""
        message = send_message(
            title="个人消息",
            content="这是一条个人消息",
            message_type=Message.MessageType.PERSONAL,
            sender=self.sender,
            recipients=[self.user1],
        )

        self.assertEqual(message.sender, self.sender)

    def test_send_message_without_title(self):
        """测试发送没有标题的消息应该失败."""
        with self.assertRaises(MessageError):
            send_message(title="", content="内容", recipients=[self.user1])

    def test_send_message_without_content(self):
        """测试发送没有内容的消息应该失败."""
        with self.assertRaises(MessageError):
            send_message(title="标题", content="", recipients=[self.user1])

    def test_send_message_broadcast_with_recipients(self):
        """测试广播消息不能同时指定接收者."""
        with self.assertRaises(MessageError):
            send_message(
                title="测试", content="内容", is_broadcast=True, recipients=[self.user1]
            )

    def test_send_message_without_recipients_or_broadcast(self):
        """测试非广播消息必须指定接收者."""
        with self.assertRaises(MessageError):
            send_message(title="测试", content="内容", is_broadcast=False)

    def test_send_broadcast_uses_batches(self):
        """测试广播消息按批次写入，触发循环中的批处理逻辑。"""
        # 创建多一些用户以确保达到批处理阈值
        extra_users = [
            User.objects.create_user(
                username=f"user_batch_{i}", email=f"batch{i}@example.com"
            )
            for i in range(3)
        ]

        with mock.patch("messages.services.BROADCAST_BATCH_SIZE", 1):
            message = send_message(title="广播", content="批处理", is_broadcast=True)

        # 所有激活用户都应收到消息
        expected_count = 3 + len(extra_users)  # user1,user2,sender plus extras
        self.assertEqual(message.get_recipient_count(), expected_count)
        # 确保最后一个批次的 bulk_create 也执行了
        self.assertEqual(
            UserMessage.objects.filter(message=message).count(), expected_count
        )

    def test_send_message_ignores_inactive_users_in_broadcast(self):
        """测试广播消息不会发送给未激活的用户."""
        self.user2.is_active = False
        self.user2.save()

        message = send_message(title="广播", content="内容", is_broadcast=True)

        # 只应该发送给激活用户
        self.assertFalse(
            UserMessage.objects.filter(user=self.user2, message=message).exists()
        )


class GetUserMessagesTests(TestCase):
    """获取用户消息测试."""

    def setUp(self):
        """设置测试数据."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com"
        )

        self.message1 = Message.objects.create(
            title="消息1", content="内容1", message_type=Message.MessageType.SYSTEM
        )
        self.message2 = Message.objects.create(
            title="消息2", content="内容2", message_type=Message.MessageType.PAYMENT
        )

        self.um1 = UserMessage.objects.create(user=self.user, message=self.message1)
        self.um2 = UserMessage.objects.create(user=self.user, message=self.message2)

    def test_get_all_messages(self):
        """测试获取所有消息."""
        messages = get_user_messages(self.user)
        self.assertEqual(messages.count(), 2)

    def test_get_unread_messages_only(self):
        """测试仅获取未读消息."""
        self.um1.mark_as_read()

        messages = get_user_messages(self.user, only_unread=True)
        self.assertEqual(messages.count(), 1)
        self.assertEqual(messages.first(), self.um2)

    def test_get_messages_by_type(self):
        """测试按类型过滤消息."""
        messages = get_user_messages(
            self.user, message_type=Message.MessageType.PAYMENT
        )
        self.assertEqual(messages.count(), 1)
        self.assertEqual(messages.first().message, self.message2)

    def test_exclude_deleted_messages(self):
        """测试排除已删除的消息."""
        self.um1.soft_delete()

        messages = get_user_messages(self.user)
        self.assertEqual(messages.count(), 1)

    def test_include_deleted_messages(self):
        """测试包含已删除的消息."""
        self.um1.soft_delete()

        messages = get_user_messages(self.user, include_deleted=True)
        self.assertEqual(messages.count(), 2)


class GetUnreadCountTests(TestCase):
    """获取未读消息数量测试."""

    def setUp(self):
        """设置测试数据."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com"
        )

        for i in range(3):
            message = Message.objects.create(
                title=f"消息{i}",
                content=f"内容{i}",
                message_type=Message.MessageType.SYSTEM,
            )
            UserMessage.objects.create(user=self.user, message=message)

    def test_get_unread_count(self):
        """测试获取未读消息数量."""
        count = get_unread_count(self.user)
        self.assertEqual(count, 3)

    def test_get_unread_count_after_reading(self):
        """测试阅读后的未读数量."""
        um = UserMessage.objects.filter(user=self.user).first()
        um.mark_as_read()

        count = get_unread_count(self.user)
        self.assertEqual(count, 2)

    def test_get_unread_count_by_type(self):
        """测试按类型获取未读数量."""
        # 创建不同类型的消息
        message = Message.objects.create(
            title="支付", content="内容", message_type=Message.MessageType.PAYMENT
        )
        UserMessage.objects.create(user=self.user, message=message)

        count = get_unread_count(self.user, message_type=Message.MessageType.PAYMENT)
        self.assertEqual(count, 1)

    def test_get_unread_count_excludes_deleted(self):
        """测试未读数量不包含已删除的消息."""
        um = UserMessage.objects.filter(user=self.user).first()
        um.soft_delete()

        count = get_unread_count(self.user)
        self.assertEqual(count, 2)


class MarkAsReadTests(TestCase):
    """标记为已读测试."""

    def setUp(self):
        """设置测试数据."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com"
        )

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
        count = mark_as_read(self.user)

        self.assertEqual(count, 3)
        self.assertEqual(get_unread_count(self.user), 0)

    def test_mark_specific_messages_as_read(self):
        """测试标记指定消息为已读."""
        message_ids = [self.messages[0].id, self.messages[1].id]
        count = mark_as_read(self.user, message_ids)

        self.assertEqual(count, 2)
        self.assertEqual(get_unread_count(self.user), 1)

    def test_mark_as_read_already_read_messages(self):
        """测试标记已读消息."""
        mark_as_read(self.user)

        # 再次标记应该返回 0
        count = mark_as_read(self.user)
        self.assertEqual(count, 0)

    def test_mark_as_read_excludes_deleted(self):
        """测试标记已读时排除已删除的消息."""
        um = UserMessage.objects.filter(user=self.user).first()
        um.soft_delete()

        count = mark_as_read(self.user)
        self.assertEqual(count, 2)


class MarkAsUnreadTests(TestCase):
    """标记为未读测试."""

    def setUp(self):
        """设置测试数据."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com"
        )

        self.messages = []
        for i in range(3):
            message = Message.objects.create(
                title=f"消息{i}",
                content=f"内容{i}",
                message_type=Message.MessageType.SYSTEM,
            )
            um = UserMessage.objects.create(user=self.user, message=message)
            um.mark_as_read()
            self.messages.append(message)

    def test_mark_as_unread(self):
        """测试标记为未读."""
        message_ids = [self.messages[0].id]
        count = mark_as_unread(self.user, message_ids)

        self.assertEqual(count, 1)
        self.assertEqual(get_unread_count(self.user), 1)

    def test_mark_as_unread_already_unread(self):
        """测试标记未读消息为未读."""
        um = UserMessage.objects.filter(user=self.user).first()
        um.mark_as_unread()

        count = mark_as_unread(self.user, [um.message.id])
        self.assertEqual(count, 0)


class DeleteMessagesTests(TestCase):
    """删除消息测试."""

    def setUp(self):
        """设置测试数据."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com"
        )

        self.messages = []
        for i in range(3):
            message = Message.objects.create(
                title=f"消息{i}",
                content=f"内容{i}",
                message_type=Message.MessageType.SYSTEM,
            )
            UserMessage.objects.create(user=self.user, message=message)
            self.messages.append(message)

    def test_delete_messages(self):
        """测试删除消息."""
        message_ids = [self.messages[0].id, self.messages[1].id]
        count = delete_messages(self.user, message_ids)

        self.assertEqual(count, 2)

        # 验证消息被软删除
        deleted = UserMessage.objects.filter(user=self.user, is_deleted=True)
        self.assertEqual(deleted.count(), 2)

    def test_delete_already_deleted_messages(self):
        """测试删除已删除的消息."""
        um = UserMessage.objects.filter(user=self.user).first()
        um.soft_delete()

        count = delete_messages(self.user, [um.message.id])
        self.assertEqual(count, 0)


class GetMessageStatsTests(TestCase):
    """获取消息统计测试."""

    def setUp(self):
        """设置测试数据."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com"
        )

        # 创建不同类型的消息
        for i in range(2):
            message = Message.objects.create(
                title=f"系统{i}",
                content=f"内容{i}",
                message_type=Message.MessageType.SYSTEM,
            )
            UserMessage.objects.create(user=self.user, message=message)

        for i in range(3):
            message = Message.objects.create(
                title=f"支付{i}",
                content=f"内容{i}",
                message_type=Message.MessageType.PAYMENT,
            )
            um = UserMessage.objects.create(user=self.user, message=message)
            if i < 2:  # 标记前两条为已读
                um.mark_as_read()

    def test_get_message_stats(self):
        """测试获取消息统计."""
        stats = get_message_stats(self.user)

        self.assertEqual(stats["total"], 5)
        self.assertEqual(stats["unread"], 3)
        self.assertEqual(stats["read"], 2)

    def test_get_message_stats_by_type(self):
        """测试按类型统计."""
        stats = get_message_stats(self.user)

        type_counts = stats["type_counts"]
        self.assertEqual(type_counts[Message.MessageType.SYSTEM], 2)
        self.assertEqual(type_counts[Message.MessageType.PAYMENT], 1)  # 只有 1 条未读

    def test_get_message_stats_excludes_deleted(self):
        """测试统计不包含已删除的消息."""
        um = UserMessage.objects.filter(user=self.user).first()
        um.soft_delete()

        stats = get_message_stats(self.user)
        self.assertEqual(stats["total"], 4)
