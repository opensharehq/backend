"""Tests for points management commands."""

from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from points.management.commands.create_default_point_sources import (
    Command as CreateDefaultSourcesCommand,
)
from points.models import PointSource, PointTransaction, Tag, WithdrawalRequest

User = get_user_model()


class GrantPointsCommandTests(TestCase):
    """Test cases for grant_points management command."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )

    def test_command_grants_points_by_username(self):
        """Test granting points using username."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            stdout=out,
        )

        self.assertIn("Successfully granted 100 points to testuser", out.getvalue())
        self.assertEqual(self.user.total_points, 100)

    def test_command_grants_points_by_email(self):
        """Test granting points using email."""
        out = StringIO()
        call_command(
            "grant_points",
            "test@example.com",
            "50",
            stdout=out,
        )

        self.assertIn("Successfully granted 50 points to testuser", out.getvalue())
        self.assertEqual(self.user.total_points, 50)

    def test_command_with_tag_name(self):
        """Test granting points with tag name."""
        Tag.objects.create(name="Premium", slug="premium")

        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--tags=Premium",
            stdout=out,
        )

        self.assertEqual(self.user.total_points, 100)
        source = PointSource.objects.first()
        self.assertTrue(source.tags.filter(name="Premium").exists())
        # Ensure no duplicate tag was created
        self.assertEqual(Tag.objects.filter(name="Premium").count(), 1)

    def test_command_with_tag_slug(self):
        """Test granting points with tag slug."""
        Tag.objects.create(name="Premium", slug="premium")

        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--tags=premium",
            stdout=out,
        )

        self.assertEqual(self.user.total_points, 100)
        source = PointSource.objects.first()
        self.assertTrue(source.tags.filter(slug="premium").exists())
        # Ensure no duplicate tag was created
        self.assertEqual(Tag.objects.filter(slug="premium").count(), 1)

    def test_command_with_multiple_tags(self):
        """Test granting points with multiple tags (mix of name and slug)."""
        Tag.objects.create(name="Tag One", slug="tag-one")
        Tag.objects.create(name="Tag Two", slug="tag-two")

        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--tags=tag-one,Tag Two",
            stdout=out,
        )

        self.assertEqual(self.user.total_points, 100)
        source = PointSource.objects.first()
        self.assertEqual(source.tags.count(), 2)

    def test_command_with_description(self):
        """Test granting points with custom description."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--description=Custom description",
            stdout=out,
        )

        transaction = PointTransaction.objects.first()
        self.assertEqual(transaction.description, "Custom description")

    def test_command_user_not_found(self):
        """Test granting points to non-existent user."""
        from django.core.management.base import CommandError

        with self.assertRaisesMessage(CommandError, "User not found"):
            call_command(
                "grant_points",
                "nonexistent",
                "100",
            )

    def test_command_invalid_points(self):
        """Test granting invalid points amount."""
        from django.core.management.base import CommandError

        with self.assertRaisesMessage(CommandError, "发放的积分必须是正整数"):
            call_command(
                "grant_points",
                "testuser",
                "0",
            )

    def test_command_negative_points(self):
        """Test granting negative points raises error."""
        from django.core.management.base import CommandError

        with self.assertRaisesMessage(CommandError, "发放的积分必须是正整数"):
            call_command(
                "grant_points",
                "testuser",
                "-50",
            )

    def test_command_with_short_form_description_flag(self):
        """Test using -d short form for description."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "75",
            "-d",
            "Short form description",
            stdout=out,
        )

        transaction = PointTransaction.objects.first()
        self.assertEqual(transaction.description, "Short form description")
        self.assertIn("Description: Short form description", out.getvalue())

    def test_command_with_short_form_tags_flag(self):
        """Test using -t short form for tags."""
        Tag.objects.create(name="bonus", slug="bonus")

        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "60",
            "-t",
            "bonus",
            stdout=out,
        )

        source = PointSource.objects.first()
        self.assertTrue(source.tags.filter(name="bonus").exists())
        self.assertIn("Tags: bonus", out.getvalue())

    def test_command_default_description(self):
        """Test that default description is '管理员发放' when not provided."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            stdout=out,
        )

        transaction = PointTransaction.objects.first()
        self.assertEqual(transaction.description, "管理员发放")
        self.assertIn("Description: 管理员发放", out.getvalue())


class CreateDefaultPointSourcesCommandEdgeTests(TestCase):
    """Cover error-handling branches of create_default_point_sources command."""

    def setUp(self):
        self.command = CreateDefaultSourcesCommand()
        self.command.stdout = StringIO()
        Tag.objects.get_or_create(slug="default", defaults={"name": "默认"})
        self.users = [
            User.objects.create_user(username=f"user{i}", password="pwd")
            for i in range(2)
        ]
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="pwd"
        )

    def test_process_batch_collects_user_errors(self):
        """If某个用户创建默认积分池失败，错误应被收集并返回。"""
        default_tag = Tag.objects.get(slug="default")
        with mock.patch.object(
            PointSource.objects, "create", side_effect=Exception("boom")
        ):
            created, errors = self.command._process_batch(
                self.users, default_tag, 0, len(self.users)
            )

        self.assertEqual(created, 0)
        self.assertEqual(len(errors), len(self.users))
        self.assertTrue(any("boom" in err for err in errors))
        # ensure branch wrote errors to stdout
        self.assertTrue(
            any(
                "错误" in line
                for line in getattr(self.command, "stdout", StringIO())
                .getvalue()
                .splitlines()
            )
        )

    def test_process_batch_handles_batch_exception(self):
        """整批事务失败时，所有用户都应被标记为错误。"""
        dummy_tag = Tag.objects.get(slug="default")

        class ExplodingContext:
            def __enter__(self):
                raise Exception("tx failed")

            def __exit__(self, exc_type, exc, tb):
                return False

        with mock.patch(
            "points.management.commands.create_default_point_sources.transaction.atomic",
            return_value=ExplodingContext(),
        ):
            created, errors = self.command._process_batch(
                self.users, dummy_tag, 0, len(self.users)
            )

        self.assertEqual(created, 0)
        self.assertEqual(len(errors), len(self.users))
        self.assertTrue(all("批次失败" in err or "tx failed" in err for err in errors))
        self.assertIn("批次处理失败", self.command.stdout.getvalue())

    def test_process_batch_reports_progress_every_ten(self):
        """当创建数达到整十时应输出进度百分比。"""
        default_tag = Tag.objects.get(slug="default")
        self.command.stdout = StringIO()
        batch_users = [
            User.objects.create_user(username=f"progress{i}") for i in range(10)
        ]

        created, errors = self.command._process_batch(
            batch_users, default_tag, created_count=0, total_users=len(batch_users)
        )

        self.assertEqual(created, 10)
        self.assertFalse(errors)
        self.assertIn("已创建 10/10 (100%)", self.command.stdout.getvalue())

    def test_show_results_displays_errors_and_remaining_users(self):
        """_show_results 覆盖错误展示和剩余用户提醒分支。"""
        out = StringIO()
        self.command.stdout = out
        many_errors = [f"err {i}" for i in range(12)]

        with mock.patch(
            "points.management.commands.create_default_point_sources.User.objects.exclude"
        ) as exclude_mock:
            exclude_mock.return_value.count.return_value = 3
            self.command._show_results(created_count=1, errors=many_errors)

        output = out.getvalue()
        self.assertIn("失败: 12 个用户", output)
        self.assertIn("以及其他 2 个错误", output)
        self.assertIn("仍有 3 个用户没有默认积分池", output)

    def test_show_results_success_when_all_users_handled(self):
        """当没有错误且所有用户都有默认积分池时显示成功提示。"""
        out = StringIO()
        self.command.stdout = out

        with mock.patch(
            "points.management.commands.create_default_point_sources.User.objects.exclude"
        ) as exclude_mock:
            exclude_mock.return_value.count.return_value = 0
            self.command._show_results(created_count=5, errors=[])

        output = out.getvalue()
        self.assertIn("成功创建 5 个默认积分池", output)
        self.assertIn("所有用户现在都拥有默认积分池", output)

    def test_command_default_tags(self):
        """Test that default tag is '默认' when not provided."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            stdout=out,
        )

        source = PointSource.objects.first()
        self.assertTrue(source.tags.filter(name="openshare").exists())
        self.assertIn("Tags: openshare", out.getvalue())

    def test_command_tags_with_whitespace(self):
        """Test that tags with extra whitespace are properly stripped."""
        Tag.objects.create(name="tag1", slug="tag1")
        Tag.objects.create(name="tag2", slug="tag2")

        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--tags= tag1 , tag2 ",
            stdout=out,
        )

        source = PointSource.objects.first()
        self.assertEqual(source.tags.count(), 2)
        self.assertTrue(source.tags.filter(name="tag1").exists())
        self.assertTrue(source.tags.filter(name="tag2").exists())

    def test_command_empty_tags_in_list(self):
        """Test that empty strings in tag list are filtered out."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--tags=,,,valid-tag,,,",
            stdout=out,
        )

        source = PointSource.objects.first()
        # Should only have one tag (empty strings filtered out)
        self.assertEqual(source.tags.count(), 1)
        self.assertTrue(source.tags.filter(name="valid-tag").exists())

    def test_command_all_flags_combined(self):
        """Test command with all flags combined."""
        Tag.objects.create(name="special", slug="special")

        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "200",
            "--description=All flags test",
            "--tags=special",
            stdout=out,
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.total_points, 200)

        transaction = PointTransaction.objects.first()
        self.assertEqual(transaction.description, "All flags test")

        source = PointSource.objects.first()
        self.assertTrue(source.tags.filter(name="special").exists())

        output = out.getvalue()
        self.assertIn("Successfully granted 200 points to testuser", output)
        self.assertIn("Description: All flags test", output)
        self.assertIn("Tags: special", output)
        self.assertIn("User's total points: 200", output)

    def test_command_creates_new_tags_when_not_exists(self):
        """Test that command creates new tags when they don't exist."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--tags=brand-new-tag",
            stdout=out,
        )

        # Tag should be created
        self.assertTrue(Tag.objects.filter(name="brand-new-tag").exists())

        source = PointSource.objects.first()
        self.assertTrue(source.tags.filter(name="brand-new-tag").exists())

    def test_command_output_shows_total_points(self):
        """Test that command output includes user's total points."""
        # Grant points twice to test accumulation
        out1 = StringIO()
        call_command("grant_points", "testuser", "100", stdout=out1)

        out2 = StringIO()
        call_command("grant_points", "testuser", "50", stdout=out2)

        self.assertIn("User's total points: 100", out1.getvalue())
        self.assertIn("User's total points: 150", out2.getvalue())

    def test_command_with_chinese_tag_names(self):
        """Test command with Chinese characters in tag names."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--tags=签到奖励,推荐奖励",
            stdout=out,
        )

        source = PointSource.objects.first()
        self.assertEqual(source.tags.count(), 2)
        self.assertTrue(source.tags.filter(name="签到奖励").exists())
        self.assertTrue(source.tags.filter(name="推荐奖励").exists())

    def test_command_point_source_creation(self):
        """Test that PointSource is created correctly."""
        out = StringIO()
        call_command("grant_points", "testuser", "150", stdout=out)

        source = PointSource.objects.first()
        self.assertIsNotNone(source)
        self.assertEqual(source.user_profile, self.user)
        self.assertEqual(source.initial_points, 150)
        self.assertEqual(source.remaining_points, 150)

    def test_command_point_transaction_creation(self):
        """Test that PointTransaction is created correctly."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "250",
            "--description=测试积分",
            stdout=out,
        )

        transaction = PointTransaction.objects.first()
        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.user_profile, self.user)
        self.assertEqual(transaction.points, 250)
        self.assertEqual(
            transaction.transaction_type, PointTransaction.TransactionType.EARN
        )
        self.assertEqual(transaction.description, "测试积分")

    def test_command_user_not_found_by_username_or_email(self):
        """Test that CommandError is raised when user is not found by username or email."""
        from django.core.management.base import CommandError

        with self.assertRaisesMessage(CommandError, "User not found: nosuchuser"):
            call_command("grant_points", "nosuchuser", "100")


