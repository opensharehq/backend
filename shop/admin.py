"""Django admin configuration for shop application."""

from django.contrib import admin
from django.utils.html import format_html

from .models import Redemption, ShopItem


@admin.register(ShopItem)
class ShopItemAdmin(admin.ModelAdmin):
    """Admin for ShopItem model."""

    list_display = (
        "id",
        "name",
        "cost",
        "stock_display",
        "is_active",
        "display_tags",
        "redemption_count",
        "created_at",
        "updated_at",
    )
    list_filter = ("is_active", "created_at", "updated_at", "allowed_tags")
    search_fields = ("name", "description")
    filter_horizontal = ("allowed_tags",)
    readonly_fields = ("created_at", "updated_at", "redemption_count")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "基本信息",
            {
                "fields": ("name", "description", "cost"),
            },
        ),
        (
            "库存和状态",
            {
                "fields": ("stock", "is_active"),
            },
        ),
        (
            "标签限制",
            {
                "fields": ("allowed_tags",),
                "description": "如果为空，则任何积分都可兑换。如果不为空，则只有带这些标签的积分才能用于兑换。",
            },
        ),
        (
            "时间信息",
            {
                "fields": ("created_at", "updated_at"),
            },
        ),
    )

    @admin.display(description="库存")
    def stock_display(self, obj):
        """Display stock with color."""
        if obj.stock is None:
            return format_html('<span style="color: green;">♾️ 无限</span>')
        if obj.stock == 0:
            return format_html(
                '<span style="color: red; font-weight: bold;">0 (售罄)</span>'
            )
        if obj.stock < 10:
            return format_html('<span style="color: orange;">{}</span>', obj.stock)
        return obj.stock

    @admin.display(description="允许标签")
    def display_tags(self, obj):
        """Display allowed tags."""
        tags = obj.allowed_tags.all()
        if not tags:
            return format_html('<span style="color: gray;">不限</span>')
        return ", ".join([tag.name for tag in tags])

    @admin.display(description="兑换次数")
    def redemption_count(self, obj):
        """Display redemption count."""
        count = obj.redemptions.count()
        return count if count > 0 else 0


class RedemptionInline(admin.TabularInline):
    """Inline admin for redemptions on ShopItem."""

    model = Redemption
    extra = 0
    readonly_fields = (
        "user_profile",
        "points_cost_at_redemption",
        "status",
        "created_at",
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        """Disable adding redemptions inline."""
        return False


@admin.register(Redemption)
class RedemptionAdmin(admin.ModelAdmin):
    """Admin for Redemption model."""

    list_display = (
        "id",
        "user_profile",
        "item",
        "points_cost_at_redemption",
        "status_display",
        "has_transaction",
        "created_at",
    )
    list_filter = ("status", "created_at", "item")
    search_fields = (
        "user_profile__username",
        "user_profile__email",
        "item__name",
    )
    readonly_fields = ("created_at", "transaction")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "兑换信息",
            {
                "fields": (
                    "user_profile",
                    "item",
                    "points_cost_at_redemption",
                    "status",
                ),
            },
        ),
        (
            "关联信息",
            {
                "fields": ("transaction",),
            },
        ),
        (
            "时间信息",
            {
                "fields": ("created_at",),
            },
        ),
    )

    actions = ["mark_as_completed", "mark_as_cancelled"]

    @admin.display(description="状态")
    def status_display(self, obj):
        """Display status with color."""
        colors = {
            Redemption.StatusChoices.PENDING: "orange",
            Redemption.StatusChoices.COMPLETED: "green",
            Redemption.StatusChoices.CANCELLED: "red",
        }
        color = colors.get(obj.status, "black")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display(),
        )

    @admin.display(boolean=True, description="有交易记录")
    def has_transaction(self, obj):
        """Check if redemption has a transaction."""
        return obj.transaction is not None

    @admin.action(description="标记为已完成")
    def mark_as_completed(self, request, queryset):
        """Mark selected redemptions as completed."""
        updated = queryset.update(status=Redemption.StatusChoices.COMPLETED)
        self.message_user(request, f"已将 {updated} 条兑换记录标记为已完成")

    @admin.action(description="标记为已取消")
    def mark_as_cancelled(self, request, queryset):
        """Mark selected redemptions as cancelled."""
        updated = queryset.update(status=Redemption.StatusChoices.CANCELLED)
        self.message_user(request, f"已将 {updated} 条兑换记录标记为已取消")
