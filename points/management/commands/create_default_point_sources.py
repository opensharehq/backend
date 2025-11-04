"""Management command for creating default point sources for existing users."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from points.models import PointSource, Tag

User = get_user_model()


class Command(BaseCommand):
    """Create default point sources for existing users who don't have one."""

    help = "为没有默认积分池的存量用户创建默认积分池"

    def add_arguments(self, parser):
        """Add command arguments."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="预览将要创建的积分池，但不实际执行",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="批量处理的用户数量（默认: 100）",
        )

    def handle(self, *args, **options):
        """Execute the command."""
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        # 获取 default 标签
        default_tag = self._get_default_tag()
        if not default_tag:
            return

        # 获取没有默认积分池的用户
        users_without_default = self._get_users_without_default()
        total_users = len(users_without_default)

        if total_users == 0:
            self.stdout.write(self.style.SUCCESS("所有用户都已经拥有默认积分池！"))
            return

        self.stdout.write(f"找到 {total_users} 个用户没有默认积分池")

        # 预览模式
        if dry_run:
            self._show_dry_run_preview(users_without_default, total_users)
            return

        # 实际创建积分池
        created_count, errors = self._create_point_sources(
            users_without_default, default_tag, batch_size, total_users
        )

        # 显示最终结果
        self._show_results(created_count, errors)

    def _get_default_tag(self):
        """获取 default 标签."""
        try:
            default_tag = Tag.objects.get(slug="default")
        except Tag.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(
                    "错误: 未找到 default 标签。请先运行 migrate 以创建 default 标签。"
                )
            )
            return None

        # 显示 default 标签信息
        self.stdout.write(
            self.style.SUCCESS(
                f"找到 default 标签: {default_tag.name} (slug={default_tag.slug})"
            )
        )
        self.stdout.write(
            f"  可充值: {default_tag.allow_recharge}, "
            f"可提现: {default_tag.withdrawable}"
        )
        self.stdout.write("")

        return default_tag

    def _get_users_without_default(self):
        """获取所有没有 default 标签积分池的用户."""
        # 先获取所有有 default 标签积分池的用户ID
        users_with_default = PointSource.objects.filter(
            tags__slug="default"
        ).values_list("user_id", flat=True)

        # 获取所有没有 default 标签积分池的用户
        # 转换为列表以避免 QuerySet 延迟执行导致的数据不一致
        return list(User.objects.exclude(id__in=users_with_default).order_by("id"))

    def _show_dry_run_preview(self, users_without_default, total_users):
        """显示预览模式信息."""
        self.stdout.write(self.style.WARNING("\n【预览模式】以下用户将创建默认积分池:"))
        # 显示前 10 个用户作为示例
        sample_users = users_without_default[:10]
        for user in sample_users:
            self.stdout.write(
                f"  - {user.username} (ID: {user.id}, Email: {user.email})"
            )
        if total_users > 10:
            self.stdout.write(f"  ... 以及其他 {total_users - 10} 个用户")
        self.stdout.write(
            self.style.WARNING(f"\n总计将创建 {total_users} 个默认积分池")
        )
        self.stdout.write("\n运行时不带 --dry-run 参数以实际执行创建操作")

    def _create_point_sources(
        self, users_without_default, default_tag, batch_size, total_users
    ):
        """实际创建积分池."""
        self.stdout.write(f"\n开始为 {total_users} 个用户创建默认积分池...")

        created_count = 0
        errors = []

        # 分批处理
        for i in range(0, total_users, batch_size):
            batch = users_without_default[i : i + batch_size]

            batch_created, batch_errors = self._process_batch(
                batch, default_tag, created_count, total_users
            )
            created_count += batch_created
            errors.extend(batch_errors)

        return created_count, errors

    def _process_batch(self, batch, default_tag, created_count, total_users):
        """处理一批用户."""
        batch_created = 0
        batch_errors = []

        try:
            with transaction.atomic():
                for user in batch:
                    try:
                        # 创建积分池
                        point_source = PointSource.objects.create(
                            user=user,
                            initial_points=0,
                            remaining_points=0,
                            allow_recharge=True,
                            notes="管理命令为存量用户创建的默认积分池",
                        )
                        # 关联 default 标签
                        point_source.tags.add(default_tag)

                        batch_created += 1

                        # 每 10 个显示一次进度
                        total_created = created_count + batch_created
                        if total_created % 10 == 0:
                            self.stdout.write(
                                f"  已创建 {total_created}/{total_users} "
                                f"({total_created * 100 // total_users}%)"
                            )

                    except Exception as e:
                        error_msg = f"用户 {user.username} (ID: {user.id}): {e}"
                        batch_errors.append(error_msg)
                        self.stdout.write(self.style.ERROR(f"  错误: {error_msg}"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"批次处理失败: {e}"))
            # 如果整个批次失败，将所有用户标记为错误
            for user in batch:
                if not any(user.username in err for err in batch_errors):
                    batch_errors.append(
                        f"用户 {user.username} (ID: {user.id}): 批次失败"
                    )

        return batch_created, batch_errors

    def _show_results(self, created_count, errors):
        """显示最终结果."""
        error_count = len(errors)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS(f"成功创建 {created_count} 个默认积分池"))

        if error_count > 0:
            self.stdout.write(self.style.ERROR(f"失败: {error_count} 个用户"))
            self.stdout.write("\n错误详情:")
            for error in errors[:10]:  # 只显示前 10 个错误
                self.stdout.write(self.style.ERROR(f"  - {error}"))
            if len(errors) > 10:
                self.stdout.write(
                    self.style.ERROR(f"  ... 以及其他 {len(errors) - 10} 个错误")
                )

        self.stdout.write(self.style.SUCCESS("=" * 60))

        # 验证结果
        remaining_users = User.objects.exclude(
            id__in=PointSource.objects.filter(tags__slug="default").values_list(
                "user_id", flat=True
            )
        ).count()

        if remaining_users == 0:
            self.stdout.write(self.style.SUCCESS("\n✓ 所有用户现在都拥有默认积分池！"))
        else:
            self.stdout.write(
                self.style.WARNING(f"\n⚠ 仍有 {remaining_users} 个用户没有默认积分池")
            )
