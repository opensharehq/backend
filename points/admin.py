"""Admin configuration for the points app."""

from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    PointSource,
    PointTransaction,
    Tag,
    WithdrawalContractSigning,
    WithdrawalRequest,
)
from .services import approve_withdrawal, reject_withdrawal
from .withdrawal_contracts import handle_withdrawal_contract_webhook

User = get_user_model()


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    """Admin for Tag model."""

    list_display = (
        "name",
        "slug",
        "is_default",
        "withdrawable",
        "allow_recharge",
        "description_short",
    )
    list_filter = ("is_default", "withdrawable", "allow_recharge")
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
        "rechargeable_status",
    )
    list_filter = ("created_at", "expires_at", "tags", "allow_recharge")
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
            "设置",
            {
                "fields": ("allow_recharge",),
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

    @admin.display(boolean=True, description="可充值")
    def rechargeable_status(self, obj):
        """Display if points are rechargeable based on settings or tags."""
        return obj.is_rechargeable


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


@admin.register(WithdrawalRequest)
class WithdrawalRequestAdmin(admin.ModelAdmin):
    """Admin for WithdrawalRequest model."""

    list_display = (
        "id",
        "user",
        "points",
        "colored_status",
        "real_name",
        "phone_number",
        "created_at",
        "processed_at",
        "processed_by",
    )
    list_filter = ("status", "created_at", "processed_at")
    search_fields = (
        "user__username",
        "user__email",
        "real_name",
        "id_number",
        "phone_number",
        "bank_account",
    )
    readonly_fields = (
        "user",
        "point_source",
        "points",
        "real_name",
        "id_number",
        "phone_number",
        "bank_name",
        "bank_account",
        "created_at",
        "updated_at",
        "processed_at",
        "processed_by",
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    actions = ["approve_selected", "reject_selected"]

    fieldsets = (
        (
            "申请信息",
            {
                "fields": (
                    "user",
                    "point_source",
                    "points",
                    "status",
                ),
            },
        ),
        (
            "个人信息",
            {
                "fields": (
                    "real_name",
                    "id_number",
                    "phone_number",
                ),
            },
        ),
        (
            "银行账户",
            {
                "fields": (
                    "bank_name",
                    "bank_account",
                ),
            },
        ),
        (
            "处理信息",
            {
                "fields": (
                    "admin_note",
                    "processed_by",
                    "processed_at",
                ),
            },
        ),
        (
            "时间信息",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )

    @admin.display(description="状态")
    def colored_status(self, obj):
        """Display status with color."""
        color_map = {
            WithdrawalRequest.Status.PENDING: "orange",
            WithdrawalRequest.Status.REJECTED: "red",
            WithdrawalRequest.Status.COMPLETED: "green",
            WithdrawalRequest.Status.CANCELLED: "gray",
        }
        color = color_map.get(obj.status, "black")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display(),
        )

    @admin.action(description="完成选中的提现申请")
    def approve_selected(self, request, queryset):
        """Complete selected withdrawal requests."""
        pending_requests = queryset.filter(status=WithdrawalRequest.Status.PENDING)
        completed_count = 0
        error_count = 0

        for withdrawal in pending_requests:
            try:
                approve_withdrawal(withdrawal, request.user)
                completed_count += 1
            except Exception as e:
                error_count += 1
                self.message_user(
                    request,
                    f"完成申请 #{withdrawal.id} 失败: {e!s}",
                    level="ERROR",
                )

        if completed_count > 0:
            self.message_user(
                request,
                f"成功完成 {completed_count} 个提现申请，已扣除积分并创建交易记录。",
                level="SUCCESS",
            )

        if error_count > 0:
            self.message_user(
                request,
                f"{error_count} 个提现申请完成失败。",
                level="WARNING",
            )

    @admin.action(description="拒绝选中的提现申请")
    def reject_selected(self, request, queryset):
        """Reject selected withdrawal requests."""
        pending_requests = queryset.filter(status=WithdrawalRequest.Status.PENDING)
        rejected_count = 0
        error_count = 0

        for withdrawal in pending_requests:
            try:
                reject_withdrawal(withdrawal, request.user, admin_note="管理员批量拒绝")
                rejected_count += 1
            except Exception as e:
                error_count += 1
                self.message_user(
                    request,
                    f"拒绝申请 #{withdrawal.id} 失败: {e!s}",
                    level="ERROR",
                )

        if rejected_count > 0:
            self.message_user(
                request,
                f"成功拒绝 {rejected_count} 个提现申请。",
                level="SUCCESS",
            )

        if error_count > 0:
            self.message_user(
                request,
                f"{error_count} 个提现申请拒绝失败。",
                level="WARNING",
            )


@admin.register(WithdrawalContractSigning)
class WithdrawalContractSigningAdmin(admin.ModelAdmin):
    """Admin for WithdrawalContractSigning model."""

    list_display = (
        "id",
        "user",
        "status",
        "real_name",
        "phone_number",
        "signed_at",
        "created_at",
        "withdrawal_request_count",
    )
    list_filter = ("status", "created_at", "signed_at")
    search_fields = (
        "user__username",
        "user__email",
        "real_name",
        "id_number",
        "phone_number",
        "bank_account",
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    actions = ["mark_signed_and_create_withdrawals"]

    readonly_fields = (
        "user",
        "status",
        "real_name",
        "id_number",
        "phone_number",
        "bank_name",
        "bank_account",
        "withdrawal_payload",
        "created_withdrawal_request_ids",
        "withdrawal_error",
        "fdd_request_payload",
        "fdd_response_payload",
        "fdd_webhook_payload",
        "signed_at",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (
            "签署信息",
            {
                "fields": (
                    "user",
                    "status",
                    "signed_at",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
        (
            "身份信息",
            {
                "fields": (
                    "real_name",
                    "id_number",
                    "phone_number",
                ),
            },
        ),
        (
            "收款信息",
            {
                "fields": (
                    "bank_name",
                    "bank_account",
                ),
            },
        ),
        (
            "提现申请",
            {
                "fields": (
                    "withdrawal_payload",
                    "created_withdrawal_request_ids",
                    "withdrawal_error",
                ),
            },
        ),
        (
            "法大大记录",
            {
                "fields": (
                    "fdd_request_payload",
                    "fdd_response_payload",
                    "fdd_webhook_payload",
                ),
            },
        ),
    )

    @admin.display(description="已创建提现")
    def withdrawal_request_count(self, obj):
        """Display count of created withdrawal requests."""
        if not obj.created_withdrawal_request_ids:
            return 0
        return len(obj.created_withdrawal_request_ids)

    @admin.action(description="标记为已签署并创建提现申请")
    def mark_signed_and_create_withdrawals(self, request, queryset):
        """Manually mark selected records as signed and create withdrawals."""
        updated = 0
        failed = 0

        for record in queryset:
            if record.status == WithdrawalContractSigning.Status.SIGNED:
                continue
            try:
                handle_withdrawal_contract_webhook(
                    {
                        "signing_record_id": record.id,
                        "status": "SIGNED",
                        "signed_at": timezone.now().isoformat(),
                        "source": "admin",
                    }
                )
                updated += 1
            except Exception as exc:
                failed += 1
                self.message_user(
                    request,
                    f"处理签署记录 #{record.id} 失败: {exc!s}",
                    level="ERROR",
                )

        if updated:
            self.message_user(
                request,
                f"已处理 {updated} 条签署记录。",
                level="SUCCESS",
            )
        if failed:
            self.message_user(
                request,
                f"{failed} 条签署记录处理失败。",
                level="WARNING",
            )
