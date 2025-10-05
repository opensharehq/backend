"""Admin configuration for the points app."""

from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model

from .models import PointSource, PointTransaction, Tag

User = get_user_model()


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    """Admin for Tag model."""

    list_display = ("name", "description", "is_default")
    list_filter = ("is_default",)
    search_fields = ("name", "description")
    ordering = ("name",)


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
        "user_profile",
        "initial_points",
        "remaining_points",
        "created_at",
        "expires_at",
    )
    list_filter = ("created_at", "expires_at")
    search_fields = ("user_profile__username", "user_profile__email", "notes")
    filter_horizontal = ("tags",)
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)

    fieldsets = (
        (
            "基本信息",
            {
                "fields": (
                    "user_profile",
                    "initial_points",
                    "remaining_points",
                )
            },
        ),
        (
            "标签和备注",
            {"fields": ("tags", "notes")},
        ),
        (
            "时间信息",
            {"fields": ("created_at", "expires_at")},
        ),
    )


@admin.register(PointTransaction)
class PointTransactionAdmin(admin.ModelAdmin):
    """Admin for PointTransaction model."""

    list_display = (
        "id",
        "user_profile",
        "transaction_type",
        "points",
        "description",
        "created_at",
    )
    list_filter = ("transaction_type", "created_at")
    search_fields = ("user_profile__username", "user_profile__email", "description")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)

    fieldsets = (
        (
            "交易信息",
            {
                "fields": (
                    "user_profile",
                    "transaction_type",
                    "points",
                    "description",
                )
            },
        ),
        (
            "关联信息",
            {"fields": ("consumed_sources",)},
        ),
        (
            "时间信息",
            {"fields": ("created_at",)},
        ),
    )


# Add a custom admin action for granting points
class GrantPointsAdminSite(admin.AdminSite):
    """Custom admin site with grant points functionality."""

    site_header = "积分管理后台"
    site_title = "积分管理"
    index_title = "欢迎使用积分管理系统"
