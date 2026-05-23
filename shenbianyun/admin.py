"""身边云模块 Django admin 注册."""

from django.contrib import admin

from .models import PaymentRecord, SignedUser


@admin.register(SignedUser)
class SignedUserAdmin(admin.ModelAdmin):
    """身边云签约用户只读查看入口."""

    list_display = (
        "offset_id",
        "name",
        "mobile",
        "id_card",
        "provider_id",
        "state",
        "payment_type",
        "created_at",
    )
    list_filter = ("state", "payment_type", "provider_id", "created_at")
    search_fields = ("offset_id", "name", "mobile", "id_card")
    readonly_fields = (
        "offset_id",
        "name",
        "mobile",
        "id_card",
        "provider_id",
        "payment_type",
        "state",
        "force_create_contract_flag",
        "ret_msg",
        "raw_data",
        "created_at",
        "updated_at",
    )
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    list_per_page = 50

    def has_add_permission(self, request):
        """禁止手工新增, 数据由同步任务写入."""
        return False

    def has_change_permission(self, request, obj=None):
        """禁止手工修改, 仅供查看."""
        return False

    def has_delete_permission(self, request, obj=None):
        """允许超管删除以便清理脏数据."""
        return request.user.is_superuser


@admin.register(PaymentRecord)
class PaymentRecordAdmin(admin.ModelAdmin):
    """付款记录管理."""

    list_display = [
        "mer_batch_id",
        "mer_order_id",
        "withdrawal_request",
        "amount",
        "state",
        "created_at",
    ]
    list_filter = ["state"]
    search_fields = ["mer_batch_id", "mer_order_id", "order_no"]
    readonly_fields = ["mer_batch_id", "mer_order_id", "order_no", "withdrawal_request"]
