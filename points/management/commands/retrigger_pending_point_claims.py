"""Manually retrigger pending point claim for existing users."""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Prefetch
from social_django.models import UserSocialAuth

from accounts.models import User
from points.allocation_services import AllocationService


class Command(BaseCommand):
    """Manually retrigger pending point claim for existing users."""

    help = "手动重新触发存量用户的待领取积分发放"
    DEFAULT_BATCH_SIZE = 500

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
        parser.add_argument(
            "--batch-size",
            type=int,
            default=self.DEFAULT_BATCH_SIZE,
            help="仅在 --all 下生效，按 ID 分批处理用户数",
        )

    def handle(self, *args, **options):
        """Execute command."""
        process_all = options.get("all", False)
        include_without_github = options.get("include_without_github", False)
        dry_run = options.get("dry_run", False)
        batch_size = options.get("batch_size", self.DEFAULT_BATCH_SIZE)
        self._validate_options(
            include_without_github=include_without_github,
            process_all=process_all,
            batch_size=batch_size,
        )

        users = self._get_target_users(options, include_without_github)
        processed_users = 0
        users_with_claims = 0
        total_claimed_count = 0
        total_amount = 0
        failed_users = []

        for user in self._iter_target_users(
            users,
            process_all=process_all,
            batch_size=batch_size,
        ):
            processed_users += 1
            try:
                result, claimed_count = self._process_user(
                    user,
                    dry_run=dry_run,
                )
            except Exception as err:
                failed_users.append((user.username, str(err)))
                continue

            if claimed_count <= 0:
                continue

            users_with_claims += 1
            total_claimed_count += claimed_count
            total_amount += result["total_amount"]
            self._write_user_result(
                user,
                claimed_count=claimed_count,
                total_amount=result["total_amount"],
                dry_run=dry_run,
            )

        self._write_summary(
            processed_users=processed_users,
            users_with_claims=users_with_claims,
            total_claimed_count=total_claimed_count,
            total_amount=total_amount,
            dry_run=dry_run,
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
                return self._with_github_social_auth_prefetch(
                    User.objects.all().order_by("id")
                )
            queryset = (
                User.objects.filter(social_auth__provider="github")
                .distinct()
                .order_by("id")
            )
            return self._with_github_social_auth_prefetch(queryset)

        if options.get("user"):
            username = options["user"]
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist as err:
                msg = f"用户不存在: {username}"
                raise CommandError(msg) from err
            return self._with_github_social_auth_prefetch(
                User.objects.filter(id=user.id)
            )

        if options.get("user_id"):
            user_id = options["user_id"]
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist as err:
                msg = f"用户不存在: ID={user_id}"
                raise CommandError(msg) from err
            return self._with_github_social_auth_prefetch(
                User.objects.filter(id=user.id)
            )

        msg = "必须指定 --all, --user 或 --user-id"
        raise CommandError(msg)  # pragma: no cover

    def _validate_options(
        self,
        *,
        include_without_github: bool,
        process_all: bool,
        batch_size: int,
    ) -> None:
        if include_without_github and not process_all:
            msg = "--include-without-github 只能与 --all 一起使用"
            raise CommandError(msg)
        if batch_size <= 0:
            msg = "--batch-size 必须大于 0"
            raise CommandError(msg)

    def _process_user(self, user, *, dry_run: bool) -> tuple[dict, int]:
        if dry_run:
            result = AllocationService.get_claimable_pending_points_summary(user)
            return result, result["claimable_count"]

        result = AllocationService.claim_pending_points(user)
        return result, result["claimed_count"]

    def _write_user_result(
        self,
        user,
        *,
        claimed_count: int,
        total_amount: int,
        dry_run: bool,
    ) -> None:
        if dry_run:
            self.stdout.write(
                f"用户 {user.username}: 可领取 {claimed_count} 条，共 {total_amount} 积分"
            )
            return
        self.stdout.write(
            f"用户 {user.username}: 领取 {claimed_count} 条，共 {total_amount} 积分"
        )

    def _write_summary(
        self,
        *,
        processed_users: int,
        users_with_claims: int,
        total_claimed_count: int,
        total_amount: int,
        dry_run: bool,
    ) -> None:
        summary_title = "预览完成：" if dry_run else "处理完成："
        self.stdout.write(
            self.style.SUCCESS(
                summary_title + f"用户数 {processed_users}，"
                f"有领取用户 {users_with_claims}，"
                f"领取记录 {total_claimed_count}，"
                f"总积分 {total_amount}"
            )
        )

    def _with_github_social_auth_prefetch(self, queryset):
        """Prefetch github social auth records into list attribute."""
        return queryset.prefetch_related(
            Prefetch(
                "social_auth",
                queryset=UserSocialAuth.objects.filter(provider="github")
                .only("id", "user_id", "uid")
                .order_by("id"),
                to_attr=AllocationService.GITHUB_SOCIAL_AUTH_PREFETCH_ATTR,
            )
        )

    def _iter_target_users(self, queryset, *, process_all: bool, batch_size: int):
        """Yield users with bounded memory for --all mode."""
        if not process_all:
            yield from queryset
            return

        last_id = 0
        while True:
            batch = list(queryset.filter(id__gt=last_id)[:batch_size])
            if not batch:
                break
            yield from batch
            last_id = batch[-1].id
