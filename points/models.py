"""Data models for points application."""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class PointType(models.TextChoices):
    """Point type choices."""

    CASH = "cash", "现金积分"
    GIFT = "gift", "礼物积分"


class TagType(models.TextChoices):
    """Tag type choices."""

    GENERAL = "general", "通用标签"
    ORG = "org", "组织标签"
    REPO = "repo", "仓库标签"
    USER = "user", "用户标签"


class AllocationStatus(models.TextChoices):
    """Allocation status choices."""

    DRAFT = "draft", "草稿"
    PREVIEWING = "previewing", "预览中"
    EXECUTING = "executing", "执行中"
    COMPLETED = "completed", "已完成"
    FAILED = "failed", "失败"


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
    """积分标签模型, 用于分类礼物积分来源和项目/用户范围筛选."""

    name = models.CharField(max_length=50, unique=True, verbose_name="标签名称")
    slug = models.SlugField(max_length=50, unique=True, verbose_name="URL别名")
    description = models.TextField(blank=True, verbose_name="标签描述")

    # 新增字段: 标签类型
    tag_type = models.CharField(
        max_length=20,
        choices=TagType.choices,
        default=TagType.GENERAL,
        verbose_name="标签类型",
        db_index=True,
    )
    entity_identifier = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="实体标识",
        help_text="组织名称、仓库全名(owner/repo)或用户标识",
    )
    is_official = models.BooleanField(
        default=True,
        verbose_name="官方标签",
        help_text="是否为 OpenDigger 官方标签",
        db_index=True,
    )

    # 私有标签的所有者（使用 GenericForeignKey）
    owner_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="owned_tags",
        verbose_name="所有者类型",
        help_text="私有标签的所有者类型",
    )
    owner_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="所有者ID",
    )
    owner = GenericForeignKey("owner_type", "owner_id")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        """Model metadata."""

        verbose_name = "积分标签"
        verbose_name_plural = verbose_name
        ordering = ["name"]
        indexes = [
            models.Index(fields=["tag_type"]),
            models.Index(fields=["is_official"]),
            models.Index(fields=["owner_type", "owner_id"]),
        ]

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
    id_card = models.CharField(max_length=18, verbose_name="身份证号", default="")

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


