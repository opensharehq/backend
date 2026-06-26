"""站内信数据模型."""

from django.conf import settings
from django.db import models
from django.utils import timezone


class Message(models.Model):
    """站内信消息模型."""

    class MessageType(models.TextChoices):
        """消息类型枚举."""

        SYSTEM = "system", "系统消息"
        PERSONAL = "personal", "个人消息"
        PAYMENT = "payment", "支付信息"
        SHIPPING = "shipping", "发货信息"
        ACTIVITY = "activity", "活动通知"
        ANNOUNCEMENT = "announcement", "公告"
        POINTS = "points", "积分变动"
        ORDER = "order", "订单信息"
        SECURITY = "security", "安全提醒"
        WITHDRAWAL = "withdrawal", "提现信息"
        OUTREACH = "outreach", "Outreach"

    title = models.CharField(max_length=200, verbose_name="标题")
    content = models.TextField(verbose_name="内容(Markdown)")
    message_type = models.CharField(
        max_length=20,
        choices=MessageType.choices,
        default=MessageType.SYSTEM,
        verbose_name="消息类型",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_messages",
        verbose_name="发送者",
        help_text="留空表示系统消息",
    )
    is_broadcast = models.BooleanField(
        default=False, verbose_name="广播消息", help_text="是否发送给全站用户"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        """模型元数据."""

        verbose_name = "消息"
        verbose_name_plural = "消息"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["message_type"]),
            models.Index(fields=["is_broadcast"]),
        ]

    def __str__(self):
        """字符串表示."""
        return f"{self.get_message_type_display()}: {self.title}"

    def get_recipient_count(self):
        """获取接收者数量."""
        return self.user_messages.count()


class UserMessage(models.Model):
    """用户消息关联模型."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_messages",
        verbose_name="用户",
    )
    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="user_messages",
        verbose_name="消息",
    )
    is_read = models.BooleanField(default=False, verbose_name="已读")
    read_at = models.DateTimeField(null=True, blank=True, verbose_name="阅读时间")
    is_deleted = models.BooleanField(
        default=False, verbose_name="已删除", help_text="用户端软删除"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="接收时间")

    class Meta:
        """模型元数据."""

        verbose_name = "用户消息"
        verbose_name_plural = "用户消息"
        ordering = ["-created_at"]
        unique_together = [["user", "message"]]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["user", "is_read"]),
            models.Index(fields=["user", "is_deleted"]),
            models.Index(fields=["message", "is_read"]),
        ]

    def __str__(self):
        """字符串表示."""
        return f"{self.user.username} - {self.message.title}"

    def mark_as_read(self):
        """标记为已读."""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])

    def mark_as_unread(self):
        """标记为未读."""
        if self.is_read:
            self.is_read = False
            self.read_at = None
            self.save(update_fields=["is_read", "read_at"])

    def soft_delete(self):
        """软删除."""
        if not self.is_deleted:
            self.is_deleted = True
            self.save(update_fields=["is_deleted"])
