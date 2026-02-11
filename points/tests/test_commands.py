"""Tests for points management commands."""

from datetime import date
from io import StringIO

from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from social_django.models import UserSocialAuth

from accounts.models import Organization, User
from points import services
from points.allocation_services import AllocationService
from points.management.commands.retrigger_pending_point_claims import (
    Command as RetriggerPendingPointClaimsCommand,
)
from points.models import PendingPointGrant, PointAllocation, PointType, Tag


class GrantPointsCommandTests(TestCase):
    """Tests for grant_points management command."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.org = Organization.objects.create(name="Test Org", slug="test-org")
        self.tag = Tag.objects.create(name="活动", slug="event")

    def test_grant_cash_to_user_by_username(self):
        """Test granting cash points to user by username."""
        out = StringIO()
        call_command(
            "grant_points",
            user="testuser",
            amount=100,
            type="cash",
            reason="测试奖励",
            stdout=out,
        )

        balance = services.get_balance(self.user, PointType.CASH)
        self.assertEqual(balance, 100)
        self.assertIn("成功发放", out.getvalue())

    def test_grant_cash_to_user_by_id(self):
        """Test granting cash points to user by ID."""
        out = StringIO()
        call_command(
            "grant_points",
            user_id=self.user.id,
            amount=50,
            type="cash",
            reason="测试奖励",
            stdout=out,
        )

        balance = services.get_balance(self.user, PointType.CASH)
        self.assertEqual(balance, 50)

    def test_grant_gift_to_user(self):
        """Test granting gift points to user."""
        out = StringIO()
        call_command(
            "grant_points",
            user="testuser",
            amount=75,
            type="gift",
            reason="礼物",
            stdout=out,
        )

        balance = services.get_balance(self.user, PointType.GIFT)
        self.assertEqual(balance, 75)

    def test_grant_gift_with_tag(self):
        """Test granting gift points with tag."""
        out = StringIO()
        call_command(
            "grant_points",
            user="testuser",
            amount=100,
            type="gift",
            tag="event",
            reason="活动奖励",
            stdout=out,
        )

        balance = services.get_balance(self.user, PointType.GIFT, tag_slug="event")
        self.assertEqual(balance, 100)
        self.assertIn("标签: event", out.getvalue())

    def test_grant_to_org_by_slug(self):
        """Test granting points to organization by slug."""
        out = StringIO()
        call_command(
            "grant_points",
            org="test-org",
            amount=200,
            type="cash",
            reason="组织奖励",
            stdout=out,
        )

        balance = services.get_balance(self.org, PointType.CASH)
        self.assertEqual(balance, 200)
        self.assertIn("组织", out.getvalue())

    def test_grant_to_org_by_id(self):
        """Test granting points to organization by ID."""
        out = StringIO()
        call_command(
            "grant_points",
            org_id=self.org.id,
            amount=150,
            type="cash",
            reason="组织奖励",
            stdout=out,
        )

        balance = services.get_balance(self.org, PointType.CASH)
        self.assertEqual(balance, 150)

    def test_grant_with_reference_id(self):
        """Test granting points with reference ID."""
        out = StringIO()
        call_command(
            "grant_points",
            user="testuser",
            amount=100,
            type="cash",
            reason="外部系统",
            reference_id="ext:12345",
            stdout=out,
        )

        wallet = services.get_or_create_wallet(self.user)
        source = wallet.sources.first()
        self.assertEqual(source.reference_id, "ext:12345")

    def test_grant_with_expiration(self):
        """Test granting points with expiration date."""
        out = StringIO()
        call_command(
            "grant_points",
            user="testuser",
            amount=100,
            type="gift",
            reason="限时",
            expires="2025-12-31",
            stdout=out,
        )

        wallet = services.get_or_create_wallet(self.user)
        source = wallet.sources.first()
        self.assertIsNotNone(source.expires_at)
        self.assertIn("过期时间: 2025-12-31", out.getvalue())

    def test_user_not_found_fails(self):
        """Test that non-existent user fails."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                "grant_points",
                user="nonexistent",
                amount=100,
                type="cash",
                reason="测试",
            )
        self.assertIn("用户不存在", str(cm.exception))

    def test_org_not_found_fails(self):
        """Test that non-existent org fails."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                "grant_points",
                org="nonexistent",
                amount=100,
                type="cash",
                reason="测试",
            )
        self.assertIn("组织不存在", str(cm.exception))

    def test_zero_amount_fails(self):
        """Test that zero amount fails."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                "grant_points",
                user="testuser",
                amount=0,
                type="cash",
                reason="测试",
            )
        self.assertIn("大于 0", str(cm.exception))

    def test_tag_on_cash_fails(self):
        """Test that tag on cash points fails."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                "grant_points",
                user="testuser",
                amount=100,
                type="cash",
                tag="event",
                reason="测试",
            )
        self.assertIn("只有礼物积分可以设置标签", str(cm.exception))

    def test_invalid_tag_fails(self):
        """Test that invalid tag fails."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                "grant_points",
                user="testuser",
                amount=100,
                type="gift",
                tag="nonexistent",
                reason="测试",
            )
        self.assertIn("标签不存在", str(cm.exception))

    def test_invalid_date_format_fails(self):
        """Test that invalid date format fails."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                "grant_points",
                user="testuser",
                amount=100,
                type="gift",
                expires="invalid-date",
                reason="测试",
            )
        self.assertIn("无效的日期格式", str(cm.exception))

    def test_user_id_not_found_fails(self):
        """Test that non-existent user ID fails."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                "grant_points",
                user_id=99999,
                amount=100,
                type="cash",
                reason="测试",
            )
        self.assertIn("用户不存在", str(cm.exception))

    def test_org_id_not_found_fails(self):
        """Test that non-existent org ID fails."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                "grant_points",
                org_id=99999,
                amount=100,
                type="cash",
                reason="测试",
            )
        self.assertIn("组织不存在", str(cm.exception))

    def test_no_target_specified_fails(self):
        """Test that no target specified fails."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                "grant_points",
                amount=100,
                type="cash",
                reason="测试",
            )
        # Django argparse returns English error for missing arguments
        self.assertIn("required", str(cm.exception).lower())