class PendingPointGrant(models.Model):
    """
    未注册用户的待领取积分.

    设计要点:
    1. 每次向未注册用户发放积分都会创建一条记录
    2. 记录永久保留, 不会删除(即使已领取)
    3. 用户注册后通过 GitHub ID/login/email 匹配并自动领取
    4. 支持完整的历史追溯和审计
    """

    # 用户识别信息（至少一个）
    github_id = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="GitHub ID",
        db_index=True,
    )
    github_login = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="GitHub 用户名",
        db_index=True,
    )
    email = models.EmailField(
        blank=True,
        verbose_name="邮箱",
        db_index=True,
    )

    # 积分信息
    amount = models.PositiveIntegerField(verbose_name="积分金额")
    point_type = models.CharField(
        max_length=10,
        choices=PointType.choices,
        verbose_name="积分类型",
    )
    reason = models.CharField(max_length=200, verbose_name="发放原因")
    tag = models.ForeignKey(
        Tag,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pending_grants",
        verbose_name="积分标签",
    )
    reference_id = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="关联ID",
    )

    # 发放者信息
    granter_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        verbose_name="发放者类型",
    )
    granter_id = models.PositiveIntegerField(verbose_name="发放者ID")
    granter = GenericForeignKey("granter_type", "granter_id")

    # 状态（领取后不删除记录，仅更新状态）
    is_claimed = models.BooleanField(
        default=False,
        verbose_name="已领取",
        db_index=True,
    )
    claimed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="claimed_pending_points",
        verbose_name="领取人",
    )
    claimed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="领取时间",
    )

    # 关联的分配配置（保留完整的分配上下文）
    allocation = models.ForeignKey(
        "PointAllocation",
        on_delete=models.CASCADE,
        related_name="pending_grants",
        verbose_name="所属分配",
    )

    # 时间戳（永久保留）
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="过期时间",
    )

    class Meta:
        """Model metadata."""

        verbose_name = "待领取积分"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_claimed"]),
            models.Index(fields=["github_id", "is_claimed"]),
            models.Index(fields=["github_login", "is_claimed"]),
            models.Index(fields=["email", "is_claimed"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        """Return string representation."""
        status = "已领取" if self.is_claimed else "待领取"
        return f"{self.github_login or self.email}: {self.amount} ({status})"


class PointAllocation(models.Model):
    """
    积分分配记录.

    设计要点:
    1. 记录每次积分分配的完整配置
    2. 保存贡献度数据快照(contribution_data)
    3. 通过 pending_grants 反向关系访问所有待领取记录
    4. 永久保留, 不删除
    """

    # 发起者
    initiator_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        verbose_name="发起者类型",
    )
    initiator_id = models.PositiveIntegerField(verbose_name="发起者ID")
    initiator = GenericForeignKey("initiator_type", "initiator_id")

    # 积分池信息
    source_pool = models.ForeignKey(
        PointSource,
        on_delete=models.PROTECT,
        related_name="allocations",
        verbose_name="积分池",
    )
    total_amount = models.PositiveIntegerField(
        verbose_name="本次分配总额",
        help_text="本次分配总额",
    )

    # 项目范围（JSON）
    project_scope = models.JSONField(
        verbose_name="项目范围",
        help_text="项目筛选配置 {tags: [...], operation: 'AND'}",
    )

    # 用户范围（JSON，可选）
    user_scope = models.JSONField(
        null=True,
        blank=True,
        verbose_name="用户范围",
        help_text="用户筛选配置 {tags: [...], operation: 'AND'}",
    )

    # 时间周期
    start_month = models.DateField(
        verbose_name="起始月份",
        help_text="起始月份（月初）",
    )
    end_month = models.DateField(
        verbose_name="结束月份",
        help_text="结束月份（月初）",
    )

    # 调整参数
    adjustment_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=1.0,
        verbose_name="全局调整比例",
        help_text="全局调整比例",
    )
    individual_adjustments = models.JSONField(
        default=dict,
        verbose_name="单独调整",
        help_text="单个用户调整 {user_id: amount}",
    )

    # 贡献度数据快照（JSON）
    contribution_data = models.JSONField(
        default=list,
        verbose_name="贡献度数据",
        help_text="贡献度数据快照",
    )

    # 状态
    status = models.CharField(
        max_length=20,
        choices=AllocationStatus.choices,
        default=AllocationStatus.DRAFT,
        verbose_name="状态",
        db_index=True,
    )

    # 统计
    total_recipients = models.PositiveIntegerField(
        default=0,
        verbose_name="总接收人数",
    )
    registered_recipients = models.PositiveIntegerField(
        default=0,
        verbose_name="已注册人数",
    )
    unregistered_recipients = models.PositiveIntegerField(
        default=0,
        verbose_name="未注册人数",
    )

    # 时间戳
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    executed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="执行时间",
    )

    class Meta:
        """Model metadata."""

        verbose_name = "积分分配"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["initiator_type", "initiator_id"]),
        ]

    def __str__(self):
        """Return string representation."""
        return f"分配 #{self.id}: {self.total_amount} ({self.get_status_display()})"


class ContributionCache(models.Model):
    """贡献度数据缓存."""

    # 项目标识（如 "alibaba/spring-cloud-alibaba"）
    project_identifier = models.CharField(
        max_length=200,
        verbose_name="项目标识",
        db_index=True,
    )

    # 用户标识
    github_id = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="GitHub ID",
    )
    github_login = models.CharField(
        max_length=100,
        verbose_name="GitHub 用户名",
        db_index=True,
    )
    email = models.EmailField(blank=True, verbose_name="邮箱")

    # 时间周期
    start_month = models.DateField(verbose_name="起始月份")
    end_month = models.DateField(verbose_name="结束月份")

    # 贡献度值
    contribution_score = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="贡献度",
    )

    # 元数据
    raw_data = models.JSONField(
        default=dict,
        verbose_name="原始数据",
        help_text="原始 OpenDigger 数据",
    )

    # 缓存时间
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        """Model metadata."""

        verbose_name = "贡献度缓存"
        verbose_name_plural = verbose_name
        unique_together = [
            ("project_identifier", "github_login", "start_month", "end_month")
        ]
        indexes = [
            models.Index(fields=["project_identifier", "start_month", "end_month"]),
        ]

    def __str__(self):
        """Return string representation."""
        return f"{self.github_login} @ {self.project_identifier}: {self.contribution_score}"
