"""Management command to grant points to users or organizations."""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from accounts.models import Organization, User
from points import services
from points.models import PointType


class Command(BaseCommand):
    """Management command to grant points to users or organizations."""

    help = "发放积分给用户或组织"

    def add_arguments(self, parser):
        """Add command arguments."""
        # 用户或组织选择（互斥）
        owner_group = parser.add_mutually_exclusive_group(required=True)
        owner_group.add_argument(
            "--user",
            type=str,
            help="用户名",
        )
        owner_group.add_argument(
            "--user-id",
            type=int,
            help="用户 ID",
        )
        owner_group.add_argument(
            "--org",
            type=str,
            help="组织 slug",
        )
        owner_group.add_argument(
            "--org-id",
            type=int,
            help="组织 ID",
        )

        # 必填参数
        parser.add_argument(
            "--amount",
            type=int,
            required=True,
            help="积分数量",
        )
        parser.add_argument(
            "--type",
            type=str,
            required=True,
            choices=["cash", "gift"],
            help="积分类型 (cash/gift)",
        )
        parser.add_argument(
            "--reason",
            type=str,
            required=True,
            help="发放原因",
        )

        # 可选参数
        parser.add_argument(
            "--tag",
            type=str,
            help="标签 slug（仅 gift 类型可用）",
        )
        parser.add_argument(
            "--expires",
            type=str,
            help="过期日期 (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--reference-id",
            type=str,
            default="",
            help="关联 ID",
        )

    def handle(self, *args, **options):
        """Execute the command."""
        # 获取所有者
        owner = self._get_owner(options)

        # 解析参数
        amount = options["amount"]
        point_type = options["type"]
        reason = options["reason"]
        tag_slug = options.get("tag")
        reference_id = options.get("reference_id", "")
        expires_str = options.get("expires")

        # 验证参数
        if amount <= 0:
            msg = "积分数量必须大于 0"
            raise CommandError(msg)

        if tag_slug and point_type != "gift":
            msg = "只有礼物积分可以设置标签"
            raise CommandError(msg)

        # 解析过期日期
        expires_at = None
        if expires_str:
            try:
                expires_at = datetime.strptime(expires_str, "%Y-%m-%d")
            except ValueError as err:
                msg = f"无效的日期格式: {expires_str}，应为 YYYY-MM-DD"
                raise CommandError(msg) from err

        # 发放积分
        try:
            source = services.grant_points(
                owner=owner,
                amount=amount,
                point_type=point_type,
                reason=reason,
                tag_slug=tag_slug,
                expires_at=expires_at,
                reference_id=reference_id,
            )
        except services.InvalidPointOperationError as e:
            raise CommandError(str(e)) from e

        # 输出结果
        owner_type = "用户" if isinstance(owner, User) else "组织"
        owner_name = owner.username if isinstance(owner, User) else owner.name
        point_type_display = PointType(point_type).label

        self.stdout.write(
            self.style.SUCCESS(
                f"成功发放 {amount} {point_type_display} 给 {owner_type} {owner_name}"
            )
        )
        self.stdout.write(f"  积分来源 ID: {source.id}")
        self.stdout.write(f"  原因: {reason}")
        if tag_slug:
            self.stdout.write(f"  标签: {tag_slug}")
        if expires_at:
            self.stdout.write(f"  过期时间: {expires_at.strftime('%Y-%m-%d')}")

        # 显示当前余额
        balance = services.get_detailed_balance(owner)
        self.stdout.write(f"  当前总余额: {balance['total']}")
        self.stdout.write(f"    - 现金积分: {balance['cash']}")
        self.stdout.write(f"    - 礼物积分: {balance['gift']}")

    def _get_owner(self, options):
        """Get owner (User or Organization) from options."""
        if options.get("user"):
            try:
                return User.objects.get(username=options["user"])
            except User.DoesNotExist as err:
                msg = f"用户不存在: {options['user']}"
                raise CommandError(msg) from err

        if options.get("user_id"):
            try:
                return User.objects.get(id=options["user_id"])
            except User.DoesNotExist as err:
                msg = f"用户不存在: ID={options['user_id']}"
                raise CommandError(msg) from err

        if options.get("org"):
            try:
                return Organization.objects.get(slug=options["org"])
            except Organization.DoesNotExist as err:
                msg = f"组织不存在: {options['org']}"
                raise CommandError(msg) from err

        if options.get("org_id"):
            try:
                return Organization.objects.get(id=options["org_id"])
            except Organization.DoesNotExist as err:
                msg = f"组织不存在: ID={options['org_id']}"
                raise CommandError(msg) from err

        # This line should never be reached due to argparse required=True
        msg = "必须指定 --user, --user-id, --org 或 --org-id 之一"
        raise CommandError(msg)  # pragma: no cover