class RollbackPendingClaimsCommandTests(TestCase):
    """Tests for rollback_pending_claims management command."""

    def setUp(self):
        """Set up test fixtures."""
        self.granter = User.objects.create_user(username="granter", password="pass")
        self.target_user = User.objects.create_user(
            username="claimuser",
            email="claimuser@example.com",
            password="pass",
        )

        services.grant_points(
            owner=self.granter,
            amount=100000,
            point_type=PointType.GIFT,
            reason="测试积分池",
        )
        source_pool = self.granter.point_wallet.sources.first()

        self.allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.granter.id,
            source_pool=source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

    def _create_and_claim_grant(self, amount=5000):
        pending_grant = PendingPointGrant.objects.create(
            github_id="",
            github_login=self.target_user.username,
            email=self.target_user.email,
            amount=amount,
            point_type=PointType.GIFT,
            reason="测试待领取",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.granter.id,
            allocation=self.allocation,
        )

        claim_result = AllocationService.claim_pending_points(self.target_user)
        self.assertEqual(claim_result["claimed_count"], 1)
        pending_grant.refresh_from_db()
        self.assertTrue(pending_grant.is_claimed)
        return pending_grant

    def test_rollback_claimed_grants_success(self):
        """Test rollback pending claimed grants successfully."""
        pending_grant = self._create_and_claim_grant(amount=5000)
        out = StringIO()

        call_command(
            "rollback_pending_claims",
            user=self.target_user.username,
            stdout=out,
        )

        pending_grant.refresh_from_db()
        self.assertFalse(pending_grant.is_claimed)
        self.assertIsNone(pending_grant.claimed_by)
        self.assertIsNone(pending_grant.claimed_at)

        balance = services.get_balance(self.target_user, PointType.GIFT)
        self.assertEqual(balance, 0)
        self.assertIn("已回退用户", out.getvalue())

    def test_rollback_claimed_grants_insufficient_balance_fails(self):
        """Test rollback fails when user balance is insufficient."""
        pending_grant = self._create_and_claim_grant(amount=5000)

        services.spend_points(
            owner=self.target_user,
            amount=5000,
            point_type=PointType.GIFT,
            description="主动消费",
            tag_is_null=True,
        )

        with self.assertRaises(CommandError) as cm:
            call_command(
                "rollback_pending_claims",
                user=self.target_user.username,
            )
        self.assertIn("余额不足", str(cm.exception))

        pending_grant.refresh_from_db()
        self.assertTrue(pending_grant.is_claimed)

    def test_rollback_claimed_grants_dry_run(self):
        """Test dry-run only previews rollback and does not mutate data."""
        pending_grant = self._create_and_claim_grant(amount=5000)
        out = StringIO()

        call_command(
            "rollback_pending_claims",
            user=self.target_user.username,
            dry_run=True,
            stdout=out,
        )

        pending_grant.refresh_from_db()
        self.assertTrue(pending_grant.is_claimed)
        self.assertEqual(pending_grant.claimed_by, self.target_user)
        self.assertEqual(services.get_balance(self.target_user, PointType.GIFT), 5000)
        self.assertIn("预览模式", out.getvalue())


