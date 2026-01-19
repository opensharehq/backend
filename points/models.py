"""Data models for points application."""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class PointType(models.TextChoices):
    """Point type choices."""

    CASH = "cash", "现金积分"
    GIFT = "gift", "礼物积分"


class TransactionType(models.TextChoices):
    """Transaction type choices."""

    EARN = "earn", "获取"
    SPEND = "spend", "消费"
    WITHDRAW = "withdraw", "提现"
    EXPIRE = "expire", "过期"


class WithdrawalStatus(models.TextChoices):
    """Withdrawal status choices."""

    PENDING = "pending", "待审核"
    APPROVED = "approved", "已批准"
    REJECTED = "rejected", "已拒绝"
    COMPLETED = "completed", "已完成"
    CANCELLED = "cancelled", "已取消"


class Tag(models.Model):
    """积分标签模型, 用于分类礼物积分来源."""

    name = models.CharField(max_length=50, unique=True, verbose_name="标签名称")
    slug = models.SlugField(max_length=50, unique=True, verbose_name="URL别名")
    description = models.TextField(blank=True, verbose_name="标签描述")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        """Model metadata."""

        verbose_name = "积分标签"
        verbose_name_plural = verbose_name
        ordering = ["name"]

    def __str__(self):
        """Return string representation."""
        return self.name


class PointWallet(models.Model):
    """积分钱包模型, 支持用户和组织."""

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        verbose_name="所有者类型",
    )
    object_id = models.PositiveIntegerField(verbose_name="所有者ID")
    owner = GenericForeignKey("content_type", "object_id")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        """Model metadata."""

        verbose_name = "积分钱包"
        verbose_name_plural = verbose_name
        unique_together = [["content_type", "object_id"]]
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self):
        """Return string representation."""
        return f"钱包 #{self.id} ({self.owner})"

    def get_cash_balance(self):
        """获取现金积分余额."""
        return (
            self.sources.filter(
                point_type=PointType.CASH,
                remaining_amount__gt=0,
            ).aggregate(total=models.Sum("remaining_amount"))["total"]
            or 0
        )

    def get_gift_balance(self, tag_slug=None):
        """获取礼物积分余额, 可按标签筛选."""
        queryset = self.sources.filter(
            point_type=PointType.GIFT,
            remaining_amount__gt=0,
        )
        if tag_slug:
            queryset = queryset.filter(tag__slug=tag_slug)
        return queryset.aggregate(total=models.Sum("remaining_amount"))["total"] or 0

    def get_total_balance(self):
        """获取总积分余额."""
        return self.get_cash_balance() + self.get_gift_balance()


class PointSource(models.Model):
    """积分来源模型, 记录每笔积分的来源和消费情况."""

    wallet = models.ForeignKey(
        PointWallet,
        on_delete=models.CASCADE,
        related_name="sources",
        verbose_name="所属钱包",
    )
    point_type = models.CharField(
        max_length=10,
        choices=PointType.choices,
        verbose_name="积分类型",
        db_index=True,
    )
    tag = models.ForeignKey(
        Tag,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="point_sources",
        verbose_name="积分标签",
        help_text="仅礼物积分可设置标签",
    )
    original_amount = models.PositiveIntegerField(verbose_name="原始金额")
    remaining_amount = models.PositiveIntegerField(verbose_name="剩余金额")
    reason = models.CharField(max_length=200, verbose_name="发放原因")
    reference_id = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="关联ID",
        help_text="用于关联外部系统的ID",
        db_index=True,
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="过期时间",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_point_sources",
        verbose_name="创建者",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        """Model metadata."""

        verbose_name = "积分来源"
        verbose_name_plural = verbose_name
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["wallet", "point_type", "remaining_amount"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        """Return string representation."""
        tag_str = f" [{self.tag.name}]" if self.tag else ""
        return (
            f"{self.get_point_type_display()}{tag_str}: "
            f"{self.remaining_amount}/{self.original_amount}"
        )


class PointTransaction(models.Model):
    """积分交易记录模型, 不可变账本."""

    wallet = models.ForeignKey(
        PointWallet,
        on_delete=models.CASCADE,
        related_name="transactions",
        verbose_name="所属钱包",
    )
    transaction_type = models.CharField(
        max_length=10,
        choices=TransactionType.choices,
        verbose_name="交易类型",
        db_index=True,
    )
    point_type = models.CharField(
        max_length=10,
        choices=PointType.choices,
        verbose_name="积分类型",
    )
    amount = models.IntegerField(verbose_name="交易金额")
    balance_after = models.PositiveIntegerField(verbose_name="交易后余额")
    description = models.CharField(max_length=200, verbose_name="交易描述")
    reference_id = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="关联ID",
        db_index=True,
    )
    source = models.ForeignKey(
        PointSource,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        verbose_name="积分来源",
    )
    tag = models.ForeignKey(
        Tag,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        verbose_name="积分标签",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_point_transactions",
        verbose_name="创建者",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        """Model metadata."""

        verbose_name = "积分交易"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["wallet", "transaction_type"]),
            models.Index(fields=["wallet", "point_type"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        """Return string representation."""
        sign = "+" if self.amount > 0 else ""
        return f"{self.get_transaction_type_display()}: {sign}{self.amount}"


class WithdrawalRequest(models.Model):
    """提现申请模型."""

    wallet = models.ForeignKey(
        PointWallet,
        on_delete=models.CASCADE,
        related_name="withdrawals",
        verbose_name="所属钱包",
    )
    amount = models.PositiveIntegerField(verbose_name="提现金额")
    status = models.CharField(
        max_length=20,
        choices=WithdrawalStatus.choices,
        default=WithdrawalStatus.PENDING,
        verbose_name="状态",
        db_index=True,
    )

    # 提现人信息
    real_name = models.CharField(max_length=50, verbose_name="真实姓名")
    phone = models.CharField(max_length=20, verbose_name="联系电话")

    # 银行账户信息
    bank_name = models.CharField(max_length=100, verbose_name="银行名称")
    bank_account = models.CharField(max_length=50, verbose_name="银行账号")

    # 审核信息
    admin_note = models.TextField(blank=True, verbose_name="管理员备注")
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="processed_withdrawals",
        verbose_name="处理人",
    )
    processed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="处理时间",
    )

    # 关联交易记录
    transaction = models.OneToOneField(
        PointTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="withdrawal",
        verbose_name="关联交易",
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        """Model metadata."""

        verbose_name = "提现申请"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        """Return string representation."""
        return f"提现申请 #{self.id}: {self.amount} ({self.get_status_display()})"