class FixWithdrawalTransactionsCommandTests(TestCase):
    """测试修复提现交易记录命令."""

    def setUp(self):
        """设置测试数据."""
        self.user = User.objects.create_user(username="testuser")
        self.admin = User.objects.create_user(username="admin", is_staff=True)

        # 创建可提现的标签
        self.tag = Tag.objects.create(name="withdrawable", withdrawable=True)

        # 创建积分来源
        self.source = PointSource.objects.create(
            user=self.user, initial_points=1000, remaining_points=1000
        )
        self.source.tags.add(self.tag)

    def test_fix_completed_withdrawal_without_transaction(self):
        """测试修复已完成但没有交易记录的提现申请."""
        # 创建已完成的提现申请（模拟旧数据）
        withdrawal = WithdrawalRequest.objects.create(
            user=self.user,
            point_source=self.source,
            points=100,
            status=WithdrawalRequest.Status.COMPLETED,
            real_name="测试用户",
            id_number="123456789012345678",
            phone_number="13800138000",
            bank_name="测试银行",
            bank_account="6222021234567890",
            processed_by=self.admin,
            processed_at=timezone.now(),
        )

        # 确认没有交易记录
        self.assertEqual(PointTransaction.objects.count(), 0)

        # 运行修复命令
        out = StringIO()
        call_command("fix_withdrawal_transactions", stdout=out)

        # 验证创建了交易记录
        self.assertEqual(PointTransaction.objects.count(), 1)

        transaction = PointTransaction.objects.first()
        self.assertEqual(transaction.user, self.user)
        self.assertEqual(transaction.points, -100)
        self.assertEqual(
            transaction.transaction_type, PointTransaction.TransactionType.WITHDRAW
        )
        self.assertIn(f"#{withdrawal.id}", transaction.description)
        self.assertIn(self.source, transaction.consumed_sources.all())

        # 验证输出
        output = out.getvalue()
        self.assertIn("成功修复 1 个提现申请", output)

    def test_skip_withdrawal_with_existing_transaction(self):
        """测试跳过已有交易记录的提现申请."""
        # 创建已完成的提现申请
        withdrawal = WithdrawalRequest.objects.create(
            user=self.user,
            point_source=self.source,
            points=100,
            status=WithdrawalRequest.Status.COMPLETED,
            real_name="测试用户",
            id_number="123456789012345678",
            phone_number="13800138000",
            bank_name="测试银行",
            bank_account="6222021234567890",
            processed_by=self.admin,
            processed_at=timezone.now(),
        )

        # 创建对应的交易记录
        PointTransaction.objects.create(
            user=self.user,
            points=-100,
            transaction_type=PointTransaction.TransactionType.WITHDRAW,
            description=f"提现申请 #{withdrawal.id}",
        )

        # 运行修复命令
        out = StringIO()
        call_command("fix_withdrawal_transactions", stdout=out)

        # 验证没有创建新的交易记录
        self.assertEqual(PointTransaction.objects.count(), 1)

        # 验证输出
        output = out.getvalue()
        self.assertIn("跳过 1 个已有记录的申请", output)

    def test_dry_run_mode(self):
        """测试预览模式不实际修改数据."""
        # 创建已完成的提现申请
        WithdrawalRequest.objects.create(
            user=self.user,
            point_source=self.source,
            points=100,
            status=WithdrawalRequest.Status.COMPLETED,
            real_name="测试用户",
            id_number="123456789012345678",
            phone_number="13800138000",
            bank_name="测试银行",
            bank_account="6222021234567890",
            processed_by=self.admin,
            processed_at=timezone.now(),
        )

        # 运行预览模式
        out = StringIO()
        call_command("fix_withdrawal_transactions", "--dry-run", stdout=out)

        # 验证没有创建交易记录
        self.assertEqual(PointTransaction.objects.count(), 0)

        # 验证输出
        output = out.getvalue()
        self.assertIn("预览模式", output)
        self.assertIn("将修复 1 个提现申请", output)

    def test_fix_multiple_withdrawals(self):
        """测试修复多个提现申请."""
        # 创建多个已完成的提现申请
        for i in range(3):
            WithdrawalRequest.objects.create(
                user=self.user,
                point_source=self.source,
                points=100 + i * 10,
                status=WithdrawalRequest.Status.COMPLETED,
                real_name="测试用户",
                id_number="123456789012345678",
                phone_number="13800138000",
                bank_name="测试银行",
                bank_account="6222021234567890",
                processed_by=self.admin,
                processed_at=timezone.now(),
            )

        # 运行修复命令
        out = StringIO()
        call_command("fix_withdrawal_transactions", stdout=out)

        # 验证创建了3个交易记录
        self.assertEqual(PointTransaction.objects.count(), 3)

        # 验证输出
        output = out.getvalue()
        self.assertIn("成功修复 3 个提现申请", output)

    def test_only_process_completed_withdrawals(self):
        """测试只处理已完成状态的提现申请."""
        # 创建不同状态的提现申请
        WithdrawalRequest.objects.create(
            user=self.user,
            point_source=self.source,
            points=100,
            status=WithdrawalRequest.Status.PENDING,
            real_name="测试用户",
            id_number="123456789012345678",
            phone_number="13800138000",
            bank_name="测试银行",
            bank_account="6222021234567890",
        )

        WithdrawalRequest.objects.create(
            user=self.user,
            point_source=self.source,
            points=200,
            status=WithdrawalRequest.Status.REJECTED,
            real_name="测试用户",
            id_number="123456789012345678",
            phone_number="13800138000",
            bank_name="测试银行",
            bank_account="6222021234567890",
        )

        # 运行修复命令
        out = StringIO()
        call_command("fix_withdrawal_transactions", stdout=out)

        # 验证没有创建交易记录
        self.assertEqual(PointTransaction.objects.count(), 0)

        # 验证输出
        output = out.getvalue()
        self.assertIn("找到 0 个已完成的提现申请", output)


