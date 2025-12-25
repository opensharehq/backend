"""Models for labels and related permissions."""

from django.db import models
from django.utils import timezone


class LabelType(models.TextChoices):
    """标签类型枚举."""

    PROJECT = "project", "项目"
    ENTERPRISE = "enterprise", "企业"
    FOUNDATION = "foundation", "基金会"
    TECHNOLOGY = "technology", "技术领域"
    COMMUNITY = "community", "社区"


class OwnerType(models.TextChoices):
    """所有者类型枚举."""

    SYSTEM = "system", "系统"  # OpenDigger 同步的标签
    USER = "user", "个人"  # 用户创建的标签
    ORGANIZATION = "organization", "组织"  # 组织创建的标签


class PermissionLevel(models.TextChoices):
    """权限级别枚举."""

    VIEW = "view", "查看"  # 仅可查看标签及其数据
    USE = "use", "使用"  # 可查看和使用标签(积分分发、筛选)
    EDIT = "edit", "编辑"  # 可查看、使用和编辑标签数据
    MANAGE = "manage", "管理"  # 完全控制(包括删除、授权)


class GranteeType(models.TextChoices):
    """被授权对象类型枚举."""

    USER = "user", "用户"  # 授权给个人用户
    ORGANIZATION = "organization", "组织"  # 授权给整个组织


