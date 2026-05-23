"""Tests for allocation services."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.db import connection, models
from django.test import TestCase
from django.utils import timezone
from social_django.models import UserSocialAuth

from accounts.models import User
from contributions.services import ContributionDataUnavailableError
from points.allocation_services import AllocationService
from points.models import (
    AllocationStatus,
    PendingPointGrant,
    PointAllocation,
    PointSource,
    PointType,
    PointWallet,
    Tag,
    TagType,
)
from points.services import get_balance, grant_points


class AllocationServiceTests(TestCase):
    """Tests for allocation service."""

    def setUp(self):
        """Set up test data."""

        def fake_project_tags(tags, operation="AND"):
            return {"repo:github:1"} if tags else set()

        self.tag_operation_patcher = patch(
            "points.tag_operations.TagOperation.evaluate_project_tags",
            side_effect=fake_project_tags,
        )
        self.tag_operation_patcher.start()
        self.addCleanup(self.tag_operation_patcher.stop)

        # 创建测试用户
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com"
        )

        self.mock_contributions = [
            {
                "platform": "GitHub",
                "actor_id": "123456",
                "actor_login": self.user.username,
                "email": self.user.email,
                "contribution_score": Decimal("100.0"),
                "is_registered": True,
                "user_id": self.user.id,
            },
            {
                "platform": "GitHub",
                "actor_id": "654321",
                "actor_login": "external-contributor",
                "email": "external@example.com",
                "contribution_score": Decimal("50.0"),
                "is_registered": False,
                "user_id": None,
            },
        ]
        self.contribution_patcher = patch(
            "points.allocation_services.ContributionService.get_contributions",
            return_value=self.mock_contributions,
        )
        self.contribution_patcher.start()
        self.addCleanup(self.contribution_patcher.stop)

        # 创建钱包
        self.wallet = PointWallet.objects.create(
            content_type=ContentType.objects.get_for_model(User),
            object_id=self.user.id,
        )

        # 给用户发放积分，创建积分池
        grant_points(
            owner=self.user,
            amount=100000,
            point_type=PointType.GIFT,
            reason="测试积分",
        )

        self.source_pool = PointSource.objects.filter(wallet=self.wallet).first()

        # 创建标签
        self.tag_org = Tag.objects.create(
            name="测试组织",
            slug="test-org",
            tag_type=TagType.ORG,
            entity_identifier="test",
            is_official=True,
        )

        self.tag_repo = Tag.objects.create(
            name="测试仓库",
            slug="test-repo",
            tag_type=TagType.REPO,
            entity_identifier="test/project",
            is_official=True,
        )

    def test_preview_allocation_basic(self):
        """Test basic allocation preview returns contribution data only."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        preview = AllocationService.preview_allocation(allocation)

        # 应该返回一些贡献者
        self.assertTrue(len(preview) > 0)

        # 检查数据结构 - preview 仅返回原始贡献度数据
        for item in preview:
            self.assertIn("actor_login", item)
            self.assertIn("contribution_score", item)
            self.assertIn("is_registered", item)
            # preview 不再包含 calculated_points 和 adjusted_points
            self.assertNotIn("calculated_points", item)
            self.assertNotIn("adjusted_points", item)

    def test_preview_allocation_raises_when_contribution_data_is_unavailable(self):
        """Test contribution backend failures propagate as structured availability errors."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        with (
            patch(
                "points.allocation_services.ContributionService.get_contributions",
                side_effect=ContributionDataUnavailableError(
                    "Contribution data is currently unavailable."
                ),
            ),
            self.assertRaises(ContributionDataUnavailableError),
        ):
            AllocationService.preview_allocation(allocation)

    def test_preview_allocation_ignores_adjustment_ratio(self):
        """Test preview no longer applies adjustment ratio - returns raw scores."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=500000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
            adjustment_ratio=Decimal("0.5"),
        )

        preview = AllocationService.preview_allocation(allocation)

        # Preview 不再应用调整比例，仅返回原始 contribution_score
        for item in preview:
            self.assertIn("contribution_score", item)
            self.assertNotIn("calculated_points", item)
            self.assertNotIn("adjusted_points", item)

    def test_preview_allocation_ignores_individual_adjustments(self):
        """Test preview no longer applies individual adjustments."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=500000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
            individual_adjustments={str(self.user.id): 10000},
        )

        preview = AllocationService.preview_allocation(allocation)

        # Preview 不再应用单独调整，仅返回原始数据
        for item in preview:
            self.assertNotIn("adjusted_points", item)
            self.assertIn("contribution_score", item)

    def test_preview_allocation_no_longer_scales_to_total_amount(self):
        """Test preview does not scale results - returns raw contribution scores."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=1000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        preview = AllocationService.preview_allocation(allocation)

        # Preview 不再缩放，仅返回原始 contribution_score
        for item in preview:
            self.assertNotIn("adjusted_points", item)
            self.assertIn("contribution_score", item)

    def test_execute_allocation_to_registered_users(self):
        """Test executing allocation to registered users."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        allocations_data = [
            {
                "platform": "GitHub",
                "actor_id": "123456",
                "actor_login": self.user.username,
                "email": self.user.email,
                "contribution_score": 100.0,
                "is_registered": True,
                "user_id": self.user.id,
                "amount": 30000,
            },
            {
                "platform": "GitHub",
                "actor_id": "654321",
                "actor_login": "external-contributor",
                "email": "external@example.com",
                "contribution_score": 50.0,
                "is_registered": False,
                "user_id": None,
                "amount": 20000,
            },
        ]

        initial_remaining = self.source_pool.remaining_amount
        result = AllocationService.execute_allocation(allocation, allocations_data)

        # 检查执行结果
        self.assertIn("success", result)
        self.assertIn("pending", result)
        self.assertIn("failed", result)
        self.assertIn("total_points", result)
        self.assertEqual(result["total_points"], 50000)

        # 检查分配记录状态
        allocation.refresh_from_db()
        self.assertEqual(allocation.status, "completed")
        self.assertIsNotNone(allocation.executed_at)
        self.assertTrue(len(allocation.contribution_data) > 0)

        # 检查积分池余额扣减
        self.source_pool.refresh_from_db()
        self.assertEqual(
            self.source_pool.remaining_amount,
            initial_remaining - result["total_points"],
        )

    def test_execute_allocation_creates_pending_grants(self):
        """Test that executing allocation creates pending grants for unregistered users."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        allocations_data = [
            {
                "platform": "GitHub",
                "actor_id": "123456",
                "actor_login": self.user.username,
                "email": self.user.email,
                "contribution_score": 100.0,
                "is_registered": True,
                "user_id": self.user.id,
                "amount": 30000,
            },
            {
                "platform": "GitHub",
                "actor_id": "654321",
                "actor_login": "external-contributor",
                "email": "external@example.com",
                "contribution_score": 50.0,
                "is_registered": False,
                "user_id": None,
                "amount": 20000,
            },
        ]

        result = AllocationService.execute_allocation(allocation, allocations_data)

        # 检查是否创建了待领取记录
        pending_grants = PendingPointGrant.objects.filter(
            allocation=allocation, is_claimed=False
        )
        self.assertTrue(pending_grants.exists())
        self.assertEqual(pending_grants.count(), result["pending"])
        self.assertEqual(pending_grants.first().amount, 20000)

    def test_claim_pending_points(self):
        """Test claiming pending points."""
        # 创建新用户并绑定社交账号（先于待领取记录创建，避免信号自动认领）
        new_user = User.objects.create_user(
            username="newuser", email="newuser@example.com"
        )
        UserSocialAuth.objects.create(user=new_user, provider="github", uid="123456")

        # 创建待领取记录
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        pending_grant = PendingPointGrant.objects.create(
            platform="github",
            actor_id="123456",
            actor_login="newuser",
            email="newuser@example.com",
            amount=5000,
            point_type=PointType.GIFT,
            reason="测试待领取",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
        )

        result = AllocationService.claim_pending_points(new_user)

        # 检查领取结果
        self.assertEqual(result["claimed_count"], 1)
        self.assertEqual(result["total_amount"], 5000)

        # 检查待领取记录状态
        pending_grant.refresh_from_db()
        self.assertTrue(pending_grant.is_claimed)
        self.assertEqual(pending_grant.claimed_by, new_user)
        self.assertIsNotNone(pending_grant.claimed_at)

    def test_claim_pending_grant_uses_atomic_claim_guard(self):
        """Test only one stale grant snapshot can claim the same pending record."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        pending_grant = PendingPointGrant.objects.create(
            platform="github",
            actor_id="123456",
            actor_login="race-user",
            email="race-user@example.com",
            amount=4200,
            point_type=PointType.GIFT,
            reason="并发领取测试",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
        )
        claimant = User.objects.create_user(
            username="race-user",
            email="race-user@example.com",
        )

        stale_grant_1 = PendingPointGrant.objects.get(id=pending_grant.id)
        stale_grant_2 = PendingPointGrant.objects.get(id=pending_grant.id)

        with patch("points.allocation_services.grant_points") as grant_points_mock:
            first_amount = AllocationService._claim_pending_grant(
                claimant, stale_grant_1
            )
            second_amount = AllocationService._claim_pending_grant(
                claimant, stale_grant_2
            )

        self.assertEqual(first_amount, 4200)
        self.assertEqual(second_amount, 0)
        grant_points_mock.assert_called_once()

        pending_grant.refresh_from_db()
        self.assertTrue(pending_grant.is_claimed)
        self.assertEqual(pending_grant.claimed_by, claimant)
        self.assertIsNotNone(pending_grant.claimed_at)

    def test_claim_pending_points_rolls_back_claim_flag_on_grant_failure(self):
        """Test claim flag is rolled back if grant_points fails inside transaction."""
        # 先创建用户和 social_auth，避免信号自动认领
        claimant = User.objects.create_user(
            username="rollback-user",
            email="rollback-user@example.com",
        )
        UserSocialAuth.objects.create(user=claimant, provider="github", uid="123456")

        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        pending_grant = PendingPointGrant.objects.create(
            platform="github",
            actor_id="123456",
            actor_login="rollback-user",
            email="rollback-user@example.com",
            amount=2600,
            point_type=PointType.GIFT,
            reason="失败回滚测试",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
        )

        with (
            patch(
                "points.allocation_services.grant_points",
                side_effect=RuntimeError("grant failed"),
            ),
            self.assertLogs("points.allocation_services", level="ERROR") as cm,
        ):
            result = AllocationService.claim_pending_points(claimant)

        self.assertEqual(result["claimed_count"], 0)
        self.assertEqual(result["total_amount"], 0)
        self.assertEqual(len(cm.output), 1)
        self.assertIn("Failed to claim pending grant", cm.output[0])

        pending_grant.refresh_from_db()
        self.assertFalse(pending_grant.is_claimed)
        self.assertIsNone(pending_grant.claimed_by)
        self.assertIsNone(pending_grant.claimed_at)

    def test_claim_pending_points_no_match(self):
        """Test claiming pending points with no matches."""
        new_user = User.objects.create_user(
            username="nomatch", email="nomatch@example.com"
        )

        result = AllocationService.claim_pending_points(new_user)

        # 没有匹配的待领取记录
        self.assertEqual(result["claimed_count"], 0)
        self.assertEqual(result["total_amount"], 0)

    def test_claim_pending_points_skips_zero_amount_results_and_continues(self):
        """Zero-amount claim results should be ignored while later claims still count."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        claimant = User.objects.create_user(
            username="continued-claim-user",
            email="continued-claim@example.com",
        )
        UserSocialAuth.objects.create(user=claimant, provider="github", uid="cont-uid")
        for amount in (1000, 1800):
            PendingPointGrant.objects.create(
                platform="github",
                actor_id="cont-uid",
                actor_login=claimant.username,
                email=claimant.email,
                amount=amount,
                point_type=PointType.GIFT,
                reason="continue on zero claim",
                granter_type=ContentType.objects.get_for_model(User),
                granter_id=self.user.id,
                allocation=allocation,
            )

        with patch.object(
            AllocationService,
            "_claim_pending_grant",
            side_effect=[0, 1800],
        ):
            result = AllocationService.claim_pending_points(claimant)

        self.assertEqual(result, {"claimed_count": 1, "total_amount": 1800})

    def test_get_claimable_pending_points_summary(self):
        """Test claimable pending points summary returns count and total."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        UserSocialAuth.objects.create(
            user=self.user, provider="github", uid="777888"
        )

        PendingPointGrant.objects.create(
            platform="github",
            actor_id="777888",
            actor_login=self.user.username,
            email="",
            amount=3000,
            point_type=PointType.GIFT,
            reason="按 actor_id 匹配",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
        )
        PendingPointGrant.objects.create(
            platform="github",
            actor_id="",
            actor_login="",
            email=self.user.email,
            amount=2000,
            point_type=PointType.GIFT,
            reason="仅邮箱匹配（已下线兜底，不应被认领）",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
        )
        PendingPointGrant.objects.create(
            platform="github",
            actor_id="",
            actor_login="other-user",
            email="other@example.com",
            amount=9999,
            point_type=PointType.GIFT,
            reason="不匹配",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
        )

        summary = AllocationService.get_claimable_pending_points_summary(self.user)

        self.assertEqual(summary["claimable_count"], 1)
        self.assertEqual(summary["total_amount"], 3000)

    def test_claim_pending_points_ignores_empty_identifiers(self):
        """Test empty user identifiers will not match all blank pending grants."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        pending_grant = PendingPointGrant.objects.create(
            platform="github",
            actor_id="",
            actor_login="",
            email="",
            amount=3000,
            point_type=PointType.GIFT,
            reason="空标识测试",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
        )

        user_with_empty_email = User.objects.create_user(
            username="freshuser",
            email="",
        )
        result = AllocationService.claim_pending_points(user_with_empty_email)

        self.assertEqual(result["claimed_count"], 0)
        self.assertEqual(result["total_amount"], 0)

        pending_grant.refresh_from_db()
        self.assertFalse(pending_grant.is_claimed)

    def test_build_pending_claim_query_uses_prefetched_github_social_auth(self):
        """Test pending claim query uses prefetched social auth without DB query."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        prefetched_user = User.objects.create_user(
            username="prefetched-user",
            email="prefetched-user@example.com",
        )
        setattr(
            prefetched_user,
            AllocationService.SOCIAL_AUTH_PREFETCH_ATTR,
            [SimpleNamespace(provider="github", uid="556677")],
        )

        PendingPointGrant.objects.create(
            platform="github",
            actor_id="556677",
            actor_login="someone-else",
            email="someone-else@example.com",
            amount=2600,
            point_type=PointType.GIFT,
            reason="按 actor_id 匹配",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
        )

        with self.assertNumQueries(0):
            query = AllocationService._build_pending_claim_query(prefetched_user)

        self.assertEqual(PendingPointGrant.objects.filter(query).count(), 1)

    def test_build_pending_claim_query_matches_prefetched_uid_zero(self):
        """Test prefetched uid=0 is treated as a valid identifier."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        prefetched_user = User.objects.create_user(
            username="uid-zero-user",
            email="uid-zero-user@example.com",
        )
        setattr(
            prefetched_user,
            AllocationService.SOCIAL_AUTH_PREFETCH_ATTR,
            [SimpleNamespace(provider="github", uid=0)],
        )

        PendingPointGrant.objects.create(
            platform="github",
            actor_id="0",
            actor_login="someone-else",
            email="someone-else@example.com",
            amount=1600,
            point_type=PointType.GIFT,
            reason="按 actor_id=0 匹配",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
        )

        with self.assertNumQueries(0):
            query = AllocationService._build_pending_claim_query(prefetched_user)

        self.assertEqual(PendingPointGrant.objects.filter(query).count(), 1)

    def test_rollback_claimed_points_uses_locked_balance_check(self):
        """Test rollback execution enables source locking during balance check."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        pending_grant = PendingPointGrant.objects.create(
            platform="github",
            actor_id="",
            actor_login=self.user.username,
            email=self.user.email,
            amount=1200,
            point_type=PointType.GIFT,
            reason="回退锁测试",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
            is_claimed=True,
            claimed_by=self.user,
            claimed_at=timezone.now(),
        )
        grant_points(
            owner=self.user,
            amount=1200,
            point_type=PointType.GIFT,
            reason="回退可用余额",
        )

        with patch.object(
            AllocationService,
            "_ensure_rollback_balance_sufficient",
            wraps=AllocationService._ensure_rollback_balance_sufficient,
        ) as ensure_mock:
            AllocationService.rollback_claimed_points_for_user(self.user)

        pending_grant.refresh_from_db()
        self.assertFalse(pending_grant.is_claimed)
        self.assertEqual(ensure_mock.call_count, 1)
        self.assertTrue(ensure_mock.call_args.kwargs["lock_sources"])

    def test_get_rollback_bucket_available_amount_keeps_unfiltered_gift_sources(self):
        """Gift lookups without tag filters should retain all positive sources."""
        grant_points(
            owner=self.user,
            amount=500,
            point_type=PointType.GIFT,
            reason="tagged gift source",
            tag_slug=self.tag_repo.slug,
        )

        available_amount = AllocationService._get_rollback_bucket_available_amount(
            self.wallet,
            point_type=PointType.GIFT,
            tag_slug=None,
            tag_is_null=False,
        )

        expected_amount = sum(
            source.remaining_amount
            for source in PointSource.objects.filter(
                wallet=self.wallet,
                point_type=PointType.GIFT,
                remaining_amount__gt=0,
            )
        )
        self.assertEqual(available_amount, expected_amount)

    def test_preview_allocation_empty_projects(self):
        """Test allocation preview with empty project tags."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": [], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        preview = AllocationService.preview_allocation(allocation)

        # 空项目范围应该返回空列表
        self.assertEqual(len(preview), 0)

    def test_get_project_identifiers_normalizes_values(self):
        """Test project tags are normalized before querying contributions."""
        allocation = SimpleNamespace(project_scope={"tags": [None, " ", " repo ", 123]})

        identifiers = AllocationService._get_project_identifiers(allocation)

        self.assertEqual(identifiers, ["repo", "123"])

    def test_filter_contributions_by_user_scope_matches_login_or_id(self):
        """Test user scope matches either actor_login or actor_id."""
        allocation = SimpleNamespace(user_scope={"tags": ["scope"], "operation": "AND"})
        contributions = [
            {"actor_login": "alice", "actor_id": "100"},
            {"actor_login": "bob", "actor_id": "200"},
            {"actor_login": "charlie", "actor_id": "300"},
        ]

        with patch(
            "points.allocation_services.TagOperation.evaluate_user_tags",
            return_value={"alice", "300"},
        ):
            filtered = AllocationService._filter_contributions_by_user_scope(
                allocation, contributions
            )

        self.assertEqual(filtered, [contributions[0], contributions[2]])

    def test_preview_allocation_returns_empty_after_user_scope_filter(self):
        """Test preview returns empty when user scope removes all contributions."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            user_scope={"tags": ["test-users"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )
        contributions = [
            {
                "actor_login": "alice",
                "actor_id": "100",
                "email": "alice@example.com",
                "contribution_score": Decimal("1.5"),
                "is_registered": False,
                "user_id": None,
            }
        ]

        with (
            patch.object(
                AllocationService, "_get_contributions", return_value=contributions
            ),
            patch(
                "points.allocation_services.TagOperation.evaluate_user_tags",
                return_value={"nobody"},
            ),
        ):
            preview = AllocationService.preview_allocation(allocation)

        self.assertEqual(preview, [])

    def test_preview_allocation_returns_empty_when_total_contribution_is_zero(self):
        """Test preview returns empty when total contribution sums to zero."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )
        contributions = [
            {
                "actor_login": "alice",
                "actor_id": "100",
                "email": "alice@example.com",
                "contribution_score": Decimal("0"),
                "is_registered": False,
                "user_id": None,
            }
        ]

        with patch.object(
            AllocationService, "_get_contributions", return_value=contributions
        ):
            preview = AllocationService.preview_allocation(allocation)

        self.assertEqual(preview, [])

    def test_scale_results_to_total_amount_preserves_exact_total_for_mixed_signs(
        self,
    ):
        """Scaling should still hit the target total when adjusted rows mix signs."""
        results = [
            {"adjusted_points": -10},
            {"adjusted_points": -3},
            {"adjusted_points": 20},
        ]

        AllocationService._scale_results_to_total_amount(results, total_amount=2)

        self.assertEqual(
            [item["adjusted_points"] for item in results],
            [-3, -1, 6],
        )
        self.assertEqual(sum(item["adjusted_points"] for item in results), 2)

    def test_scale_results_to_total_amount_raises_when_scaled_total_exceeds_target(
        self,
    ):
        """Scaling should assert if floor rounding ever overshoots the target total."""
        results = [
            {"adjusted_points": 2},
            {"adjusted_points": 1},
        ]

        with (
            patch("points.allocation_services.math.floor", side_effect=[2, 1]),
            self.assertRaisesMessage(
                AssertionError,
                "Scaled allocation exceeded the requested total amount.",
            ),
        ):
            AllocationService._scale_results_to_total_amount(results, total_amount=2)

    def test_scale_results_to_total_amount_raises_when_final_total_drifts(self):
        """Scaling should assert if remainder redistribution cannot hit the target."""
        results = [
            {"adjusted_points": 3},
            {"adjusted_points": 3},
        ]

        with (
            patch("points.allocation_services.math.floor", side_effect=[0, 0]),
            self.assertRaisesMessage(
                AssertionError,
                "Scaled allocation did not preserve the requested total amount.",
            ),
        ):
            AllocationService._scale_results_to_total_amount(results, total_amount=5)

    def test_execute_allocation_marks_failed_when_apply_raises(self):
        """Test execute_allocation marks allocation failed on unexpected errors."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        allocations_data = [
            {
                "platform": "GitHub",
                "actor_id": "123456",
                "actor_login": self.user.username,
                "email": self.user.email,
                "contribution_score": 100.0,
                "is_registered": True,
                "user_id": self.user.id,
                "amount": 50000,
            },
        ]

        with (
            self.assertRaises(RuntimeError),
            patch.object(
                AllocationService,
                "_apply_allocation_items",
                side_effect=RuntimeError("apply failed"),
            ),
            patch.object(
                AllocationService,
                "_mark_allocation_failed",
                wraps=AllocationService._mark_allocation_failed,
            ) as mark_failed_mock,
        ):
            AllocationService.execute_allocation(allocation, allocations_data)

        mark_failed_mock.assert_called_once_with(allocation)

    def test_execute_allocation_late_failure_rolls_back_side_effects(self):
        """Late failures should roll back grants and pending rows while persisting failed status."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=600,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )
        recipient = User.objects.create_user(
            username="late-failure-user",
            email="late-failure@example.com",
        )
        allocations_data = [
            {
                "platform": "GitHub",
                "actor_login": recipient.username,
                "actor_id": "1001",
                "email": recipient.email,
                "contribution_score": 1.0,
                "is_registered": True,
                "user_id": recipient.id,
                "amount": 300,
            },
            {
                "platform": "GitHub",
                "actor_login": "pending-late-failure",
                "actor_id": "1002",
                "email": "pending@example.com",
                "contribution_score": 1.0,
                "is_registered": False,
                "user_id": None,
                "amount": 300,
            },
        ]
        initial_balance = get_balance(recipient, PointType.GIFT)
        initial_remaining = self.source_pool.remaining_amount

        with (
            self.assertRaises(RuntimeError),
            patch.object(
                AllocationService,
                "_deduct_source_pool",
                side_effect=RuntimeError("deduct failed"),
            ),
        ):
            AllocationService.execute_allocation(allocation, allocations_data)

        allocation.refresh_from_db()
        self.assertEqual(allocation.status, "failed")
        self.assertEqual(get_balance(recipient, PointType.GIFT), initial_balance)
        self.assertFalse(
            PendingPointGrant.objects.filter(allocation=allocation).exists()
        )
        self.source_pool.refresh_from_db()
        self.assertEqual(self.source_pool.remaining_amount, initial_remaining)

    def test_execute_allocation_rejects_duplicate_execution(self):
        """The same allocation should not be executable twice."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=300,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )
        allocations_data = [
            {
                "actor_login": self.user.username,
                "actor_id": "123456",
                "platform": "GitHub",
                "email": self.user.email,
                "contribution_score": 1.0,
                "is_registered": True,
                "user_id": self.user.id,
                "amount": 300,
            }
        ]

        AllocationService.execute_allocation(allocation, allocations_data)
        with self.assertRaises(RuntimeError):
            AllocationService.execute_allocation(allocation, allocations_data)

    def test_mark_allocation_failed_only_transitions_from_executing(self):
        """Failed marking should not overwrite non-executing allocation states."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        AllocationService._mark_allocation_failed(allocation)

        allocation.refresh_from_db()
        self.assertEqual(allocation.status, AllocationStatus.DRAFT)

    def test_process_preview_item_skips_non_positive_amounts(self):
        """Test preview items with zero adjusted points are ignored."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        result = AllocationService._process_preview_item(
            allocation,
            {"adjusted_points": 0, "is_registered": True},
        )

        self.assertEqual(result, (0, 0, 0, 0))

    def test_process_preview_item_counts_failed_registered_grants(self):
        """Test failed registered grants increase the failure counter only."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )
        item = {"adjusted_points": 1200, "is_registered": True, "user_id": self.user.id}

        with patch.object(
            AllocationService, "_grant_registered_points", return_value=False
        ):
            result = AllocationService._process_preview_item(allocation, item)

        self.assertEqual(result, (0, 0, 1, 0))

    def test_deduct_source_pool_ignores_non_positive_amount(self):
        """Test source pool deduction is skipped when there is nothing to deduct."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        with patch("points.allocation_services.spend_points") as spend_points_mock:
            AllocationService._deduct_source_pool(allocation, 0)

        spend_points_mock.assert_not_called()

    def test_grant_registered_points_returns_false_when_grant_fails(self):
        """Test grant failures are converted into False for allocation stats."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        with (
            patch(
                "points.allocation_services.grant_points",
                side_effect=RuntimeError("grant failed"),
            ),
            self.assertLogs("points.allocation_services", level="ERROR") as cm,
        ):
            success = AllocationService._grant_registered_points(
                allocation,
                {"user_id": self.user.id},
                1200,
            )

        self.assertFalse(success)
        self.assertEqual(len(cm.output), 1)
        self.assertIn("Failed to grant points for allocation", cm.output[0])

    def test_build_pending_claim_query_without_identifiers_matches_nothing(self):
        """Test users without identifiers do not match blank pending grants."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )
        PendingPointGrant.objects.create(
            platform="github",
            actor_id="",
            actor_login="",
            email="",
            amount=3000,
            point_type=PointType.GIFT,
            reason="空标识测试",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
        )
        user = SimpleNamespace(username=" ", email=" ")
        setattr(user, AllocationService.SOCIAL_AUTH_PREFETCH_ATTR, [])

        query = AllocationService._build_pending_claim_query(user)

        self.assertEqual(PendingPointGrant.objects.filter(query).count(), 0)

    def test_claim_pending_points_retries_failed_claim_once(self):
        """A grant that fails once should remain claimable and succeed exactly once later."""
        # 先创建用户和 social_auth，避免信号自动认领
        claimant = User.objects.create_user(
            username="retry-user",
            email="retry-user@example.com",
        )
        UserSocialAuth.objects.create(user=claimant, provider="github", uid="retry-uid")

        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )
        pending_grant = PendingPointGrant.objects.create(
            platform="github",
            actor_id="retry-uid",
            actor_login="retry-user",
            email="retry-user@example.com",
            amount=3000,
            point_type=PointType.GIFT,
            reason="retry claim",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
        )

        with (
            patch(
                "points.allocation_services.grant_points",
                side_effect=RuntimeError("grant failed"),
            ),
            self.assertLogs("points.allocation_services", level="ERROR") as cm,
        ):
            failed_result = AllocationService.claim_pending_points(claimant)

        success_result = AllocationService.claim_pending_points(claimant)

        self.assertEqual(failed_result, {"claimed_count": 0, "total_amount": 0})
        self.assertEqual(success_result, {"claimed_count": 1, "total_amount": 3000})
        self.assertEqual(get_balance(claimant, PointType.GIFT), 3000)
        self.assertEqual(len(cm.output), 1)
        self.assertIn("Failed to claim pending grant", cm.output[0])
        pending_grant.refresh_from_db()
        self.assertTrue(pending_grant.is_claimed)
        self.assertEqual(pending_grant.claimed_by, claimant)

    def test_get_claimable_pending_points_summary_excludes_expired_grants(self):
        """Expired pending grants should not be included in claimable summaries."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )
        UserSocialAuth.objects.create(
            user=self.user, provider="github", uid="expire-uid"
        )
        PendingPointGrant.objects.create(
            platform="github",
            actor_id="expire-uid",
            actor_login=self.user.username,
            email=self.user.email,
            amount=1000,
            point_type=PointType.GIFT,
            reason="expired",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
            expires_at=timezone.now() - timezone.timedelta(days=1),
        )
        PendingPointGrant.objects.create(
            platform="github",
            actor_id="expire-uid",
            actor_login=self.user.username,
            email=self.user.email,
            amount=2000,
            point_type=PointType.GIFT,
            reason="active",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
            expires_at=timezone.now() + timezone.timedelta(days=1),
        )

        summary = AllocationService.get_claimable_pending_points_summary(self.user)

        self.assertEqual(summary, {"claimable_count": 1, "total_amount": 2000})

    def test_claim_pending_points_ignores_expired_grants(self):
        """Expired pending grants should not be claimed."""
        # 先创建用户和 social_auth，避免信号自动认领
        claimant = User.objects.create_user(
            username="expired-user",
            email="expired-user@example.com",
        )
        UserSocialAuth.objects.create(user=claimant, provider="github", uid="exp-uid")

        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )
        expired_grant = PendingPointGrant.objects.create(
            platform="github",
            actor_id="exp-uid",
            actor_login="expired-user",
            email="expired-user@example.com",
            amount=1000,
            point_type=PointType.GIFT,
            reason="expired",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
            expires_at=timezone.now() - timezone.timedelta(days=1),
        )
        active_grant = PendingPointGrant.objects.create(
            platform="github",
            actor_id="exp-uid",
            actor_login="expired-user",
            email="expired-user@example.com",
            amount=2000,
            point_type=PointType.GIFT,
            reason="active",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
            expires_at=timezone.now() + timezone.timedelta(days=1),
        )

        result = AllocationService.claim_pending_points(claimant)

        self.assertEqual(result, {"claimed_count": 1, "total_amount": 2000})
        self.assertEqual(get_balance(claimant, PointType.GIFT), 2000)
        expired_grant.refresh_from_db()
        active_grant.refresh_from_db()
        self.assertFalse(expired_grant.is_claimed)
        self.assertTrue(active_grant.is_claimed)

    def test_rollback_claimed_points_for_user_returns_zero_without_grants(self):
        """Test rollback is a no-op when there are no claimed grants."""
        result = AllocationService.rollback_claimed_points_for_user(self.user)

        self.assertEqual(result, {"rolled_back_count": 0, "total_amount": 0})

    def test_get_rollback_claimed_points_summary_returns_defaults_without_grants(self):
        """Test empty rollback summary reports safe defaults."""
        summary = AllocationService.get_rollback_claimed_points_summary(self.user)

        self.assertEqual(
            summary,
            {
                "rollbackable_count": 0,
                "total_amount": 0,
                "can_execute": True,
                "blocking_error": "",
            },
        )

    def test_get_rollback_target_grants_filters_by_grant_ids(self):
        """Test rollback targets can be restricted to specific grant IDs."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )
        first_grant = PendingPointGrant.objects.create(
            platform="github",
            actor_id="",
            actor_login=self.user.username,
            email=self.user.email,
            amount=1000,
            point_type=PointType.GIFT,
            reason="first",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
            is_claimed=True,
            claimed_by=self.user,
            claimed_at=timezone.now(),
        )
        PendingPointGrant.objects.create(
            platform="github",
            actor_id="",
            actor_login=self.user.username,
            email=self.user.email,
            amount=1200,
            point_type=PointType.GIFT,
            reason="second",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
            is_claimed=True,
            claimed_by=self.user,
            claimed_at=timezone.now(),
        )

        grants = AllocationService._get_rollback_target_grants(
            user=self.user,
            grant_ids=[first_grant.id],
        )

        self.assertEqual([grant.id for grant in grants], [first_grant.id])

    def test_get_rollback_target_grants_uses_select_for_update_of_when_supported(self):
        """Test rollback target locking uses OF syntax when the backend supports it."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )
        grant = PendingPointGrant.objects.create(
            platform="github",
            actor_id="",
            actor_login=self.user.username,
            email=self.user.email,
            amount=1500,
            point_type=PointType.GIFT,
            reason="lock test",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
            is_claimed=True,
            claimed_by=self.user,
            claimed_at=timezone.now(),
        )

        with patch.object(connection.features, "has_select_for_update_of", True):
            grants = AllocationService._get_rollback_target_grants(
                user=self.user,
                for_update=True,
            )

        self.assertEqual([item.id for item in grants], [grant.id])

    def test_rollback_claimed_points_for_user_is_atomic_on_mid_batch_failure(self):
        """If a later rollback step fails, earlier grant state changes must be rolled back."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=50000,
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )
        claimant = User.objects.create_user(
            username="atomic-rollback",
            email="atomic-rollback@example.com",
        )
        grant_points(
            owner=claimant,
            amount=1000,
            point_type=PointType.GIFT,
            reason="rollback source",
        )
        first_grant = PendingPointGrant.objects.create(
            platform="github",
            actor_id="",
            actor_login=claimant.username,
            email=claimant.email,
            amount=200,
            point_type=PointType.GIFT,
            reason="first rollback",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
            is_claimed=True,
            claimed_by=claimant,
            claimed_at=timezone.now(),
        )
        second_grant = PendingPointGrant.objects.create(
            platform="github",
            actor_id="",
            actor_login=claimant.username,
            email=claimant.email,
            amount=300,
            point_type=PointType.GIFT,
            reason="second rollback",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
            is_claimed=True,
            claimed_by=claimant,
            claimed_at=timezone.now(),
        )

        with patch(
            "points.allocation_services.spend_points",
            side_effect=[[], RuntimeError("rollback failed")],
        ):
            with self.assertRaises(RuntimeError):
                AllocationService.rollback_claimed_points_for_user(claimant)

        first_grant.refresh_from_db()
        second_grant.refresh_from_db()
        self.assertTrue(first_grant.is_claimed)
        self.assertTrue(second_grant.is_claimed)
        self.assertEqual(get_balance(claimant, PointType.GIFT), 1000)

    def test_ensure_rollback_balance_sufficient_supports_cash_and_tagged_buckets(self):
        """Test rollback balance checks handle cash and tagged gift buckets."""
        grant_points(
            owner=self.user,
            amount=500,
            point_type=PointType.CASH,
            reason="现金余额",
        )
        grant_points(
            owner=self.user,
            amount=800,
            point_type=PointType.GIFT,
            reason="标签余额",
            tag_slug=self.tag_repo.slug,
        )
        grants = [
            SimpleNamespace(point_type=PointType.CASH, tag=None, amount=200),
            SimpleNamespace(point_type=PointType.GIFT, tag=self.tag_repo, amount=300),
        ]

        AllocationService._ensure_rollback_balance_sufficient(self.user, grants)

    def test_scale_results_to_total_amount_preserves_positive_remainder(self):
        """Scaling should not collapse all positive allocations to zero."""
        results = [
            {"adjusted_points": 1},
            {"adjusted_points": 1},
            {"adjusted_points": 1},
        ]

        AllocationService._scale_results_to_total_amount(results, total_amount=1)

        self.assertEqual(sum(item["adjusted_points"] for item in results), 1)

    def test_scale_results_to_total_amount_returns_when_flooring_has_no_remainder(self):
        """Scaling should stop when floor-rounded values already hit the target total."""
        results = [
            {"adjusted_points": 4},
            {"adjusted_points": 2},
        ]

        AllocationService._scale_results_to_total_amount(results, total_amount=3)

        self.assertEqual([item["adjusted_points"] for item in results], [2, 1])


class AllocationServiceThinIntegrationTests(TestCase):
    """Integration-oriented allocation tests without global service patches."""

    def setUp(self):
        self.initiator = User.objects.create_user(
            username="thin-initiator",
            email="thin-initiator@example.com",
        )
        self.user_ct = ContentType.objects.get_for_model(User)
        self.repo_tag = Tag.objects.create(
            name="thin-repo-tag",
            slug="thin-repo-tag",
            tag_type=TagType.REPO,
            entity_identifier="acme/repo",
            is_official=True,
        )
        self.cash_source_pool = grant_points(
            owner=self.initiator,
            amount=5000,
            point_type=PointType.CASH,
            reason="thin cash pool",
        )
        self.gift_tagged_source_pool = grant_points(
            owner=self.initiator,
            amount=5000,
            point_type=PointType.GIFT,
            reason="thin tagged gift pool",
            tag_slug=self.repo_tag.slug,
        )
        self.gift_untagged_source_pool = grant_points(
            owner=self.initiator,
            amount=5000,
            point_type=PointType.GIFT,
            reason="thin untagged gift pool",
        )

    def _create_allocation(self, *, source_pool, total_amount=1200):
        return PointAllocation.objects.create(
            initiator_type=self.user_ct,
            initiator_id=self.initiator.id,
            source_pool=source_pool,
            total_amount=total_amount,
            project_scope={"tags": ["repo:github:acme/repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 1, 1),
        )

    def _create_registered_contributor(self, *, uid="9001", username="registered-thin"):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
        )
        UserSocialAuth.objects.create(user=user, provider="github", uid=str(uid))
        return user

    def test_preview_allocation_uses_contribution_service_success_path(self):
        """Preview should flow through ContributionService enrichment logic."""
        registered = self._create_registered_contributor(uid="9001")
        allocation = self._create_allocation(source_pool=self.cash_source_pool)

        with patch(
            "chdb.services.query_contributions",
            return_value=[
                {
                    "platform": "GitHub",
                    "actor_id": "9001",
                    "actor_login": registered.username,
                    "contribution_score": 2.0,
                },
                {
                    "platform": "GitHub",
                    "actor_id": 7002,
                    "actor_login": "pending-thin",
                    "contribution_score": 1.0,
                },
            ],
        ) as query_mock:
            preview = AllocationService.preview_allocation(allocation)

        query_mock.assert_called_once_with(
            label_ids=["repo:github:acme/repo"],
            start_month=202401,
            end_month=202401,
        )
        self.assertEqual(len(preview), 2)
        by_login = {item["actor_login"]: item for item in preview}
        self.assertTrue(by_login[registered.username]["is_registered"])
        self.assertEqual(by_login[registered.username]["user_id"], registered.id)
        self.assertFalse(by_login["pending-thin"]["is_registered"])
        self.assertIsNone(by_login["pending-thin"]["user_id"])
        # Preview 不再返回 calculated_points/adjusted_points
        self.assertNotIn("adjusted_points", by_login[registered.username])
        self.assertNotIn("calculated_points", by_login[registered.username])
        # 仅返回原始 contribution_score
        self.assertIn("contribution_score", by_login[registered.username])
        self.assertIn("contribution_score", by_login["pending-thin"])

    def test_execute_allocation_handles_registered_and_pending_recipients(self):
        """Execute should grant registered users and create pending grants together."""
        registered = self._create_registered_contributor(uid="9002")
        allocation = self._create_allocation(
            source_pool=self.cash_source_pool,
            total_amount=900,
        )
        initial_source_remaining = self.cash_source_pool.remaining_amount

        allocations_data = [
            {
                "platform": "GitHub",
                "actor_id": "9002",
                "actor_login": registered.username,
                "email": registered.email,
                "contribution_score": 2.0,
                "is_registered": True,
                "user_id": registered.id,
                "amount": 600,
            },
            {
                "platform": "GitHub",
                "actor_id": "9003",
                "actor_login": "pending-recipient-thin",
                "email": "",
                "contribution_score": 1.0,
                "is_registered": False,
                "user_id": None,
                "amount": 300,
            },
        ]

        result = AllocationService.execute_allocation(allocation, allocations_data)

        self.assertEqual(
            result,
            {"success": 1, "pending": 1, "failed": 0, "total_points": 900},
        )
        allocation.refresh_from_db()
        self.assertEqual(allocation.status, "completed")
        self.assertEqual(allocation.registered_recipients, 1)
        self.assertEqual(allocation.unregistered_recipients, 1)
        self.assertEqual(get_balance(registered, PointType.CASH), 600)

        pending_grants = PendingPointGrant.objects.filter(
            allocation=allocation,
            is_claimed=False,
            actor_login="pending-recipient-thin",
        )
        self.assertEqual(pending_grants.count(), 1)
        self.assertEqual(pending_grants.first().amount, 300)

        self.cash_source_pool.refresh_from_db()
        self.assertEqual(
            self.cash_source_pool.remaining_amount,
            initial_source_remaining - 900,
        )

    def test_claim_pending_points_with_multiple_identifiers_no_double_claim(self):
        """A pending grant matching multiple identifiers should still be claimed once."""
        allocation = self._create_allocation(source_pool=self.gift_untagged_source_pool)
        claimant = User.objects.create_user(
            username="multi-identity-claimer",
            email="multi-identity-claimer@example.com",
        )
        UserSocialAuth.objects.create(
            user=claimant,
            provider="github",
            uid="claim-uid-1",
        )

        matching_grants = [
            PendingPointGrant.objects.create(
                platform="github",
                actor_id="claim-uid-1",
                actor_login="someone-else",
                email="x@example.com",
                amount=100,
                point_type=PointType.GIFT,
                reason="match by actor_id",
                granter_type=self.user_ct,
                granter_id=self.initiator.id,
                allocation=allocation,
            ),
            PendingPointGrant.objects.create(
                platform="github",
                actor_id="claim-uid-1",
                actor_login=claimant.username,
                email=claimant.email,
                amount=400,
                point_type=PointType.GIFT,
                reason="match by actor_id (all identifiers present)",
                granter_type=self.user_ct,
                granter_id=self.initiator.id,
                allocation=allocation,
            ),
        ]
        email_only_grants = [
            PendingPointGrant.objects.create(
                platform="github",
                actor_id="",
                actor_login=claimant.username,
                email=claimant.email,
                amount=200,
                point_type=PointType.GIFT,
                reason="email only (no longer matches after email fallback removal)",
                granter_type=self.user_ct,
                granter_id=self.initiator.id,
                allocation=allocation,
            ),
            PendingPointGrant.objects.create(
                platform="github",
                actor_id="",
                actor_login="",
                email=claimant.email,
                amount=300,
                point_type=PointType.GIFT,
                reason="email only",
                granter_type=self.user_ct,
                granter_id=self.initiator.id,
                allocation=allocation,
            ),
        ]
        non_matching = PendingPointGrant.objects.create(
            platform="github",
            actor_id="other-uid",
            actor_login="other-login",
            email="other@example.com",
            amount=999,
            point_type=PointType.GIFT,
            reason="no match",
            granter_type=self.user_ct,
            granter_id=self.initiator.id,
            allocation=allocation,
        )

        result = AllocationService.claim_pending_points(claimant)

        self.assertEqual(result["claimed_count"], 2)
        self.assertEqual(result["total_amount"], 500)
        self.assertEqual(get_balance(claimant, PointType.GIFT), 500)
        for grant in matching_grants:
            grant.refresh_from_db()
            self.assertTrue(grant.is_claimed)
            self.assertEqual(grant.claimed_by, claimant)
        for grant in email_only_grants:
            grant.refresh_from_db()
            self.assertFalse(grant.is_claimed)
        non_matching.refresh_from_db()
        self.assertFalse(non_matching.is_claimed)

    def test_rollback_claimed_points_for_user_supports_multiple_balance_buckets(self):
        """Rollback should deduct from cash, tagged gift, and untagged gift buckets."""
        claimant = User.objects.create_user(
            username="rollback-buckets",
            email="rollback-buckets@example.com",
        )
        allocation = self._create_allocation(source_pool=self.cash_source_pool)

        grant_points(
            owner=claimant,
            amount=500,
            point_type=PointType.CASH,
            reason="rollback cash balance",
        )
        grant_points(
            owner=claimant,
            amount=700,
            point_type=PointType.GIFT,
            reason="rollback tagged gift balance",
            tag_slug=self.repo_tag.slug,
        )
        grant_points(
            owner=claimant,
            amount=900,
            point_type=PointType.GIFT,
            reason="rollback untagged gift balance",
        )

        grants = [
            PendingPointGrant.objects.create(
                platform="github",
                actor_id="",
                actor_login=claimant.username,
                email=claimant.email,
                amount=200,
                point_type=PointType.CASH,
                reason="rollback cash",
                granter_type=self.user_ct,
                granter_id=self.initiator.id,
                allocation=allocation,
                is_claimed=True,
                claimed_by=claimant,
                claimed_at=timezone.now(),
            ),
            PendingPointGrant.objects.create(
                platform="github",
                actor_id="",
                actor_login=claimant.username,
                email=claimant.email,
                amount=300,
                point_type=PointType.GIFT,
                reason="rollback tagged gift",
                tag=self.repo_tag,
                granter_type=self.user_ct,
                granter_id=self.initiator.id,
                allocation=allocation,
                is_claimed=True,
                claimed_by=claimant,
                claimed_at=timezone.now(),
            ),
            PendingPointGrant.objects.create(
                platform="github",
                actor_id="",
                actor_login=claimant.username,
                email=claimant.email,
                amount=400,
                point_type=PointType.GIFT,
                reason="rollback untagged gift",
                granter_type=self.user_ct,
                granter_id=self.initiator.id,
                allocation=allocation,
                is_claimed=True,
                claimed_by=claimant,
                claimed_at=timezone.now(),
            ),
        ]

        result = AllocationService.rollback_claimed_points_for_user(claimant)

        self.assertEqual(result, {"rolled_back_count": 3, "total_amount": 900})
        self.assertEqual(get_balance(claimant, PointType.CASH), 300)
        self.assertEqual(
            get_balance(claimant, PointType.GIFT, tag_slug=self.repo_tag.slug),
            400,
        )
        wallet = PointWallet.objects.get(
            content_type=self.user_ct,
            object_id=claimant.id,
        )
        untagged_gift_balance = (
            PointSource.objects.filter(
                wallet=wallet,
                point_type=PointType.GIFT,
                tag__isnull=True,
                remaining_amount__gt=0,
            ).aggregate(total=models.Sum("remaining_amount"))["total"]
            or 0
        )
        self.assertEqual(untagged_gift_balance, 500)
        for grant in grants:
            grant.refresh_from_db()
            self.assertFalse(grant.is_claimed)
            self.assertIsNone(grant.claimed_by)
            self.assertIsNone(grant.claimed_at)

    def test_deduct_source_pool_passes_bucket_specific_parameters(self):
        """Deduction should pass tag parameters according to source bucket type."""
        cases = [
            (
                "cash",
                self.cash_source_pool,
                {
                    "point_type": PointType.CASH,
                    "tag_slug": None,
                    "tag_is_null": False,
                },
            ),
            (
                "gift-tagged",
                self.gift_tagged_source_pool,
                {
                    "point_type": PointType.GIFT,
                    "tag_slug": self.repo_tag.slug,
                    "tag_is_null": False,
                },
            ),
            (
                "gift-untagged",
                self.gift_untagged_source_pool,
                {"point_type": PointType.GIFT, "tag_slug": None, "tag_is_null": True},
            ),
        ]

        for _, source_pool, expected in cases:
            allocation = self._create_allocation(source_pool=source_pool)
            with patch("points.allocation_services.spend_points") as spend_points_mock:
                AllocationService._deduct_source_pool(allocation, 123)
            kwargs = spend_points_mock.call_args.kwargs
            self.assertEqual(kwargs["owner"], self.initiator)
            self.assertEqual(kwargs["amount"], 123)
            self.assertEqual(kwargs["point_type"], expected["point_type"])
            self.assertEqual(kwargs["tag_slug"], expected["tag_slug"])
            self.assertEqual(kwargs["tag_is_null"], expected["tag_is_null"])
            self.assertEqual(kwargs["reference_id"], f"allocation_{allocation.id}")

    def test_grant_registered_points_passes_bucket_specific_parameters(self):
        """Granting to registered users should preserve source bucket metadata."""
        recipient = User.objects.create_user(
            username="bucket-recipient",
            email="bucket-recipient@example.com",
        )
        cases = [
            ("cash", self.cash_source_pool, PointType.CASH, None),
            (
                "gift-tagged",
                self.gift_tagged_source_pool,
                PointType.GIFT,
                self.repo_tag.slug,
            ),
            ("gift-untagged", self.gift_untagged_source_pool, PointType.GIFT, None),
        ]

        for _, source_pool, expected_point_type, expected_tag_slug in cases:
            allocation = self._create_allocation(source_pool=source_pool)
            with patch("points.allocation_services.grant_points") as grant_points_mock:
                success = AllocationService._grant_registered_points(
                    allocation,
                    {"user_id": recipient.id},
                    456,
                )

            self.assertTrue(success)
            kwargs = grant_points_mock.call_args.kwargs
            self.assertEqual(kwargs["owner"], recipient)
            self.assertEqual(kwargs["amount"], 456)
            self.assertEqual(kwargs["point_type"], expected_point_type)
            self.assertEqual(kwargs["tag_slug"], expected_tag_slug)
            self.assertEqual(kwargs["reference_id"], f"allocation_{allocation.id}")