class RetriggerPendingPointClaimsCommandTests(TestCase):
    """Tests for retrigger_pending_point_claims management command."""

    def setUp(self):
        """Set up test fixtures."""
        self.granter = User.objects.create_user(username="granter", password="pass")

        services.grant_points(
            owner=self.granter,
            amount=100000,
            point_type=PointType.GIFT,
            reason="测试积分池",
        )
        source_pool = self.granter.point_wallet.sources.first()

        self.allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.granter.id,
            source_pool=source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

    def _create_pending_grant(self, user, amount=2000):
        return PendingPointGrant.objects.create(
            github_id="",
            github_login=user.username,
            email=user.email,
            amount=amount,
            point_type=PointType.GIFT,
            reason="测试待领取",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.granter.id,
            allocation=self.allocation,
        )

    def test_retrigger_single_user(self):
        """Test retriggering pending claim for a specific user."""
        user = User.objects.create_user(
            username="single-user",
            email="single@example.com",
            password="pass",
        )
        pending_grant = self._create_pending_grant(user, amount=3500)
        out = StringIO()

        call_command(
            "retrigger_pending_point_claims",
            user=user.username,
            stdout=out,
        )

        pending_grant.refresh_from_db()
        self.assertTrue(pending_grant.is_claimed)
        balance = services.get_balance(user, PointType.GIFT)
        self.assertEqual(balance, 3500)
        self.assertIn("处理完成", out.getvalue())

    def test_retrigger_all_only_handles_github_users_by_default(self):
        """Test --all only processes GitHub-linked users by default."""
        github_user = User.objects.create_user(
            username="github-user",
            email="github@example.com",
            password="pass",
        )
        UserSocialAuth.objects.create(
            user=github_user,
            provider="github",
            uid="10001",
        )

        non_github_user = User.objects.create_user(
            username="normal-user",
            email="normal@example.com",
            password="pass",
        )

        github_grant = self._create_pending_grant(github_user, amount=2000)
        normal_grant = self._create_pending_grant(non_github_user, amount=1800)

        call_command("retrigger_pending_point_claims", all=True)

        github_grant.refresh_from_db()
        normal_grant.refresh_from_db()
        self.assertTrue(github_grant.is_claimed)
        self.assertFalse(normal_grant.is_claimed)

    def test_retrigger_all_with_include_without_github(self):
        """Test --include-without-github processes all users."""
        github_user = User.objects.create_user(
            username="github-user-all",
            email="github-all@example.com",
            password="pass",
        )
        UserSocialAuth.objects.create(
            user=github_user,
            provider="github",
            uid="10002",
        )
        non_github_user = User.objects.create_user(
            username="normal-user-all",
            email="normal-all@example.com",
            password="pass",
        )

        github_grant = self._create_pending_grant(github_user, amount=2200)
        normal_grant = self._create_pending_grant(non_github_user, amount=2100)

        call_command(
            "retrigger_pending_point_claims",
            all=True,
            include_without_github=True,
        )

        github_grant.refresh_from_db()
        normal_grant.refresh_from_db()
        self.assertTrue(github_grant.is_claimed)
        self.assertTrue(normal_grant.is_claimed)

    def test_include_without_github_requires_all(self):
        """Test --include-without-github requires --all."""
        user = User.objects.create_user(
            username="target-user",
            email="target@example.com",
            password="pass",
        )

        with self.assertRaises(CommandError) as cm:
            call_command(
                "retrigger_pending_point_claims",
                user=user.username,
                include_without_github=True,
            )
        self.assertIn("--include-without-github 只能与 --all 一起使用", str(cm.exception))

    def test_retrigger_single_user_dry_run(self):
        """Test retrigger dry-run does not claim pending grants."""
        user = User.objects.create_user(
            username="dry-run-user",
            email="dry-run@example.com",
            password="pass",
        )
        pending_grant = self._create_pending_grant(user, amount=3200)
        out = StringIO()

        call_command(
            "retrigger_pending_point_claims",
            user=user.username,
            dry_run=True,
            stdout=out,
        )

        pending_grant.refresh_from_db()
        self.assertFalse(pending_grant.is_claimed)
        self.assertEqual(services.get_balance(user, PointType.GIFT), 0)
        self.assertIn("预览完成", out.getvalue())

    def test_get_target_users_all_prefetches_social_auth(self):
        """Test --all target queryset prefetches social_auth."""
        command = RetriggerPendingPointClaimsCommand()

        queryset = command._get_target_users(
            {"all": True, "user": None, "user_id": None},
            include_without_github=False,
        )

        self.assertIn("social_auth", queryset._prefetch_related_lookups)

    def test_get_target_users_all_with_include_without_github_prefetches_social_auth(
        self,
    ):
        """Test --all with include_without_github prefetches social_auth."""
        command = RetriggerPendingPointClaimsCommand()

        queryset = command._get_target_users(
            {"all": True, "user": None, "user_id": None},
            include_without_github=True,
        )

        self.assertIn("social_auth", queryset._prefetch_related_lookups)
