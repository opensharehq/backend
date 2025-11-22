"""User models for accounts app."""

import uuid

from django.contrib.auth.models import AbstractUser, UserManager
from django.core.cache import cache
from django.db import models
from django.db.models import Q, Sum

TOTAL_POINTS_CACHE_KEY_TEMPLATE = "fullsite:accounts:user_total_points:{user_id}"
TOTAL_POINTS_CACHE_TIMEOUT = 300
WITHDRAWABLE_POINTS_CACHE_KEY_TEMPLATE = (
    "fullsite:accounts:user_withdrawable_points:{user_id}"
)
WITHDRAWABLE_POINTS_CACHE_TIMEOUT = 300


class UserQuerySet(models.QuerySet):
    """Custom queryset for User model with point-related annotations."""

    def annotate_with_points(self):
        """
        Annotate users with total points.

        Use this for efficient bulk queries instead of accessing total_points property.
        """
        return self.annotate(
            total_points_calculated=models.Sum("point_sources__remaining_points")
        )


class CustomUserManager(UserManager):
    """Custom manager for User model."""

    def get_queryset(self):
        """Return custom queryset."""
        return UserQuerySet(self.model, using=self._db)

    def annotate_with_points(self):
        """Proxy to queryset method."""
        return self.get_queryset().annotate_with_points()


class User(AbstractUser):
    """Custom user model extending AbstractUser."""

    is_active = models.BooleanField(default=True)
    merged_into = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="merged_children",
        verbose_name="合并到",
    )

    objects = CustomUserManager()

    class Meta:
        """Meta configuration for User."""

        verbose_name = "用户"
        verbose_name_plural = verbose_name

    @property
    def total_points(self):
        """
        Get total points for the user (cached).

        Cache is automatically cleared when PointSource or PointTransaction is modified.
        For up-to-date values in queries, use User.objects.annotate_with_points() instead.
        """
        cache_key = TOTAL_POINTS_CACHE_KEY_TEMPLATE.format(user_id=self.pk)
        cached_total = cache.get(cache_key)
        if cached_total is not None:
            return cached_total

        total = (
            self.point_sources.aggregate(total=Sum("remaining_points"))["total"] or 0
        )
        cache.set(cache_key, total, TOTAL_POINTS_CACHE_TIMEOUT)
        return total

    def clear_points_cache(self):
        """Clear cached points values (total and withdrawable)."""
        # Clear total points cache
        total_cache_key = TOTAL_POINTS_CACHE_KEY_TEMPLATE.format(user_id=self.pk)
        cache.delete(total_cache_key)
        if "total_points" in self.__dict__:
            del self.__dict__["total_points"]

        # Clear withdrawable points cache
        withdrawable_cache_key = WITHDRAWABLE_POINTS_CACHE_KEY_TEMPLATE.format(
            user_id=self.pk
        )
        cache.delete(withdrawable_cache_key)
        if "withdrawable_points" in self.__dict__:
            del self.__dict__["withdrawable_points"]

    def get_points_by_tag(self):
        """
        Get points grouped by tag.

        Returns a list of dicts with tag name, total points, and withdrawable status.

        """
        tag_points = {}
        # Use prefetch_related to avoid N+1 queries
        for source in self.point_sources.filter(
            remaining_points__gt=0
        ).prefetch_related("tags"):
            for tag in source.tags.all():
                if tag.name not in tag_points:
                    tag_points[tag.name] = {
                        "points": 0,
                        "withdrawable": tag.withdrawable,
                    }
                tag_points[tag.name]["points"] += source.remaining_points

        return [
            {"tag": tag, "points": data["points"], "withdrawable": data["withdrawable"]}
            for tag, data in tag_points.items()
        ]

    @property
    def withdrawable_points(self):
        """
        Get total withdrawable points across all sources (cached).

        Cache is automatically cleared when PointSource or PointTransaction is modified.
        """
        cache_key = WITHDRAWABLE_POINTS_CACHE_KEY_TEMPLATE.format(user_id=self.pk)
        cached_total = cache.get(cache_key)
        if cached_total is not None:
            return cached_total

        total = 0
        for source in self.point_sources.filter(remaining_points__gt=0):
            if source.is_withdrawable:
                total += source.remaining_points

        cache.set(cache_key, total, WITHDRAWABLE_POINTS_CACHE_TIMEOUT)
        return total


