"""User models for accounts app."""

from django.contrib.auth.models import AbstractUser, UserManager
from django.core.cache import cache
from django.db import models
from django.db.models import Sum

TOTAL_POINTS_CACHE_KEY_TEMPLATE = "accounts:user_total_points:{user_id}"
TOTAL_POINTS_CACHE_TIMEOUT = 300


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
        """Clear cached points value."""
        cache_key = TOTAL_POINTS_CACHE_KEY_TEMPLATE.format(user_id=self.pk)
        cache.delete(cache_key)
        if "total_points" in self.__dict__:
            del self.__dict__["total_points"]

    def get_points_by_tag(self):
        """
        Get points grouped by tag.

        Returns a list of dicts with tag name and total points.

        """
        tag_points = {}
        for source in self.point_sources.filter(remaining_points__gt=0):
            for tag in source.tags.all():
                if tag.name not in tag_points:
                    tag_points[tag.name] = 0
                tag_points[tag.name] += source.remaining_points

        return [{"tag": tag, "points": points} for tag, points in tag_points.items()]


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
