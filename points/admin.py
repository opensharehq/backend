"""Admin configuration for points application."""

from django.contrib import admin, messages
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import path
from django.utils.html import format_html

from . import services
from .forms import GrantPointsForm
from .models import (
    ContributionCache,
    PendingPointGrant,
    PointAllocation,
    PointSource,
    PointTransaction,
    PointType,
    PointWallet,
    Tag,
    TransactionType,
    WithdrawalRequest,
    WithdrawalStatus,
)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    """Admin for Tag model."""

    list_display = (
        "name",
        "slug",
        "tag_type",
        "is_official",
        "entity_identifier",
        "created_at",
    )
    list_filter = ("tag_type", "is_official", "created_at")
    search_fields = ("name", "slug", "description", "entity_identifier")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("name",)

    fieldsets = (
        (
            "基本信息",
            {"fields": ("name", "slug", "description")},
        ),
        (
            "分类信息",
            {
                "fields": (
                    "tag_type",
                    "entity_identifier",
                    "is_official",
                )
            },
        ),
        (
            "所有权",
            {
                "fields": ("owner_type", "owner_id"),
                "classes": ("collapse",),
            },
        ),
    )


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
        "id_card",
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
        "id_card",
        "bank_name",
        "bank_account",
        "processed_by",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = (
        "real_name",
        "phone",
        "id_card",
        "bank_name",
        "bank_account",
        "wallet__id",
    )
    readonly_fields = (
        "wallet",
        "amount",
        "real_name",
        "phone",
        "id_card",
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
                    "id_card",
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


def grant_points_to_users_view(request):
    """给选中的用户发放积分."""
    if not request.user.is_staff:
        return HttpResponseForbidden()

    # Import here to avoid circular dependency
    from accounts.models import User

    # 获取选中的用户 IDs
    user_ids_str = request.GET.get("ids", "")
    if not user_ids_str:
        messages.error(request, "未选择任何用户")
        return redirect("admin:accounts_user_changelist")

    user_ids = [int(id_str) for id_str in user_ids_str.split(",") if id_str]
    users = User.objects.filter(id__in=user_ids)

    if not users.exists():
        messages.error(request, "未找到选中的用户")
        return redirect("admin:accounts_user_changelist")

    if request.method == "POST":
        form = GrantPointsForm(request.POST)
        if form.is_valid():
            success_count = 0
            error_count = 0

            point_type = form.cleaned_data["point_type"]
            amount = form.cleaned_data["amount"]
            reason = form.cleaned_data["reason"]
            tag = form.cleaned_data.get("tag")
            expires_at = form.cleaned_data.get("expires_at")
            reference_id = form.cleaned_data.get("reference_id", "")

            for user in users:
                try:
                    services.grant_points(
                        owner=user,
                        amount=amount,
                        point_type=PointType(point_type),
                        reason=reason,
                        tag_slug=tag.slug if tag else None,
                        expires_at=expires_at,
                        reference_id=reference_id,
                        created_by=request.user,
                    )
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    messages.error(request, f"给用户 {user.username} 发放失败：{e}")

            if success_count:
                messages.success(request, f"成功给 {success_count} 个用户发放积分")

            return redirect("admin:accounts_user_changelist")
    else:
        form = GrantPointsForm()

    context = {
        "form": form,
        "users": users,
        "title": "给用户发放积分",
        "opts": User._meta,
        "has_view_permission": True,
        "site_header": admin.site.site_header,
        "site_title": admin.site.site_title,
    }
    return render(request, "admin/points/grant_points.html", context)


def grant_points_to_orgs_view(request):
    """给选中的组织发放积分."""
    if not request.user.is_staff:
        return HttpResponseForbidden()

    # Import here to avoid circular dependency
    from accounts.models import Organization

    # 获取选中的组织 IDs
    org_ids_str = request.GET.get("ids", "")
    if not org_ids_str:
        messages.error(request, "未选择任何组织")
        return redirect("admin:accounts_organization_changelist")

    org_ids = [int(id_str) for id_str in org_ids_str.split(",") if id_str]
    orgs = Organization.objects.filter(id__in=org_ids)

    if not orgs.exists():
        messages.error(request, "未找到选中的组织")
        return redirect("admin:accounts_organization_changelist")

    if request.method == "POST":
        form = GrantPointsForm(request.POST)
        if form.is_valid():
            success_count = 0
            error_count = 0

            point_type = form.cleaned_data["point_type"]
            amount = form.cleaned_data["amount"]
            reason = form.cleaned_data["reason"]
            tag = form.cleaned_data.get("tag")
            expires_at = form.cleaned_data.get("expires_at")
            reference_id = form.cleaned_data.get("reference_id", "")

            for org in orgs:
                try:
                    services.grant_points(
                        owner=org,
                        amount=amount,
                        point_type=PointType(point_type),
                        reason=reason,
                        tag_slug=tag.slug if tag else None,
                        expires_at=expires_at,
                        reference_id=reference_id,
                        created_by=request.user,
                    )
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    messages.error(request, f"给组织 {org.name} 发放失败：{e}")

            if success_count:
                messages.success(request, f"成功给 {success_count} 个组织发放积分")

            return redirect("admin:accounts_organization_changelist")
    else:
        form = GrantPointsForm()

    context = {
        "form": form,
        "orgs": orgs,
        "title": "给组织发放积分",
        "opts": Organization._meta,
        "has_view_permission": True,
        "site_header": admin.site.site_header,
        "site_title": admin.site.site_title,
    }
    return render(request, "admin/points/grant_points.html", context)


# 扩展 admin site 的 get_urls 方法以添加自定义视图
admin_site = admin.site
original_get_urls = admin_site.get_urls


def get_urls():
    """扩展 admin URLs 以包含自定义视图."""
    urls = original_get_urls()
    custom_urls = [
        path(
            "points/grant-to-users/",
            admin_site.admin_view(grant_points_to_users_view),
            name="grant_points_to_users",
        ),
        path(
            "points/grant-to-orgs/",
            admin_site.admin_view(grant_points_to_orgs_view),
            name="grant_points_to_orgs",
        ),
    ]
    return custom_urls + urls


admin_site.get_urls = get_urls


@admin.register(PointAllocation)
class PointAllocationAdmin(admin.ModelAdmin):
    """Admin for PointAllocation model."""

    list_display = (
        "id",
        "initiator_display",
        "total_amount",
        "status_display",
        "total_recipients",
        "executed_at",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("id",)
    readonly_fields = (
        "initiator_display",
        "source_pool",
        "total_amount",
        "project_scope",
        "user_scope",
        "start_month",
        "end_month",
        "adjustment_ratio",
        "individual_adjustments",
        "contribution_data",
        "status",
        "total_recipients",
        "registered_recipients",
        "unregistered_recipients",
        "executed_at",
        "created_at",
    )
    ordering = ("-created_at",)

    fieldsets = (
        (
            "基本信息",
            {
                "fields": (
                    "initiator_display",
                    "source_pool",
                    "total_amount",
                    "status",
                )
            },
        ),
        (
            "筛选条件",
            {
                "fields": (
                    "project_scope",
                    "user_scope",
                    "start_month",
                    "end_month",
                )
            },
        ),
        (
            "调整参数",
            {
                "fields": (
                    "adjustment_ratio",
                    "individual_adjustments",
                )
            },
        ),
        (
            "执行结果",
            {
                "fields": (
                    "total_recipients",
                    "registered_recipients",
                    "unregistered_recipients",
                    "contribution_data",
                    "executed_at",
                )
            },
        ),
        (
            "时间信息",
            {"fields": ("created_at",)},
        ),
    )

    def initiator_display(self, obj):
        """Display initiator name."""
        return str(obj.initiator)

    initiator_display.short_description = "发起者"

    def status_display(self, obj):
        """Display status with color."""
        colors = {
            "draft": "gray",
            "previewing": "blue",
            "executing": "orange",
            "completed": "green",
            "failed": "red",
        }
        color = colors.get(obj.status, "black")
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            obj.get_status_display(),
        )

    status_display.short_description = "状态"

    def has_add_permission(self, request):
        """Disable add permission - use allocation config page."""
        return False

    def has_change_permission(self, request, obj=None):
        """Disable change permission - allocations are immutable."""
        return False


@admin.register(PendingPointGrant)
class PendingPointGrantAdmin(admin.ModelAdmin):
    """Admin for PendingPointGrant model."""

    list_display = (
        "github_login",
        "email",
        "amount",
        "point_type",
        "status_display",
        "claimed_by",
        "created_at",
    )
    list_filter = ("is_claimed", "point_type", "created_at")
    search_fields = ("github_id", "github_login", "email")
    readonly_fields = (
        "github_id",
        "github_login",
        "email",
        "amount",
        "point_type",
        "reason",
        "tag",
        "reference_id",
        "granter_display",
        "is_claimed",
        "claimed_by",
        "claimed_at",
        "allocation",
        "created_at",
        "expires_at",
    )
    ordering = ("-created_at",)

    fieldsets = (
        (
            "用户信息",
            {
                "fields": (
                    "github_id",
                    "github_login",
                    "email",
                )
            },
        ),
        (
            "积分信息",
            {
                "fields": (
                    "amount",
                    "point_type",
                    "reason",
                    "tag",
                    "reference_id",
                )
            },
        ),
        (
            "发放者",
            {"fields": ("granter_display",)},
        ),
        (
            "领取状态",
            {
                "fields": (
                    "is_claimed",
                    "claimed_by",
                    "claimed_at",
                    "allocation",
                )
            },
        ),
        (
            "时间信息",
            {
                "fields": (
                    "created_at",
                    "expires_at",
                )
            },
        ),
    )

    def granter_display(self, obj):
        """Display granter name."""
        return str(obj.granter)

    granter_display.short_description = "发放者"

    def status_display(self, obj):
        """Display status with color."""
        if obj.is_claimed:
            return format_html('<span style="color: green;">已领取</span>')
        return format_html('<span style="color: orange;">待领取</span>')

    status_display.short_description = "状态"

    def has_add_permission(self, request):
        """Disable add permission - created via allocation."""
        return False

    def has_change_permission(self, request, obj=None):
        """Disable change permission - grants are immutable."""
        return False


@admin.register(ContributionCache)
class ContributionCacheAdmin(admin.ModelAdmin):
    """Admin for ContributionCache model."""

    list_display = (
        "project_identifier",
        "github_login",
        "contribution_score",
        "start_month",
        "end_month",
        "updated_at",
    )
    list_filter = ("project_identifier", "updated_at")
    search_fields = ("project_identifier", "github_login", "github_id", "email")
    readonly_fields = (
        "project_identifier",
        "github_id",
        "github_login",
        "email",
        "start_month",
        "end_month",
        "contribution_score",
        "raw_data",
        "created_at",
        "updated_at",
    )
    ordering = ("-updated_at",)

    fieldsets = (
        (
            "项目信息",
            {"fields": ("project_identifier",)},
        ),
        (
            "用户信息",
            {
                "fields": (
                    "github_id",
                    "github_login",
                    "email",
                )
            },
        ),
        (
            "时间周期",
            {
                "fields": (
                    "start_month",
                    "end_month",
                )
            },
        ),
        (
            "贡献度数据",
            {
                "fields": (
                    "contribution_score",
                    "raw_data",
                )
            },
        ),
        (
            "缓存时间",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def has_add_permission(self, request):
        """Disable add permission - cache is created automatically."""
        return False