class UserProfile(models.Model):
    """User profile model with bio and social links."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
        primary_key=True,  # 将 user 字段设为主键，可以提升查询性能
        verbose_name="用户",
    )
    bio = models.TextField(max_length=500, blank=True, verbose_name="个人简介")
    birth_date = models.DateField(null=True, blank=True, verbose_name="生日")
    github_url = models.URLField(max_length=200, blank=True, verbose_name="GitHub 地址")
    homepage_url = models.URLField(max_length=200, blank=True, verbose_name="个人主页")
    blog_url = models.URLField(max_length=200, blank=True, verbose_name="博客地址")
    twitter_url = models.URLField(
        max_length=200,
        blank=True,
        verbose_name="Twitter 地址",
    )
    linkedin_url = models.URLField(
        max_length=200,
        blank=True,
        verbose_name="LinkedIn 地址",
    )
    company = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="公司",
        db_index=True,
    )
    location = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="位置",
        db_index=True,
    )

    class Meta:
        """Meta configuration for UserProfile."""

        verbose_name = "用户资料"
        verbose_name_plural = verbose_name

    def __str__(self):
        """Return username as string representation."""
        return self.user.username


class WorkExperience(models.Model):
    """Work experience model for user profiles."""

    profile = models.ForeignKey(
        UserProfile,
        on_delete=models.CASCADE,
        related_name="work_experiences",  # 允许 user.profile.work_experiences.all()
        verbose_name="所属用户",
    )
    company_name = models.CharField(max_length=100, verbose_name="公司名称")
    title = models.CharField(max_length=100, verbose_name="职位")
    start_date = models.DateField(verbose_name="开始日期")
    end_date = models.DateField(
        null=True,
        blank=True,
        verbose_name="结束日期",
    )  # null=True 表示仍在职
    description = models.TextField(blank=True, verbose_name="工作描述")

    class Meta:
        """Meta configuration for WorkExperience."""

        ordering = ["-start_date"]  # 默认按开始日期降序排列
        verbose_name = "工作经历"
        verbose_name_plural = verbose_name


class Education(models.Model):
    """Education model for user profiles."""

    profile = models.ForeignKey(
        UserProfile,
        on_delete=models.CASCADE,
        related_name="educations",  # 允许 user.profile.educations.all()
        verbose_name="所属用户",
    )
    institution_name = models.CharField(max_length=100, verbose_name="学校/机构名称")
    degree = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="学位",
    )  # 例如：本科, 硕士
    field_of_study = models.CharField(max_length=100, verbose_name="专业领域")
    start_date = models.DateField(verbose_name="开始日期")
    end_date = models.DateField(null=True, blank=True, verbose_name="结束日期")

    class Meta:
        """Meta configuration for Education."""

        ordering = ["-start_date"]
        verbose_name = "学习经历"
        verbose_name_plural = verbose_name


class ShippingAddress(models.Model):
    """Shipping address model for users."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="shipping_addresses",
        verbose_name="用户",
    )
    receiver_name = models.CharField(max_length=100, verbose_name="收件人姓名")
    phone = models.CharField(max_length=20, verbose_name="联系电话")
    province = models.CharField(max_length=50, verbose_name="省份")
    city = models.CharField(max_length=50, verbose_name="城市")
    district = models.CharField(max_length=50, verbose_name="区/县")
    address = models.CharField(max_length=200, verbose_name="详细地址")
    is_default = models.BooleanField(default=False, verbose_name="默认地址")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        """Meta configuration for ShippingAddress."""

        ordering = ["-is_default", "-updated_at"]
        verbose_name = "收货地址"
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["user", "is_default"]),
        ]

    def __str__(self):
        """Return address string representation."""
        return f"{self.receiver_name} - {self.province}{self.city}{self.district}{self.address}"

    def save(self, *args, **kwargs):
        """Override save to ensure only one default address per user."""
        if self.is_default:
            # 将该用户的其他地址设为非默认
            ShippingAddress.objects.filter(user=self.user, is_default=True).exclude(
                pk=self.pk
            ).update(is_default=False)
        super().save(*args, **kwargs)


