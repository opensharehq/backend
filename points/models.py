"""Database models for the points app."""

from django.conf import settings
from django.db import models


class _UserAliasQuerySet(models.QuerySet):
    """Translate legacy user_profile lookups to the current user field."""

    legacy_name = "user_profile"
    field_name = "user"

    def _alias_lookup(self, key: str) -> str:
        if key.startswith(f"{self.legacy_name}__"):
            suffix = key[len(self.legacy_name) + 2 :]
            return f"{self.field_name}__{suffix}"
        if key == self.legacy_name:
            return self.field_name
        return key

    def _alias_kwargs(self, kwargs: dict) -> dict:
        if not kwargs:
            return kwargs
        return {self._alias_lookup(key): value for key, value in kwargs.items()}

    def _alias_field(self, field: str) -> str:
        if not field:
            return field
        prefix = ""
        core = field
        if field[0] in {"-", "+"}:
            prefix, core = field[0], field[1:]
        core = self._alias_lookup(core)
        return f"{prefix}{core}"

    def filter(self, *args, **kwargs):
        return super().filter(*args, **self._alias_kwargs(kwargs))

    def exclude(self, *args, **kwargs):
        return super().exclude(*args, **self._alias_kwargs(kwargs))

    def get(self, *args, **kwargs):
        return super().get(*args, **self._alias_kwargs(kwargs))

    def order_by(self, *field_names):
        aliased = [self._alias_field(name) for name in field_names]
        return super().order_by(*aliased)

    def values(self, *fields, **expressions):
        aliased_fields = [self._alias_field(field) for field in fields]
        aliased_expressions = {
            self._alias_field(key): value for key, value in expressions.items()
        }
        return super().values(*aliased_fields, **aliased_expressions)

    def values_list(self, *fields, **kwargs):
        aliased_fields = [self._alias_field(field) for field in fields]
        return super().values_list(*aliased_fields, **kwargs)


PointSourceQuerySet = _UserAliasQuerySet
PointTransactionQuerySet = _UserAliasQuerySet


class PointSourceManager(models.Manager.from_queryset(PointSourceQuerySet)):
    """Manager providing legacy user_profile lookup support."""


class PointTransactionManager(models.Manager.from_queryset(PointTransactionQuerySet)):
    """Manager providing legacy user_profile lookup support."""


class Tag(models.Model):
    """积分标签模型, 用于分类和标识积分来源."""

    name = models.CharField(max_length=50, unique=True, verbose_name="标签名称")
    slug = models.SlugField(
        max_length=50, unique=True, blank=True, verbose_name="URL别名"
    )
    description = models.TextField(blank=True, verbose_name="描述")
    is_default = models.BooleanField(default=False, verbose_name="是否为默认标签")
    withdrawable = models.BooleanField(default=False, verbose_name="是否可提现")

    class Meta:
        """模型元数据配置."""

        verbose_name = "积分标签"
        verbose_name_plural = verbose_name

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

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="point_sources",
        verbose_name="用户",
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

    objects = PointSourceManager()

    class Meta:
        """模型元数据配置."""

        ordering = ["created_at"]  # 优先消耗最早获得的积分 (FIFO)
        verbose_name = "积分池"
        verbose_name_plural = verbose_name

    def __init__(self, *args, **kwargs):
        """允许使用 legacy user_profile 参数初始化."""
        user_profile = kwargs.pop("user_profile", None)
        super().__init__(*args, **kwargs)
        if user_profile is not None:
            self.user = user_profile

    @property
    def user_profile(self):
        """提供与历史字段兼容的访问方式."""
        return self.user

    @user_profile.setter
    def user_profile(self, value):
        self.user = value

    @property
    def is_withdrawable(self):
        """判断积分池是否可提现, 基于关联的标签."""
        return self.tags.filter(withdrawable=True).exists()


class PointTransaction(models.Model):
    """积分交易记录模型, 记录用户积分的获得和消费."""

    class TransactionType(models.TextChoices):
        """交易类型枚举."""

        EARN = "EARN", "获得"
        SPEND = "SPEND", "消费"
        # ... other types

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="point_transactions",
        verbose_name="用户",
    )
    points = models.IntegerField(verbose_name="变动积分")
    transaction_type = models.CharField(max_length=10, choices=TransactionType.choices)
    description = models.CharField(max_length=255, verbose_name="描述")
    consumed_sources = models.ManyToManyField(
        PointSource, related_name="consuming_transactions"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = PointTransactionManager()

    class Meta:
        """模型元数据配置."""

        ordering = ["-created_at"]
        verbose_name = "积分交易记录"
        verbose_name_plural = verbose_name

    def __init__(self, *args, **kwargs):
        """允许使用 legacy user_profile 参数初始化."""
        user_profile = kwargs.pop("user_profile", None)
        super().__init__(*args, **kwargs)
        if user_profile is not None:
            self.user = user_profile

    @property
    def user_profile(self):
        """历史兼容的用户访问属性."""
        return self.user

    @user_profile.setter
    def user_profile(self, value):
        self.user = value