class Label(models.Model):
    """
    标签模型, 用于分类项目、组织和开发者.

    与 OpenDigger 标签系统集成.
    """

    name = models.CharField(max_length=200, db_index=True, verbose_name="英文名称")
    name_zh = models.CharField(max_length=200, verbose_name="中文名称")
    type = models.CharField(
        max_length=20,
        choices=LabelType.choices,
        db_index=True,
        verbose_name="标签类型",
    )
    owner_type = models.CharField(
        max_length=20,
        choices=OwnerType.choices,
        default=OwnerType.USER,
        db_index=True,
        verbose_name="所有者类型",
    )
    owner_id = models.IntegerField(
        null=True, blank=True, db_index=True, verbose_name="所有者ID"
    )
    data = models.JSONField(default=dict, verbose_name="标签数据")
    is_public = models.BooleanField(default=False, verbose_name="是否公开")
    sync_source = models.CharField(
        max_length=50, blank=True, default="", verbose_name="同步来源"
    )
    last_synced_at = models.DateTimeField(
        null=True, blank=True, verbose_name="最后同步时间"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        """Meta options for Label."""

        db_table = "labels"
        verbose_name = "标签"
        verbose_name_plural = "标签"
        indexes = [
            models.Index(fields=["owner_type", "owner_id"]),
            models.Index(fields=["type", "is_public"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "owner_type", "owner_id"],
                name="unique_label_per_owner",
            )
        ]

    def __str__(self):
        """Return string representation with name and type."""
        return f"{self.name} ({self.get_type_display()})"

    def get_platform_entities(self, platform_name):
        """提取特定平台的组织/仓库/开发者."""
        for platform in self.data.get("platforms", []):
            if platform["name"] == platform_name:
                return platform
        return None

    def has_access(self, user, required_level="view"):
        """
        检查用户是否可以访问此标签.

        支持通过 LabelPermission 的授权访问.
        """
        # 公开标签：允许查看/使用，不开放编辑或管理
        if self.is_public and required_level in (
            PermissionLevel.VIEW,
            PermissionLevel.USE,
        ):
            return True

        # 系统标签对所有人可见
        if self.owner_type == OwnerType.SYSTEM:
            return required_level == "view"

        # 所有者拥有完全权限
        if self.owner_type == OwnerType.USER and self.owner_id == user.id:
            return True

        # 延迟导入以避免潜在循环依赖
        from accounts.models import OrganizationMembership

        # 预取用户的组织成员关系，便于后续多处复用
        memberships = list(
            OrganizationMembership.objects.filter(user=user).values(
                "organization_id", "role"
            )
        )
        user_org_ids = {m["organization_id"] for m in memberships}
        admin_org_ids = {
            m["organization_id"]
            for m in memberships
            if m["role"]
            in (OrganizationMembership.Role.ADMIN, OrganizationMembership.Role.OWNER)
        }

        if self.owner_type == OwnerType.ORGANIZATION:
            # 组织成员可查看/使用标签；管理员/所有者可编辑/管理
            if self.owner_id in user_org_ids and required_level in (
                PermissionLevel.VIEW,
                PermissionLevel.USE,
            ):
                return True
            if self.owner_id in admin_org_ids:
                return True

        # 检查直接授予用户的权限
        user_permission = self.permissions.filter(
            grantee_type=GranteeType.USER, grantee_id=user.id, is_active=True
        ).first()
        if user_permission and user_permission.check_permission(required_level):
            return True

        # 检查通过组织授予的权限
        if user_org_ids:
            org_permissions = self.permissions.filter(
                grantee_type=GranteeType.ORGANIZATION,
                grantee_id__in=user_org_ids,
                is_active=True,
            )
            for perm in org_permissions:
                if perm.check_permission(required_level):
                    return True

        return False

    def can_edit(self, user):
        """检查用户是否可以编辑此标签."""
        if self.owner_type == OwnerType.SYSTEM:
            return False
        return self.has_access(user, required_level="edit")

    def can_manage(self, user):
        """检查用户是否可以管理此标签(删除、授权等)."""
        if self.owner_type == OwnerType.SYSTEM:
            return False
        return self.has_access(user, required_level="manage")


class LabelPermission(models.Model):
    """标签共享权限模型, 支持跨用户和跨组织的标签访问控制."""

    label = models.ForeignKey(
        "Label",
        on_delete=models.CASCADE,
        related_name="permissions",
        verbose_name="标签",
    )
    grantee_type = models.CharField(
        max_length=20, choices=GranteeType.choices, verbose_name="被授权对象类型"
    )
    grantee_id = models.IntegerField(verbose_name="被授权对象ID")
    permission_level = models.CharField(
        max_length=20, choices=PermissionLevel.choices, verbose_name="权限级别"
    )
    granted_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="granted_permissions",
        verbose_name="授权者",
    )
    granted_at = models.DateTimeField(auto_now_add=True, verbose_name="授权时间")
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name="过期时间")
    is_active = models.BooleanField(default=True, verbose_name="是否激活")
    notes = models.TextField(blank=True, verbose_name="备注")

    class Meta:
        """Meta options for LabelPermission."""

        db_table = "label_permissions"
        verbose_name = "标签权限"
        verbose_name_plural = "标签权限"
        indexes = [
            models.Index(fields=["label", "grantee_type", "grantee_id"]),
            models.Index(fields=["grantee_type", "grantee_id", "is_active"]),
            models.Index(fields=["expires_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["label", "grantee_type", "grantee_id"],
                condition=models.Q(is_active=True),
                name="unique_active_permission",
            )
        ]

    def __str__(self):
        """Return readable permission description."""
        return (
            f"{self.label.name} - {self.get_permission_level_display()} "
            f"to {self.grantee_type}:{self.grantee_id}"
        )

    def is_expired(self):
        """检查权限是否已过期."""
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at

    def check_permission(self, required_level):
        """检查是否具有所需权限级别."""
        if not self.is_active or self.is_expired():
            return False

        # 权限级别层级: VIEW < USE < EDIT < MANAGE
        levels = ["view", "use", "edit", "manage"]
        current_index = levels.index(self.permission_level)
        required_index = levels.index(required_level)
        return current_index >= required_index


class LabelPermissionLog(models.Model):
    """标签权限变更审计日志."""

    ACTION_CHOICES = [
        ("granted", "授予"),
        ("updated", "更新"),
        ("revoked", "撤销"),
        ("expired", "过期"),
    ]

    permission = models.ForeignKey(
        LabelPermission, on_delete=models.CASCADE, verbose_name="权限"
    )
    action = models.CharField(
        max_length=20, choices=ACTION_CHOICES, verbose_name="操作"
    )
    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        verbose_name="操作者",
    )
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="时间戳")
    details = models.JSONField(default=dict, verbose_name="变更详情")

    class Meta:
        """Meta options for LabelPermissionLog."""

        db_table = "label_permission_logs"
        verbose_name = "标签权限日志"
        verbose_name_plural = "标签权限日志"
        ordering = ["-timestamp"]

    def __str__(self):
        """Return string description of permission log entry."""
        return f"{self.get_action_display()} - {self.permission} at {self.timestamp}"