class Organization(models.Model):
    """Organization model for teams and groups."""

    name = models.CharField(max_length=200, verbose_name="组织名称")
    slug = models.SlugField(max_length=200, unique=True, verbose_name="URL别名")
    description = models.TextField(blank=True, verbose_name="组织描述")
    avatar = models.ImageField(
        upload_to="organizations/avatars/", blank=True, null=True, verbose_name="头像"
    )
    website = models.URLField(max_length=500, blank=True, verbose_name="网站")
    location = models.CharField(max_length=200, blank=True, verbose_name="位置")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    members = models.ManyToManyField(
        User,
        through="OrganizationMembership",
        related_name="organizations",
        verbose_name="成员",
    )

    class Meta:
        """Meta configuration for Organization."""

        ordering = ["name"]
        verbose_name = "组织"
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=["slug"]),
        ]

    def __str__(self):
        """Return organization string representation."""
        return self.name


class OrganizationMembership(models.Model):
    """Organization membership model linking users to organizations."""

    class Role(models.TextChoices):
        """Organization member roles."""

        OWNER = "owner", "所有者"
        ADMIN = "admin", "管理员"
        MEMBER = "member", "成员"

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="organization_memberships",
        verbose_name="用户",
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name="组织",
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.MEMBER,
        verbose_name="角色",
    )
    joined_at = models.DateTimeField(auto_now_add=True, verbose_name="加入时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        """Meta configuration for OrganizationMembership."""

        ordering = ["-joined_at"]
        verbose_name = "组织成员"
        verbose_name_plural = verbose_name
        unique_together = [["user", "organization"]]
        indexes = [
            models.Index(fields=["user", "role"]),
            models.Index(fields=["organization", "role"]),
        ]

    def __str__(self):
        """Return membership string representation."""
        return f"{self.user.username} - {self.organization.name} ({self.get_role_display()})"

    def is_admin_or_owner(self):
        """Check if the member has admin or owner privileges."""
        return self.role in [self.Role.OWNER, self.Role.ADMIN]


class AccountMergeRequest(models.Model):
    """User-initiated account merge request awaiting confirmation."""

    class Status(models.TextChoices):
        """Lifecycle status for merge requests."""

        PENDING = "PENDING", "待处理"
        ACCEPTED = "ACCEPTED", "已同意"
        REJECTED = "REJECTED", "已拒绝"
        EXPIRED = "EXPIRED", "已过期"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="merge_requests_sent",
        verbose_name="源账号",
    )
    target_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="merge_requests_received",
        verbose_name="目标账号",
    )
    target_email_input = models.EmailField(blank=True, verbose_name="目标邮箱输入")
    target_username_input = models.CharField(
        max_length=150, blank=True, verbose_name="目标用户名输入"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        verbose_name="状态",
    )
    approve_token = models.CharField(
        max_length=128, unique=True, db_index=True, verbose_name="确认令牌"
    )
    expires_at = models.DateTimeField(verbose_name="过期时间")
    processed_at = models.DateTimeField(null=True, blank=True, verbose_name="处理时间")
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="processed_merge_requests",
        verbose_name="处理人",
    )
    asset_snapshot = models.JSONField(default=dict, verbose_name="资产快照")
    message = models.ForeignKey(
        "site_messages.Message",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="account_merge_requests",
        verbose_name="关联消息",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        """Meta configuration for AccountMergeRequest."""

        verbose_name = "账号合并申请"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_user"],
                condition=Q(status="PENDING"),
                name="unique_pending_merge_per_source",
            ),
        ]

    def __str__(self):
        """Show source and target with status for quick audit."""
        return f"{self.source_user} → {self.target_user} ({self.status})"

    @property
    def is_expired(self):
        """Return whether request has passed expiry."""
        from django.utils import timezone

        return self.expires_at <= timezone.now()


class AccountMergeLog(models.Model):
    """Audit log for merge execution results."""

    request = models.ForeignKey(
        AccountMergeRequest,
        on_delete=models.CASCADE,
        related_name="logs",
        verbose_name="合并请求",
    )
    table_name = models.CharField(max_length=64, verbose_name="表名")
    migrated_count = models.PositiveIntegerField(default=0, verbose_name="迁移数量")
    skipped_count = models.PositiveIntegerField(default=0, verbose_name="跳过数量")
    conflict_count = models.PositiveIntegerField(default=0, verbose_name="冲突数量")
    notes = models.TextField(blank=True, verbose_name="备注")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        """Meta configuration for AccountMergeLog."""

        verbose_name = "账号合并日志"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]

    def __str__(self):
        """Return readable summary."""
        return f"{self.table_name}: +{self.migrated_count}/~{self.conflict_count}"
