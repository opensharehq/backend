"""Admin configuration for points application."""

from django.contrib import admin
from django.utils.html import format_html

from . import services
from .models import (
    PointSource,
    PointTransaction,
    PointWallet,
    Tag,
    TransactionType,
    WithdrawalRequest,
    WithdrawalStatus,
)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    """Admin for Tag model."""

    list_display = ("name", "slug", "description", "created_at")
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("name",)


class PointSourceInline(admin.TabularInline):
    """Inline for PointSource model."""

    model = PointSource
    extra = 0
    readonly_fields = (
        "point_type",
        "tag",
        "original_amount",
        "remaining_amount",
        "reason",
        "reference_id",
        "expires_at",
        "created_by",
        "created_at",
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        """Disable add permission."""
        return False


class PointTransactionInline(admin.TabularInline):
    """Inline for PointTransaction model."""

    model = PointTransaction
    extra = 0
    readonly_fields = (
        "transaction_type",
        "point_type",
        "amount",
        "balance_after",
        "description",
        "reference_id",
        "tag",
        "created_by",
        "created_at",
    )
    can_delete = False
    ordering = ("-created_at",)

    def has_add_permission(self, request, obj=None):
        """Disable add permission."""
        return False


class WithdrawalInline(admin.TabularInline):
    """Inline for WithdrawalRequest model."""

    model = WithdrawalRequest
    extra = 0
    readonly_fields = (
        "amount",
        "status",
        "real_name",
        "phone",
        "bank_name",
        "bank_account",
        "processed_by",
        "processed_at",
        "created_at",
    )
    can_delete = False

    def has_add_permission(self, request, obj=None):
        """Disable add permission."""
        return False


@admin.register(PointWallet)
class PointWalletAdmin(admin.ModelAdmin):
    """Admin for PointWallet model."""

    list_display = (
        "id",
        "owner_display",
        "cash_balance",
        "gift_balance",
        "total_balance",
        "created_at",
    )
    list_filter = ("content_type", "created_at")
    search_fields = ("id",)
    readonly_fields = (
        "content_type",
        "object_id",
        "owner_display",
        "cash_balance",
        "gift_balance",
        "total_balance",
        "created_at",
        "updated_at",
    )
    inlines = [PointSourceInline, PointTransactionInline, WithdrawalInline]

    fieldsets = (
        (
            "钱包信息",
            {
                "fields": (
                    "owner_display",
                    "content_type",
                    "object_id",
                )
            },
        ),
        (
            "余额",
            {
                "fields": (
                    "cash_balance",
                    "gift_balance",
                    "total_balance",
                )
            },
        ),
        (
            "时间信息",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def owner_display(self, obj):
        """Display owner name."""
        owner = obj.owner
        if owner:
            return str(owner)
        return "-"

    owner_display.short_description = "所有者"

    def cash_balance(self, obj):
        """Display cash balance."""
        return obj.get_cash_balance()

    cash_balance.short_description = "现金积分"

    def gift_balance(self, obj):
        """Display gift balance."""
        return obj.get_gift_balance()

    gift_balance.short_description = "礼物积分"

    def total_balance(self, obj):
        """Display total balance."""
        return obj.get_total_balance()

    total_balance.short_description = "总积分"

    def has_add_permission(self, request):
        """Disable add permission - wallets are created automatically."""
        return False


@admin.register(PointSource)
class PointSourceAdmin(admin.ModelAdmin):
    """Admin for PointSource model."""

    list_display = (
        "id",
        "wallet_owner",
        "point_type",
        "tag",
        "original_amount",
        "remaining_amount",
        "reason",
        "created_at",
    )
    list_filter = ("point_type", "tag", "created_at")
    search_fields = ("reason", "reference_id", "wallet__id")
    readonly_fields = (
        "wallet",
        "point_type",
        "tag",
        "original_amount",
        "remaining_amount",
        "reason",
        "reference_id",
        "expires_at",
        "created_by",
        "created_at",
    )
    ordering = ("-created_at",)

    def wallet_owner(self, obj):
        """Display wallet owner."""
        owner = obj.wallet.owner
        if owner:
            return str(owner)
        return "-"

    wallet_owner.short_description = "所有者"

    def has_add_permission(self, request):
        """Disable add permission - use services to grant points."""
        return False

    def has_change_permission(self, request, obj=None):
        """Disable change permission."""
        return False


@admin.register(PointTransaction)
class PointTransactionAdmin(admin.ModelAdmin):
    """Admin for PointTransaction model."""

    list_display = (
        "id",
        "wallet_owner",
        "transaction_type_display",
        "point_type",
        "amount_display",
        "balance_after",
        "description",
        "created_at",
    )
    list_filter = ("transaction_type", "point_type", "tag", "created_at")
    search_fields = ("description", "reference_id", "wallet__id")
    readonly_fields = (
        "wallet",
        "transaction_type",
        "point_type",
        "amount",
        "balance_after",
        "description",
        "reference_id",
        "source",
        "tag",
        "created_by",
        "created_at",
    )
    ordering = ("-created_at",)

    def wallet_owner(self, obj):
        """Display wallet owner."""
        owner = obj.wallet.owner
        if owner:
            return str(owner)
        return "-"

    wallet_owner.short_description = "所有者"

    def transaction_type_display(self, obj):
        """Display transaction type with color."""
        colors = {
            TransactionType.EARN: "green",
            TransactionType.SPEND: "orange",
            TransactionType.WITHDRAW: "blue",
            TransactionType.EXPIRE: "gray",
        }
        color = colors.get(obj.transaction_type, "black")
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            obj.get_transaction_type_display(),
        )

    transaction_type_display.short_description = "交易类型"

    def amount_display(self, obj):
        """Display amount with color."""
        if obj.amount > 0:
            return format_html('<span style="color: green;">+{}</span>', obj.amount)
        return format_html('<span style="color: red;">{}</span>', obj.amount)

    amount_display.short_description = "交易金额"

    def has_add_permission(self, request):
        """Disable add permission - transactions are created via services."""
        return False

    def has_change_permission(self, request, obj=None):
        """Disable change permission - transactions are immutable."""
        return False

    def has_delete_permission(self, request, obj=None):
        """Disable delete permission - transactions are immutable."""
        return False


@admin.register(WithdrawalRequest)
class WithdrawalRequestAdmin(admin.ModelAdmin):
    """Admin for WithdrawalRequest model."""

    list_display = (
        "id",
        "wallet_owner",
        "amount",
        "status_display",
        "real_name",
        "phone",
        "bank_name",
        "bank_account",
        "processed_by",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = (
        "real_name",
        "phone",
        "bank_name",
        "bank_account",
        "wallet__id",
    )
    readonly_fields = (
        "wallet",
        "amount",
        "real_name",
        "phone",
        "bank_name",
        "bank_account",
        "transaction",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)
    actions = ["approve_selected", "reject_selected", "complete_selected"]

    fieldsets = (
        (
            "申请信息",
            {
                "fields": (
                    "wallet",
                    "amount",
                    "status",
                )
            },
        ),
        (
            "提现人信息",
            {
                "fields": (
                    "real_name",
                    "phone",
                )
            },
        ),
        (
            "银行账户",
            {
                "fields": (
                    "bank_name",
                    "bank_account",
                )
            },
        ),
        (
            "审核信息",
            {
                "fields": (
                    "admin_note",
                    "processed_by",
                    "processed_at",
                    "transaction",
                )
            },
        ),
        (
            "时间信息",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def wallet_owner(self, obj):
        """Display wallet owner."""
        owner = obj.wallet.owner
        if owner:
            return str(owner)
        return "-"

    wallet_owner.short_description = "所有者"

    def status_display(self, obj):
        """Display status with color."""
        colors = {
            WithdrawalStatus.PENDING: "orange",
            WithdrawalStatus.APPROVED: "blue",
            WithdrawalStatus.REJECTED: "red",
            WithdrawalStatus.COMPLETED: "green",
            WithdrawalStatus.CANCELLED: "gray",
        }
        color = colors.get(obj.status, "black")
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            obj.get_status_display(),
        )

    status_display.short_description = "状态"

    def has_add_permission(self, request):
        """Disable add permission - use user interface to create withdrawals."""
        return False

    @admin.action(description="批准选中的提现申请")
    def approve_selected(self, request, queryset):
        """Approve selected withdrawal requests."""
        success_count = 0
        for obj in queryset.filter(status=WithdrawalStatus.PENDING):
            try:
                services.approve_withdrawal(obj.id, request.user)
                success_count += 1
            except (services.WithdrawalError, services.InsufficientPointsError) as e:
                self.message_user(
                    request,
                    f"提现申请 #{obj.id} 批准失败: {e}",
                    level="error",
                )
        if success_count:
            self.message_user(request, f"成功批准 {success_count} 个提现申请")

    @admin.action(description="拒绝选中的提现申请")
    def reject_selected(self, request, queryset):
        """Reject selected withdrawal requests."""
        success_count = 0
        for obj in queryset.filter(status=WithdrawalStatus.PENDING):
            try:
                services.reject_withdrawal(obj.id, request.user, "批量拒绝")
                success_count += 1
            except services.WithdrawalError as e:
                self.message_user(
                    request,
                    f"提现申请 #{obj.id} 拒绝失败: {e}",
                    level="error",
                )
        if success_count:
            self.message_user(request, f"成功拒绝 {success_count} 个提现申请")

    @admin.action(description="完成选中的提现申请")
    def complete_selected(self, request, queryset):
        """Complete selected withdrawal requests."""
        success_count = 0
        for obj in queryset.filter(status=WithdrawalStatus.APPROVED):
            try:
                services.complete_withdrawal(obj.id, request.user)
                success_count += 1
            except services.WithdrawalError as e:
                self.message_user(
                    request,
                    f"提现申请 #{obj.id} 完成失败: {e}",
                    level="error",
                )
        if success_count:
            self.message_user(request, f"成功完成 {success_count} 个提现申请")
