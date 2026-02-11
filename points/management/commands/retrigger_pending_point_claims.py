"""Manually retrigger pending point claim for existing users."""

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from points.allocation_services import AllocationService


class Command(BaseCommand):
    """Manually retrigger pending point claim for existing users."""

    help = "手动重新触发存量用户的待领取积分发放"

    def add_arguments(self, parser):
        """Add command arguments."""
        target_group = parser.add_mutually_exclusive_group(required=True)
        target_group.add_argument(
            "--all",
            action="store_true",
            help="处理所有已绑定 GitHub 的用户",
        )
        target_group.add_argument(
            "--user",
            type=str,
            help="仅处理指定用户名",
        )
        target_group.add_argument(
            "--user-id",
            type=int,
            help="仅处理指定用户 ID",
        )
        parser.add_argument(
            "--include-without-github",
            action="store_true",
            help="与 --all 一起使用，处理所有用户（包括未绑定 GitHub）",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="仅预览可领取数据，不执行实际发放",
        )

    def handle(self, *args, **options):
        """Execute command."""
        include_without_github = options.get("include_without_github", False)
        dry_run = options.get("dry_run", False)
        if include_without_github and not options.get("all"):
            msg = "--include-without-github 只能与 --all 一起使用"
            raise CommandError(msg)

        users = self._get_target_users(options, include_without_github)
        processed_users = 0
        users_with_claims = 0
        total_claimed_count = 0
        total_amount = 0
        failed_users = []

        for user in users:
            processed_users += 1
            try:
                if dry_run:
                    result = AllocationService.get_claimable_pending_points_summary(user)
                    claimed_count = result["claimable_count"]
                else:
                    result = AllocationService.claim_pending_points(user)
                    claimed_count = result["claimed_count"]
            except Exception as err:
                failed_users.append((user.username, str(err)))
                continue

            if claimed_count > 0:
                users_with_claims += 1
                total_claimed_count += claimed_count
                total_amount += result["total_amount"]
                if dry_run:
                    self.stdout.write(
                        f"用户 {user.username}: 可领取 {claimed_count} 条，共 {result['total_amount']} 积分"
                    )
                else:
                    self.stdout.write(
                        f"用户 {user.username}: 领取 {claimed_count} 条，共 {result['total_amount']} 积分"
                    )

        if dry_run:
            summary_title = "预览完成："
        else:
            summary_title = "处理完成："
        self.stdout.write(
            self.style.SUCCESS(
                summary_title
                + f"用户数 {processed_users}，"
                f"有领取用户 {users_with_claims}，"
                f"领取记录 {total_claimed_count}，"
                f"总积分 {total_amount}"
            )
        )

        if failed_users:
            self.stderr.write(
                self.style.WARNING(f"有 {len(failed_users)} 个用户处理失败")
            )
            for username, error in failed_users:
                self.stderr.write(f"  - {username}: {error}")
            msg = "存在处理失败的用户，请先修复后重试"
            raise CommandError(msg)

    def _get_target_users(self, options, include_without_github):
        """Return target users queryset."""
        if options.get("all"):
            if include_without_github:
                return User.objects.all().order_by("id").prefetch_related("social_auth")
            return (
                User.objects.filter(social_auth__provider="github")
                .distinct()
                .order_by("id")
                .prefetch_related("social_auth")
            )

        if options.get("user"):
            username = options["user"]
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist as err:
                msg = f"用户不存在: {username}"
                raise CommandError(msg) from err
            return User.objects.filter(id=user.id).prefetch_related("social_auth")

        if options.get("user_id"):
            user_id = options["user_id"]
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist as err:
                msg = f"用户不存在: ID={user_id}"
                raise CommandError(msg) from err
            return User.objects.filter(id=user.id).prefetch_related("social_auth")

        msg = "必须指定 --all, --user 或 --user-id"
        raise CommandError(msg)  # pragma: no cover
