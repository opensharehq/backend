"""同步身边云签约用户到本地数据库 (funCode=6044)."""

from django.core.management.base import BaseCommand, CommandError

from shenbianyun.services import (
    SIGN_STATE_SIGNED,
    ShenbianyunError,
    sync_signed_users,
)


class Command(BaseCommand):
    """同步身边云签约用户到本地 SignedUser 表."""

    help = (
        "拉取身边云 6044 接口签约用户数据并落库。"
        "首次同步会全量拉取；后续同步以本地最新一条记录的 "
        "(idCard, mobile, name) 三元组为分水岭做增量同步。"
    )

    def add_arguments(self, parser):
        """注册命令参数."""
        parser.add_argument(
            "--provider-id",
            type=int,
            default=None,
            help="服务商 ID，未传则使用 settings.SBY_PROVIDER_ID",
        )
        parser.add_argument(
            "--begin",
            type=str,
            default="1970-01-01 00:00:00",
            help="签约创建时间开始 (yyyy-MM-dd HH:mm:ss)",
        )
        parser.add_argument(
            "--end",
            type=str,
            default=None,
            help="签约创建时间结束 (yyyy-MM-dd HH:mm:ss)，默认当前时间",
        )
        parser.add_argument(
            "--state",
            type=int,
            default=SIGN_STATE_SIGNED,
            help="签约状态: 0未签约 1已签约 3签约中 4签约失败 5已解约",
        )
        parser.add_argument(
            "--max-pages",
            type=int,
            default=1000,
            help="最多翻页数，防止无限循环 (默认 1000)",
        )

    def handle(self, *args, **options):
        """执行同步."""
        try:
            stats = sync_signed_users(
                provider_id=options.get("provider_id"),
                create_time_begin=options["begin"],
                create_time_end=options.get("end"),
                state=options["state"],
                max_pages=options["max_pages"],
            )
        except (ShenbianyunError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"同步完成: pages={stats['pages']}, "
                f"fetched={stats['fetched']}, "
                f"created={stats['created']}, "
                f"updated={stats['updated']}, "
                f"stopped_by={stats['stopped_by']}"
            )
        )
