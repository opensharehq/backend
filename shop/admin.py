"""Django admin configuration for shop application."""

from django.contrib import admin
from django.utils.html import format_html

from .models import Redemption, ShopItem


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


@admin.register(ShopItem)
class ShopItemAdmin(admin.ModelAdmin):
    """Admin for ShopItem model."""

    list_display = (
        "id",
        "name",
        "cost",
        "stock_display",
        "is_active",
        "requires_shipping",
        "has_image",
        "display_tags",
        "redemption_count",
        "created_at",
        "updated_at",
    )
    list_filter = (
        "is_active",
        "requires_shipping",
        "created_at",
        "updated_at",
        "allowed_tags",
    )
    search_fields = ("name", "description")
    filter_horizontal = ("allowed_tags",)
    readonly_fields = ("created_at", "updated_at", "redemption_count")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    inlines = [RedemptionInline]

    fieldsets = (
        (
            "基本信息",
            {
                "fields": ("name", "description", "cost", "image"),
            },
        ),
        (
            "库存和状态",
            {
                "fields": ("stock", "is_active", "requires_shipping"),
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
            "统计信息",
            {
                "fields": ("redemption_count",),
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

    @admin.display(boolean=True, description="有图片")
    def has_image(self, obj):
        """Check if item has an image."""
        return bool(obj.image)

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
        "has_shipping_address",
        "created_at",
    )
    list_filter = ("status", "created_at", "item")
    search_fields = (
        "user_profile__username",
        "user_profile__email",
        "item__name",
        "shipping_address__receiver_name",
        "shipping_address__phone",
    )
    readonly_fields = ("created_at", "transaction", "shipping_address_display")
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
            "收货信息",
            {
                "fields": ("shipping_address", "shipping_address_display"),
                "description": "如果商品需要线下发货，这里会显示用户选择的收货地址",
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

    @admin.display(boolean=True, description="有收货地址")
    def has_shipping_address(self, obj):
        """Check if redemption has a shipping address."""
        return obj.shipping_address is not None

    @admin.display(description="收货地址详情")
    def shipping_address_display(self, obj):
        """Display shipping address details."""
        if not obj.shipping_address:
            return format_html('<span style="color: gray;">无需发货</span>')

        addr = obj.shipping_address
        return format_html(
            '<div style="line-height: 1.6;">'
            "<strong>{}</strong> {}<br>"
            "{} {} {}<br>"
            "{}"
            "</div>",
            addr.receiver_name,
            addr.phone,
            addr.province,
            addr.city,
            addr.district,
            addr.address,
        )

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
