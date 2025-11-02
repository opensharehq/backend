"""修复已完成提现申请的交易记录."""

from django.core.management.base import BaseCommand
from django.db import transaction

from points.models import PointTransaction, WithdrawalRequest


class Command(BaseCommand):
    """为已完成的提现申请补充创建交易记录."""

    help = "为已完成但没有交易记录的提现申请补充创建交易记录"

    def add_arguments(self, parser):
        """添加命令参数."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="只显示将要修复的记录，不实际修改",
        )

    def handle(self, *args, **options):
        """执行命令."""
        dry_run = options["dry_run"]

        # 查找所有已完成的提现申请
        completed_withdrawals = WithdrawalRequest.objects.filter(
            status=WithdrawalRequest.Status.COMPLETED
        ).order_by("id")

        self.stdout.write(f"找到 {completed_withdrawals.count()} 个已完成的提现申请")

        fixed_count = 0
        skipped_count = 0

        for withdrawal in completed_withdrawals:
            # 检查是否已经有对应的交易记录
            existing_transaction = PointTransaction.objects.filter(
                user=withdrawal.user,
                transaction_type=PointTransaction.TransactionType.WITHDRAW,
                description__contains=f"#{withdrawal.id}",
            ).first()

            if existing_transaction:
                self.stdout.write(
                    self.style.WARNING(
                        f"  [跳过] 提现申请 #{withdrawal.id} 已有交易记录 (ID: {existing_transaction.id})"
                    )
                )
                skipped_count += 1
                continue

            # 需要创建交易记录
            if dry_run:
                self.stdout.write(
                    self.style.NOTICE(
                        f"  [预览] 将为提现申请 #{withdrawal.id} 创建交易记录 "
                        f"(用户: {withdrawal.user.username}, 积分: -{withdrawal.points})"
                    )
                )
                fixed_count += 1
            else:
                # 创建交易记录
                with transaction.atomic():
                    new_transaction = PointTransaction.objects.create(
                        user=withdrawal.user,
                        points=-withdrawal.points,  # 提现是负数
                        transaction_type=PointTransaction.TransactionType.WITHDRAW,
                        description=f"提现申请 #{withdrawal.id}",
                        created_at=withdrawal.processed_at
                        or withdrawal.created_at,  # 使用处理时间，如果没有则使用申请时间
                    )
                    # 关联积分来源
                    if withdrawal.point_source:
                        new_transaction.consumed_sources.add(withdrawal.point_source)

                self.stdout.write(
                    self.style.SUCCESS(
                        f"  [完成] 已为提现申请 #{withdrawal.id} 创建交易记录 (ID: {new_transaction.id})"
                    )
                )
                fixed_count += 1

        # 输出总结
        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING("=== 预览模式 ==="))
            self.stdout.write(f"将修复 {fixed_count} 个提现申请")
            self.stdout.write(f"跳过 {skipped_count} 个已有记录的申请")
            self.stdout.write("")
            self.stdout.write("运行命令时不带 --dry-run 参数以实际执行修复")
        else:
            self.stdout.write(self.style.SUCCESS("=== 修复完成 ==="))
            self.stdout.write(self.style.SUCCESS(f"成功修复 {fixed_count} 个提现申请"))
            self.stdout.write(f"跳过 {skipped_count} 个已有记录的申请")
