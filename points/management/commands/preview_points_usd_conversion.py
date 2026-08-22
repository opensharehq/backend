"""Preview the one-time RMB-to-USD point balance conversion."""

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

from points.models import (
    PendingPointGrant,
    PointAllocation,
    PointSource,
    WithdrawalRequest,
)
from points.point_conversion import build_conversion_summary
from talent_reach.models import OutreachRecipient


class Command(BaseCommand):
    """Report conversion totals and fail when production blockers exist."""

    help = "预览存量积分从 RMB 比例切换到 USD 比例的数据转换（只读）"
    MIGRATION_NAME = "0008_convert_existing_points_to_usd_scale"

    def add_arguments(self, parser):
        """Add output format options."""
        parser.add_argument(
            "--json",
            action="store_true",
            help="以 JSON 输出预检结果",
        )

    def handle(self, *args, **options):
        """Build and display a read-only conversion plan."""
        if self._migration_applied():
            self.stdout.write(
                self.style.WARNING(
                    f"迁移 points.{self.MIGRATION_NAME} 已执行；不会再次计算转换。"
                )
            )
            return

        summary = build_conversion_summary(
            PointSource=PointSource,
            PendingPointGrant=PendingPointGrant,
            PointAllocation=PointAllocation,
            WithdrawalRequest=WithdrawalRequest,
            OutreachRecipient=OutreachRecipient,
        )
        if options["json"]:
            self.stdout.write(json.dumps(summary.as_dict(), ensure_ascii=False))
        else:
            self._write_summary(summary)

        if summary.has_blockers:
            msg = "存在未完成积分操作，请先处理后再部署转换 migration"
            raise CommandError(msg)

    def _migration_applied(self) -> bool:
        return (
            MigrationRecorder(connection)
            .migration_qs.filter(
                app="points",
                name=self.MIGRATION_NAME,
            )
            .exists()
        )

    def _write_summary(self, summary) -> None:
        self.stdout.write("积分换算预检（1 USD = 10 积分，存量金额 ÷ 6.7 向下取整）")
        self.stdout.write(
            f"钱包来源：{summary.source_rows} 行，"
            f"{summary.wallet_buckets} 个钱包/类型，"
            f"{summary.wallet_old_total} -> {summary.wallet_new_total}"
        )
        self.stdout.write(
            f"分配待领取记录：{summary.pending_rows} 行"
            f"（未领取 {summary.pending_unclaimed_rows} 行），"
            f"{summary.pending_old_total} -> {summary.pending_new_total}，"
            f"未领取归零 {summary.pending_unclaimed_zero_after} 行"
        )
        self.stdout.write(
            f"触达待领取奖励：{summary.outreach_unclaimed_rows} 行，"
            f"{summary.outreach_old_total} -> {summary.outreach_new_total}，"
            f"归零 {summary.outreach_zero_after} 行"
        )
        self.stdout.write(
            f"阻塞项：未完成积分分配 {summary.blocking_allocations}，"
            f"待处理/已批准提现 {summary.blocking_withdrawals}"
        )
        if not summary.has_blockers:
            self.stdout.write(
                self.style.SUCCESS("预检通过，可以部署并执行 migration。")
            )
