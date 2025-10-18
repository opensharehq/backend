"""Admin configuration for the points app."""

from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.utils.html import format_html

from .models import PointSource, PointTransaction, Tag

User = get_user_model()


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    """Admin for Tag model."""

    list_display = ("name", "slug", "is_default", "withdrawable", "description_short")
    list_filter = ("is_default", "withdrawable")
    search_fields = ("name", "slug", "description")
    ordering = ("name",)
    readonly_fields = ("slug",)
    prepopulated_fields = {}  # slug is auto-generated in model

    @admin.display(description="描述")
    def description_short(self, obj):
        """Display shortened description."""
        if len(obj.description) > 50:
            return f"{obj.description[:50]}..."
        return obj.description


class GrantPointsForm(forms.Form):
    """Form for granting points to a user."""

    user = forms.ModelChoiceField(
        queryset=User.objects.all(),
        label="用户",
        help_text="选择要发放积分的用户",
    )
    points = forms.IntegerField(
        min_value=1,
        label="积分数量",
        help_text="必须是正整数",
    )
    description = forms.CharField(
        max_length=255,
        label="描述",
        help_text="积分来源描述",
    )
    tags = forms.CharField(
        max_length=500,
        label="标签",
        help_text="用逗号分隔多个标签，例如：新手福利,注册奖励",
    )

    def clean_tags(self):
        """Parse comma-separated tags."""
        tags_str = self.cleaned_data["tags"]
        return [tag.strip() for tag in tags_str.split(",") if tag.strip()]


@admin.register(PointSource)
class PointSourceAdmin(admin.ModelAdmin):
    """Admin for PointSource model."""

    list_display = (
        "id",
        "user",
        "initial_points",
        "remaining_points",
        "usage_percentage",
        "display_tags",
        "created_at",
        "expires_at",
        "is_expired",
        "withdrawable_status",
    )
    list_filter = ("created_at", "expires_at", "tags")
    search_fields = ("user__username", "user__email", "notes")
    filter_horizontal = ("tags",)
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "基本信息",
            {
                "fields": (
                    "user",
                    "initial_points",
                    "remaining_points",
                ),
            },
        ),
        (
            "标签和备注",
            {
                "fields": ("tags", "notes"),
            },
        ),
        (
            "时间信息",
            {
                "fields": ("created_at", "expires_at"),
            },
        ),
    )

    @admin.display(description="使用率")
    def usage_percentage(self, obj):
        """Display usage percentage."""
        if obj.initial_points == 0:
            return "N/A"
        used = obj.initial_points - obj.remaining_points
        percentage = (used / obj.initial_points) * 100
        return f"{percentage:.1f}%"

    @admin.display(description="标签")
    def display_tags(self, obj):
        """Display tags as colored badges."""
        tags = obj.tags.all()
        if not tags:
            return "-"
        return ", ".join([tag.name for tag in tags])

    @admin.display(boolean=True, description="已过期")
    def is_expired(self, obj):
        """Check if points are expired."""
        if obj.expires_at is None:
            return False
        from django.utils import timezone

        return timezone.now() > obj.expires_at

    @admin.display(boolean=True, description="可提现")
    def withdrawable_status(self, obj):
        """Display if points are withdrawable based on tags."""
        return obj.is_withdrawable


@admin.register(PointTransaction)
class PointTransactionAdmin(admin.ModelAdmin):
    """Admin for PointTransaction model."""

    list_display = (
        "id",
        "user",
        "transaction_type",
        "colored_points",
        "description",
        "created_at",
        "source_count",
    )
    list_filter = ("transaction_type", "created_at")
    search_fields = ("user__username", "user__email", "description")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    filter_horizontal = ("consumed_sources",)

    fieldsets = (
        (
            "交易信息",
            {
                "fields": (
                    "user",
                    "transaction_type",
                    "points",
                    "description",
                ),
            },
        ),
        (
            "关联信息",
            {
                "fields": ("consumed_sources",),
            },
        ),
        (
            "时间信息",
            {
                "fields": ("created_at",),
            },
        ),
    )

    @admin.display(description="积分")
    def colored_points(self, obj):
        """Display points with color based on transaction type."""
        if obj.transaction_type == PointTransaction.TransactionType.EARN:
            color = "green"
            prefix = "+"
        else:
            color = "red"
            prefix = "-"
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}{}</span>',
            color,
            prefix,
            abs(obj.points),
        )

    @admin.display(description="消费源数量")
    def source_count(self, obj):
        """Display count of consumed sources."""
        count = obj.consumed_sources.count()
        return count if count > 0 else "-"
