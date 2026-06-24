"""Django admin configuration for shop application."""

from django.contrib import admin
from django.shortcuts import render
from django.urls import path
from django.utils.html import format_html

from .forms import ShopItemAdminForm
from .models import CouponCode, Redemption, ShopItem


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


@admin.register(CouponCode)
class CouponCodeAdmin(admin.ModelAdmin):
    """Admin for CouponCode model."""

    list_display = [
        "id",
        "code_type",
        "masked_code",
        "status_display",
        "redeemed_by",
        "redeemed_at",
        "created_at",
    ]
    list_filter = ["status", "code_type"]
    search_fields = ["code", "code_type"]
    readonly_fields = ["redeemed_by", "redeemed_at", "created_at"]

    def masked_code(self, obj):
        """部分遮掩兑换码."""
        code = obj.code
        if len(code) > 8:
            return f"{code[:4]}{'*' * (len(code) - 8)}{code[-4:]}"
        return code[:2] + "*" * max(0, len(code) - 2)

    masked_code.short_description = "兑换码"

    def status_display(self, obj):
        """彩色状态显示."""
        colors = {"available": "green", "used": "gray", "disabled": "red"}
        color = colors.get(obj.status, "black")
        return format_html(
            '<span style="color: {};">{}</span>', color, obj.get_status_display()
        )

    status_display.short_description = "状态"

    def get_urls(self):
        """Add bulk import URL."""
        custom_urls = [
            path(
                "bulk-import/",
                self.admin_site.admin_view(self.bulk_import_view),
                name="shop_couponcode_bulk_import",
            ),
        ]
        return custom_urls + super().get_urls()

    def bulk_import_view(self, request):
        """批量导入兑换码视图."""
        existing_types = (
            CouponCode.objects.values_list("code_type", flat=True)
            .distinct()
            .order_by("code_type")
        )

        context = {
            "existing_types": list(existing_types),
            "title": "批量导入兑换码",
            "opts": self.model._meta,
            "has_view_permission": self.has_view_permission(request),
        }

        if request.method == "POST":
            code_type = request.POST.get("code_type", "").strip()
            codes_text = request.POST.get("codes", "")

            if not code_type:
                context["error"] = "请填写兑换码类型"
                return render(
                    request, "admin/shop/couponcode/bulk_import.html", context
                )

            # 按换行切分，strip 每行，去除空行
            codes = [line.strip() for line in codes_text.splitlines() if line.strip()]

            if not codes:
                context["error"] = "请输入至少一个兑换码"
                return render(
                    request, "admin/shop/couponcode/bulk_import.html", context
                )

            # 去重（输入内部去重）
            unique_codes = list(dict.fromkeys(codes))

            # 批量创建，ignore_conflicts=True 跳过数据库中已存在的
            objs = [CouponCode(code_type=code_type, code=code) for code in unique_codes]
            created = CouponCode.objects.bulk_create(objs, ignore_conflicts=True)
            created_count = len(created)
            skipped_count = len(unique_codes) - created_count

            context["success"] = f"成功导入 {created_count} 个兑换码" + (
                f"，跳过 {skipped_count} 个重复" if skipped_count > 0 else ""
            )
            context["code_type"] = code_type

        return render(request, "admin/shop/couponcode/bulk_import.html", context)

    def changelist_view(self, request, extra_context=None):
        """Add bulk import button to changelist."""
        extra_context = extra_context or {}
        extra_context["show_bulk_import_button"] = True
        return super().changelist_view(request, extra_context=extra_context)

    change_list_template = "admin/shop/couponcode/change_list.html"


@admin.register(ShopItem)
class ShopItemAdmin(admin.ModelAdmin):
    """Admin for ShopItem model."""

    form = ShopItemAdminForm

    list_display = (
        "id",
        "name_zh",
        "cost",
        "stock_display",
        "is_active",
        "requires_shipping",
        "has_image",
        "redemption_count",
        "created_at",
        "updated_at",
    )
    list_filter = (
        "is_active",
        "requires_shipping",
        "created_at",
        "updated_at",
    )
    search_fields = ("name_zh", "name_en", "description_zh")
    readonly_fields = ("created_at", "updated_at", "redemption_count")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    inlines = [RedemptionInline]

    fieldsets = (
        (
            "基本信息(中文)",
            {
                "fields": ("name_zh", "brief_zh", "description_zh"),
            },
        ),
        (
            "基本信息(英文)",
            {
                "fields": ("name_en", "brief_en", "description_en"),
            },
        ),
        (
            "图片",
            {
                "fields": ("image_card", "image_detail"),
            },
        ),
        (
            "站内信模板",
            {
                "fields": (
                    "message_title_template_zh",
                    "message_title_template_en",
                    "message_content_template_zh",
                    "message_content_template_en",
                ),
            },
        ),
        (
            "兑换设置",
            {
                "fields": (
                    "cost",
                    "stock",
                    "is_active",
                    "requires_shipping",
                    "coupon_type",
                ),
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
        """Display stock with color, showing coupon availability if applicable."""
        if obj.coupon_type:
            available_count = CouponCode.objects.filter(
                code_type=obj.coupon_type, status=CouponCode.Status.AVAILABLE
            ).count()
            return format_html(
                '<span style="color: {};">{} (券库: {})</span>',
                "green" if available_count > 0 else "red",
                obj.stock if obj.stock is not None else "♾️",
                available_count,
            )
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
        return bool(obj.image_card)

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
        "has_shipping_address",
        "created_at",
    )
    list_filter = ("status", "created_at", "item")
    search_fields = (
        "user_profile__username",
        "user_profile__email",
        "item__name_zh",
        "shipping_address__receiver_name",
        "shipping_address__phone",
    )
    readonly_fields = ("created_at", "shipping_address_display")
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
