"""Database models for the points app."""

from django.conf import settings
from django.db import models


class Tag(models.Model):
    """积分标签模型, 用于分类和标识积分来源."""

    name = models.CharField(max_length=50, unique=True, verbose_name="标签名称")
    slug = models.SlugField(
        max_length=50, unique=True, blank=True, verbose_name="URL别名"
    )
    description = models.TextField(blank=True, verbose_name="描述")
    is_default = models.BooleanField(default=False, verbose_name="是否为默认标签")

    def __str__(self):
        """返回标签名称作为字符串表示."""
        return self.name

    def save(self, *args, **kwargs):
        """保存时自动生成 slug."""
        if not self.slug:
            from django.utils.text import slugify

            self.slug = slugify(self.name) or self.name
        super().save(*args, **kwargs)


class PointSource(models.Model):
    """积分来源模型, 记录用户获得的积分及其剩余量."""

    user_profile = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="point_sources"
    )
    initial_points = models.PositiveIntegerField(verbose_name="初始积分")
    remaining_points = models.PositiveIntegerField(verbose_name="剩余积分")
    tags = models.ManyToManyField(
        Tag, related_name="point_sources", verbose_name="标签"
    )
    created_at = models.DateTimeField(
        auto_now_add=True, db_index=True, verbose_name="获得时间"
    )
    expires_at = models.DateTimeField(
        null=True, blank=True, db_index=True, verbose_name="过期时间"
    )

    notes = models.TextField(blank=True, verbose_name="备注")

    class Meta:
        """模型元数据配置."""

        ordering = ["created_at"]  # 优先消耗最早获得的积分 (FIFO)


class PointTransaction(models.Model):
    """积分交易记录模型, 记录用户积分的获得和消费."""

    class TransactionType(models.TextChoices):
        """交易类型枚举."""

        EARN = "EARN", "获得"
        SPEND = "SPEND", "消费"
        # ... other types

    user_profile = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="point_transactions",
    )
    points = models.IntegerField(verbose_name="变动积分")
    transaction_type = models.CharField(max_length=10, choices=TransactionType.choices)
    description = models.CharField(max_length=255, verbose_name="描述")
    consumed_sources = models.ManyToManyField(
        PointSource, related_name="consuming_transactions"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        """模型元数据配置."""

        ordering = ["-created_at"]
