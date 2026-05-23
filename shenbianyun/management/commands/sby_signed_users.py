"""调用身边云接口获取签约用户列表并打印输出 (funCode=6044)."""

import json

from django.core.management.base import BaseCommand, CommandError

from shenbianyun.services import (
    SIGN_STATE_SIGNED,
    ShenbianyunError,
    get_signed_users,
)


class Command(BaseCommand):
    """获取我的账号下的签约用户列表."""

    help = (
        "调用身边云 funCode=6044 接口，查询签约用户列表并打印结果。"
        "默认 createTimeBegin=1970-01-01 00:00:00，"
        "createTimeEnd=当前时间，state=1 (已签约)。"
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

    def handle(self, *args, **options):
        """执行查询并打印 JSON 结果."""
        try:
            users = get_signed_users(
                provider_id=options.get("provider_id"),
                create_time_begin=options["begin"],
                create_time_end=options.get("end"),
                state=options["state"],
            )
        except (ShenbianyunError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(f"共获取到 {len(users)} 条签约用户记录"))
        self.stdout.write(json.dumps(users, ensure_ascii=False, indent=2))
