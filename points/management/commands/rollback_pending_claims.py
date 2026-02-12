"""Rollback claimed pending point grants for a user."""

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from points import services
from points.allocation_services import AllocationService


class Command(BaseCommand):
    """Rollback claimed pending point grants for a user."""

    help = "回退某个用户的已领取待领取积分，并扣除对应积分"

    def add_arguments(self, parser):
        """Add command arguments."""
        target_group = parser.add_mutually_exclusive_group(required=True)
        target_group.add_argument(
            "--user",
            type=str,
            help="用户名",
        )
        target_group.add_argument(
            "--user-id",
            type=int,
            help="用户 ID",
        )
        parser.add_argument(
            "--grant-id",
            type=int,
            action="append",
            dest="grant_ids",
            help="指定要回退的待领取记录 ID，可重复传入多次",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="仅预览将回退的数据，不执行实际扣减与状态变更",
        )

    def handle(self, *args, **options):
        """Execute command."""
        user = self._get_user(options)
        grant_ids = options.get("grant_ids") or None
        dry_run = options.get("dry_run", False)

        if dry_run:
            self._handle_dry_run(user=user, grant_ids=grant_ids)
            return

        try:
            result = AllocationService.rollback_claimed_points_for_user(
                user=user,
                grant_ids=grant_ids,
            )
        except services.InsufficientPointsError as err:
            raise CommandError(str(err)) from err

        rolled_back_count = result["rolled_back_count"]
        total_amount = result["total_amount"]

        if rolled_back_count == 0:
            self.stdout.write(self.style.WARNING("未找到可回退的已领取记录"))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"已回退用户 {user.username} 的 {rolled_back_count} 条记录，共 {total_amount} 积分"
            )
        )
        if grant_ids:
            self.stdout.write(
                f"  指定记录 ID: {', '.join(str(gid) for gid in grant_ids)}"
            )

        balance = services.get_detailed_balance(user)
        self.stdout.write(f"  当前总余额: {balance['total']}")
        self.stdout.write(f"    - 现金积分: {balance['cash']}")
        self.stdout.write(f"    - 礼物积分: {balance['gift']}")

    def _handle_dry_run(self, *, user, grant_ids):
        """Preview rollback result without applying changes."""
        summary = AllocationService.get_rollback_claimed_points_summary(
            user=user,
            grant_ids=grant_ids,
        )
        rollbackable_count = summary["rollbackable_count"]
        total_amount = summary["total_amount"]

        if rollbackable_count == 0:
            self.stdout.write(self.style.WARNING("预览结果：未找到可回退的已领取记录"))
            return

        self.stdout.write(
            self.style.WARNING(
                "预览模式："
                f"将回退用户 {user.username} 的 {rollbackable_count} 条记录，"
                f"共 {total_amount} 积分"
            )
        )
        if grant_ids:
            self.stdout.write(
                f"  指定记录 ID: {', '.join(str(gid) for gid in grant_ids)}"
            )

        if summary["can_execute"]:
            self.stdout.write("  余额检查: 通过（正式执行预计成功）")
        else:
            self.stdout.write("  余额检查: 未通过（正式执行会失败）")
            self.stdout.write(f"  原因: {summary['blocking_error']}")

    def _get_user(self, options):
        """Get target user from options."""
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

        msg = "必须指定 --user 或 --user-id"
        raise CommandError(msg)  # pragma: no cover
