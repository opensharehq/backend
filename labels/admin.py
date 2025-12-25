import json

from django.contrib import admin
from django.http import HttpResponse
from django.utils.html import format_html

from .models import Label, LabelPermission, LabelPermissionLog


class LabelPermissionInline(admin.TabularInline):
    """标签权限内联编辑"""

    model = LabelPermission
    extra = 0
    fields = [
        "grantee_type",
        "grantee_id",
        "permission_level",
        "granted_by",
        "expires_at",
        "is_active",
    ]
    readonly_fields = ["granted_by", "granted_at"]

    def get_queryset(self, request):
        """只显示激活的权限"""
        qs = super().get_queryset(request)
        return qs.filter(is_active=True)


@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
    """标签管理后台"""

    list_display = [
        "id",
        "name",
        "name_zh",
        "type",
        "owner_type",
        "owner_display",
        "entity_count",
        "is_public",
        "sync_source",
        "created_at",
    ]

    list_filter = [
        "type",
        "owner_type",
        "is_public",
        "sync_source",
        "created_at",
    ]

    search_fields = [
        "name",
        "name_zh",
        "owner_id",
    ]

    readonly_fields = [
        "created_at",
        "updated_at",
        "last_synced_at",
        "sync_source",
        "entity_count_detail",
        "data_preview",
    ]

    fieldsets = (
        ("基本信息", {"fields": ("name", "name_zh", "type")}),
        ("所有者信息", {"fields": ("owner_type", "owner_id", "is_public")}),
        (
            "标签数据",
            {
                "fields": ("data", "data_preview", "entity_count_detail"),
                "classes": ("collapse",),
            },
        ),
        (
            "同步信息",
            {
                "fields": ("sync_source", "last_synced_at"),
                "classes": ("collapse",),
            },
        ),
        (
            "时间戳",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    inlines = [LabelPermissionInline]

    actions = ["make_public", "make_private", "export_labels"]

    def owner_display(self, obj):
        """显示所有者信息"""
        if obj.owner_type == "system":
            return format_html('<span style="color: blue;">系统</span>')
        elif obj.owner_type == "user":
            from accounts.models import User

            try:
                user = User.objects.get(id=obj.owner_id)
                return format_html(
                    '<a href="/admin/accounts/user/{}/change/">{}</a>',
                    obj.owner_id,
                    user.username,
                )
            except User.DoesNotExist:
                return f"用户 #{obj.owner_id} (已删除)"
        elif obj.owner_type == "organization":
            # 假设有 Organization 模型
            return f"组织 #{obj.owner_id}"
        return "-"

    owner_display.short_description = "所有者"

    def entity_count(self, obj):
        """计算标签包含的实体总数"""
        count = 0
        for platform in obj.data.get("platforms", []):
            count += len(platform.get("orgs", []))
            count += len(platform.get("repos", []))
            count += len(platform.get("developers", []))
        return count

    entity_count.short_description = "实体数量"

    def entity_count_detail(self, obj):
        """详细的实体计数"""
        details = []
        for platform in obj.data.get("platforms", []):
            platform_name = platform.get("name", "Unknown")
            org_count = len(platform.get("orgs", []))
            repo_count = len(platform.get("repos", []))
            dev_count = len(platform.get("developers", []))
            details.append(
                f"{platform_name}: {org_count} 组织, {repo_count} 仓库, {dev_count} 开发者"
            )
        return "\n".join(details) if details else "无数据"

    entity_count_detail.short_description = "实体详情"

    def data_preview(self, obj):
        """JSON 数据预览"""
        return format_html(
            '<pre style="max-height: 300px; overflow: auto;">{}</pre>',
            json.dumps(obj.data, indent=2, ensure_ascii=False),
        )

    data_preview.short_description = "数据预览"

    def make_public(self, request, queryset):
        """批量设为公开"""
        updated = queryset.update(is_public=True)
        self.message_user(request, f"成功将 {updated} 个标签设为公开")

    make_public.short_description = "设为公开"

    def make_private(self, request, queryset):
        """批量设为私有"""
        updated = queryset.update(is_public=False)
        self.message_user(request, f"成功将 {updated} 个标签设为私有")

    make_private.short_description = "设为私有"

    def export_labels(self, request, queryset):
        """导出标签为 JSON"""
        labels_data = []
        for label in queryset:
            labels_data.append(
                {
                    "name": label.name,
                    "name_zh": label.name_zh,
                    "type": label.type,
                    "data": label.data,
                }
            )

        response = HttpResponse(
            json.dumps(labels_data, indent=2, ensure_ascii=False),
            content_type="application/json",
        )
        response["Content-Disposition"] = 'attachment; filename="labels_export.json"'
        return response

    export_labels.short_description = "导出选中标签"


@admin.register(LabelPermission)
class LabelPermissionAdmin(admin.ModelAdmin):
    """标签权限管理后台"""

    list_display = [
        "id",
        "label_link",
        "grantee_display",
        "permission_level",
        "status_display",
        "granted_by_display",
        "granted_at",
        "expires_at",
    ]

    list_filter = [
        "permission_level",
        "grantee_type",
        "is_active",
        "granted_at",
    ]

    search_fields = [
        "label__name",
        "label__name_zh",
        "grantee_id",
        "notes",
    ]

    readonly_fields = [
        "granted_at",
        "granted_by",
    ]

    fieldsets = (
        (
            "权限信息",
            {"fields": ("label", "grantee_type", "grantee_id", "permission_level")},
        ),
        (
            "授权信息",
            {"fields": ("granted_by", "granted_at", "expires_at", "is_active")},
        ),
        (
            "备注",
            {"fields": ("notes",)},
        ),
    )

    actions = ["activate_permissions", "deactivate_permissions"]

    def label_link(self, obj):
        """标签链接"""
        return format_html(
            '<a href="/admin/labels/label/{}/change/">{}</a>',
            obj.label.id,
            obj.label.name,
        )

    label_link.short_description = "标签"

    def grantee_display(self, obj):
        """被授权对象显示"""
        if obj.grantee_type == "user":
            from accounts.models import User

            try:
                user = User.objects.get(id=obj.grantee_id)
                return format_html(
                    '用户: <a href="/admin/accounts/user/{}/change/">{}</a>',
                    obj.grantee_id,
                    user.username,
                )
            except User.DoesNotExist:
                return f"用户 #{obj.grantee_id} (已删除)"
        elif obj.grantee_type == "organization":
            return f"组织 #{obj.grantee_id}"
        return "-"

    grantee_display.short_description = "被授权对象"

    def granted_by_display(self, obj):
        """授权者显示"""
        if not obj.granted_by:
            return "-"
        return format_html(
            '<a href="/admin/accounts/user/{}/change/">{}</a>',
            obj.granted_by.id,
            obj.granted_by.username,
        )

    granted_by_display.short_description = "授权者"

    def status_display(self, obj):
        """权限状态显示"""
        if not obj.is_active:
            return format_html('<span style="color: red;">已撤销</span>')
        if obj.is_expired():
            return format_html('<span style="color: gray;">已过期</span>')
        return format_html('<span style="color: green;">激活</span>')

    status_display.short_description = "状态"

    def activate_permissions(self, request, queryset):
        """激活权限"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f"成功激活 {updated} 个权限")

    activate_permissions.short_description = "激活选中权限"

    def deactivate_permissions(self, request, queryset):
        """停用权限"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f"成功停用 {updated} 个权限")

    deactivate_permissions.short_description = "停用选中权限"


@admin.register(LabelPermissionLog)
class LabelPermissionLogAdmin(admin.ModelAdmin):
    """标签权限日志管理后台"""

    list_display = [
        "id",
        "permission_link",
        "action",
        "actor_display",
        "timestamp",
    ]

    list_filter = [
        "action",
        "timestamp",
    ]

    search_fields = [
        "permission__label__name",
        "actor__username",
    ]

    readonly_fields = [
        "permission",
        "action",
        "actor",
        "timestamp",
        "details_display",
    ]

    fieldsets = (
        ("日志信息", {"fields": ("permission", "action", "actor", "timestamp")}),
        (
            "变更详情",
            {"fields": ("details_display",)},
        ),
    )

    def has_add_permission(self, request):
        """禁止添加日志(只能由系统创建)"""
        return False

    def has_delete_permission(self, request, obj=None):
        """禁止删除日志(审计需要)"""
        return False

    def permission_link(self, obj):
        """权限链接"""
        return format_html(
            '<a href="/admin/labels/labelpermission/{}/change/">权限 #{}</a>',
            obj.permission.id,
            obj.permission.id,
        )

    permission_link.short_description = "权限"

    def actor_display(self, obj):
        """操作者显示"""
        if not obj.actor:
            return "系统"
        return format_html(
            '<a href="/admin/accounts/user/{}/change/">{}</a>',
            obj.actor.id,
            obj.actor.username,
        )

    actor_display.short_description = "操作者"

    def details_display(self, obj):
        """详情显示"""
        return format_html(
            "<pre>{}</pre>",
            json.dumps(obj.details, indent=2, ensure_ascii=False),
        )

    details_display.short_description = "变更详情"