class CreateDefaultPointSourcesCommandTests(TestCase):
    """测试为存量用户创建默认积分池的命令."""

    def setUp(self):
        """设置测试数据."""
        # 确保 default 标签存在
        self.default_tag, _ = Tag.objects.get_or_create(
            slug="default",
            defaults={
                "name": "默认",
                "description": "用户默认积分池，支持充值和提现",
                "is_default": True,
                "withdrawable": True,
                "allow_recharge": True,
            },
        )

    def test_create_default_sources_for_users_without_one(self):
        """测试为没有默认积分池的用户创建."""
        # 创建3个没有默认积分池的用户
        user1 = User.objects.create_user(username="user1")
        user2 = User.objects.create_user(username="user2")
        user3 = User.objects.create_user(username="user3")

        # 删除自动创建的默认积分池（通过信号处理器创建的）
        PointSource.objects.filter(
            user__in=[user1, user2, user3], tags__slug="default"
        ).delete()

        # 运行命令
        out = StringIO()
        call_command("create_default_point_sources", stdout=out)

        # 验证每个用户都有默认积分池
        for user in [user1, user2, user3]:
            point_sources = PointSource.objects.filter(user=user, tags__slug="default")
            self.assertEqual(point_sources.count(), 1)

            ps = point_sources.first()
            self.assertEqual(ps.initial_points, 0)
            self.assertEqual(ps.remaining_points, 0)
            self.assertTrue(ps.allow_recharge)
            self.assertIn("管理命令", ps.notes)
            self.assertIn("存量用户", ps.notes)

        # 验证输出
        output = out.getvalue()
        self.assertIn("找到 3 个用户没有默认积分池", output)
        self.assertIn("成功创建 3 个默认积分池", output)
        self.assertIn("所有用户现在都拥有默认积分池", output)

    def test_skip_users_with_existing_default_source(self):
        """测试跳过已有默认积分池的用户."""
        # 创建用户并手动创建默认积分池
        user = User.objects.create_user(username="user1")
        ps = PointSource.objects.create(
            user=user, initial_points=100, remaining_points=100
        )
        ps.tags.add(self.default_tag)

        # 运行命令
        out = StringIO()
        call_command("create_default_point_sources", stdout=out)

        # 验证没有创建新的积分池
        self.assertEqual(PointSource.objects.filter(user=user).count(), 1)

        # 验证输出
        output = out.getvalue()
        self.assertIn("所有用户都已经拥有默认积分池", output)

    def test_dry_run_mode(self):
        """测试预览模式不实际创建数据."""
        # 创建2个用户
        user1 = User.objects.create_user(username="user1")
        user2 = User.objects.create_user(username="user2")

        # 删除自动创建的默认积分池（通过信号处理器创建的）
        PointSource.objects.filter(
            user__in=[user1, user2], tags__slug="default"
        ).delete()

        # 运行预览模式
        out = StringIO()
        call_command("create_default_point_sources", "--dry-run", stdout=out)

        # 验证没有创建积分池
        self.assertEqual(PointSource.objects.count(), 0)

        # 验证输出
        output = out.getvalue()
        self.assertIn("【预览模式】", output)
        self.assertIn("找到 2 个用户没有默认积分池", output)
        self.assertIn("总计将创建 2 个默认积分池", output)
        self.assertIn("不带 --dry-run 参数", output)

    def test_default_tag_not_exists(self):
        """测试 default 标签不存在时的错误处理."""
        # 创建用户
        User.objects.create_user(username="user1")

        # 删除 default 标签（这也会删除关联的积分池）
        Tag.objects.filter(slug="default").delete()

        # 运行命令
        out = StringIO()
        call_command("create_default_point_sources", stdout=out)

        # 验证没有创建积分池
        self.assertEqual(PointSource.objects.count(), 0)

        # 验证输出
        output = out.getvalue()
        self.assertIn("错误", output)
        self.assertIn("未找到 default 标签", output)
        self.assertIn("先运行 migrate", output)

    def test_batch_processing(self):
        """测试批量处理功能."""
        # 使用 bulk_create 创建10个用户（不会触发信号）
        users = User.objects.bulk_create(
            [User(username=f"user{i}", password="test123") for i in range(10)]
        )

        # 运行命令，指定批次大小为3
        out = StringIO()
        call_command("create_default_point_sources", "--batch-size=3", stdout=out)

        # 验证所有用户都有默认积分池
        for user in users:
            self.assertTrue(
                PointSource.objects.filter(user=user, tags__slug="default").exists(),
                f"用户 {user.username} 应该有默认积分池",
            )

        # 验证输出包含成功创建的信息
        output = out.getvalue()
        self.assertIn("成功创建 10 个默认积分池", output)

    def test_mixed_scenario(self):
        """测试混合场景: 部分用户有默认积分池, 部分没有."""
        # 创建用户1，有默认积分池
        user1 = User.objects.create_user(username="user1")
        # 删除信号自动创建的，然后手动创建一个
        PointSource.objects.filter(user=user1, tags__slug="default").delete()
        ps1 = PointSource.objects.create(
            user=user1, initial_points=50, remaining_points=50
        )
        ps1.tags.add(self.default_tag)

        # 创建用户2和3，没有默认积分池
        user2 = User.objects.create_user(username="user2")
        user3 = User.objects.create_user(username="user3")

        # 删除自动创建的默认积分池
        PointSource.objects.filter(
            user__in=[user2, user3], tags__slug="default"
        ).delete()

        # 用户2有其他标签的积分池
        other_tag = Tag.objects.create(name="other", slug="other")
        ps2 = PointSource.objects.create(
            user=user2, initial_points=100, remaining_points=100
        )
        ps2.tags.add(other_tag)

        # 运行命令
        out = StringIO()
        call_command("create_default_point_sources", stdout=out)

        # 验证user1的积分池数量没变
        self.assertEqual(PointSource.objects.filter(user=user1).count(), 1)

        # 验证user2和user3有了默认积分池
        self.assertTrue(
            PointSource.objects.filter(user=user2, tags__slug="default").exists()
        )
        self.assertTrue(
            PointSource.objects.filter(user=user3, tags__slug="default").exists()
        )

        # user2现在有2个积分池（other 和 default）
        self.assertEqual(PointSource.objects.filter(user=user2).count(), 2)

        # 验证输出
        output = out.getvalue()
        self.assertIn("找到 2 个用户没有默认积分池", output)
        self.assertIn("成功创建 2 个默认积分池", output)

    def test_dry_run_shows_sample_users(self):
        """测试预览模式显示示例用户."""
        # 使用 bulk_create 创建15个用户（不会触发信号）
        User.objects.bulk_create(
            [
                User(
                    username=f"user{i}",
                    email=f"user{i}@example.com",
                    password="test123",
                )
                for i in range(15)
            ]
        )

        # 运行预览模式
        out = StringIO()
        call_command("create_default_point_sources", "--dry-run", stdout=out)

        output = out.getvalue()
        # 应该显示前10个用户
        self.assertIn("user0", output)
        self.assertIn("user9", output)
        # 应该显示还有其他用户
        self.assertIn("以及其他 5 个用户", output)

    def test_default_tag_properties(self):
        """测试创建的积分池继承了 default 标签的属性."""
        user = User.objects.create_user(username="testuser")

        # 删除自动创建的默认积分池
        PointSource.objects.filter(user=user, tags__slug="default").delete()

        # 运行命令
        out = StringIO()
        call_command("create_default_point_sources", stdout=out)

        # 获取创建的积分池
        ps = PointSource.objects.get(user=user, tags__slug="default")

        # 验证可充值和可提现
        self.assertTrue(ps.is_rechargeable)
        self.assertTrue(ps.is_withdrawable)

    def test_no_users_scenario(self):
        """测试没有用户时的处理."""
        # 确保没有用户（除了可能在 setUp 中创建的）
        User.objects.all().delete()

        # 运行命令
        out = StringIO()
        call_command("create_default_point_sources", stdout=out)

        output = out.getvalue()
        self.assertIn("所有用户都已经拥有默认积分池", output)
