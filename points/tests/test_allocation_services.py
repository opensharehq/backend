"""Tests for allocation services."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from accounts.models import User
from points.allocation_services import AllocationService
from points.models import (
    PendingPointGrant,
    PointAllocation,
    PointSource,
    PointType,
    PointWallet,
    Tag,
    TagType,
)
from points.services import grant_points


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
        self.contribution_patcher = patch(
            "contributions.services.ContributionService.query_from_clickhouse",
            side_effect=Exception("ClickHouse unavailable"),
        )
        self.contribution_patcher.start()
        self.addCleanup(self.contribution_patcher.stop)

        # 创建测试用户
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com"
        )

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
        """Test basic allocation preview."""
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

        # 检查数据结构
        for item in preview:
            self.assertIn("github_login", item)
            self.assertIn("contribution_score", item)
            self.assertIn("calculated_points", item)
            self.assertIn("adjusted_points", item)
            self.assertIn("is_registered", item)

    def test_preview_allocation_with_adjustment_ratio(self):
        """Test allocation preview with global adjustment ratio."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=500000,  # 使用足够大的总额避免触发缩放
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
            adjustment_ratio=Decimal("0.5"),  # 减半
        )

        preview = AllocationService.preview_allocation(allocation)

        # 检查调整比例是否生效（至少一个贡献者的比例应该正确）
        for item in preview:
            # 如果没有单独调整，全局比例应该生效
            if (
                str(item.get("user_id") or item["github_login"])
                not in allocation.individual_adjustments
            ):
                expected_adjusted = int(item["calculated_points"] * 0.5)
                self.assertEqual(item["adjusted_points"], expected_adjusted)

    def test_preview_allocation_with_individual_adjustments(self):
        """Test allocation preview with individual adjustments."""
        # 使用用户ID作为key（因为是已注册用户）
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=500000,  # 使用足够大的总额避免触发缩放
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
            individual_adjustments={str(self.user.id): 10000},  # 用user_id作为key
        )

        preview = AllocationService.preview_allocation(allocation)

        # 检查单独调整是否生效
        found_adjusted = False
        for item in preview:
            if item.get("user_id") == self.user.id:
                self.assertEqual(item["adjusted_points"], 10000)
                found_adjusted = True
                break

        self.assertTrue(found_adjusted, "未找到被单独调整的用户")

    def test_preview_allocation_exceeds_total_amount(self):
        """Test allocation preview when total exceeds limit."""
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.user.id,
            source_pool=self.source_pool,
            total_amount=1000,  # 设置一个很小的总额
            project_scope={"tags": ["test-repo"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 12, 1),
        )

        preview = AllocationService.preview_allocation(allocation)

        # 检查总额是否被缩放到不超过限制
        total_points = sum(item["adjusted_points"] for item in preview)
        self.assertLessEqual(total_points, allocation.total_amount)

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

        initial_remaining = self.source_pool.remaining_amount
        result = AllocationService.execute_allocation(allocation)

        # 检查执行结果
        self.assertIn("success", result)
        self.assertIn("pending", result)
        self.assertIn("failed", result)
        self.assertIn("total_points", result)

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

        result = AllocationService.execute_allocation(allocation)

        # 检查是否创建了待领取记录
        pending_grants = PendingPointGrant.objects.filter(
            allocation=allocation, is_claimed=False
        )
        self.assertTrue(pending_grants.exists())
        self.assertEqual(pending_grants.count(), result["pending"])

    def test_claim_pending_points(self):
        """Test claiming pending points."""
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
            github_id="123456",
            github_login="newuser",
            email="newuser@example.com",
            amount=5000,
            point_type=PointType.GIFT,
            reason="测试待领取",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
        )

        # 创建新用户并领取
        new_user = User.objects.create_user(
            username="newuser", email="newuser@example.com"
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

    def test_claim_pending_points_no_match(self):
        """Test claiming pending points with no matches."""
        new_user = User.objects.create_user(
            username="nomatch", email="nomatch@example.com"
        )

        result = AllocationService.claim_pending_points(new_user)

        # 没有匹配的待领取记录
        self.assertEqual(result["claimed_count"], 0)
        self.assertEqual(result["total_amount"], 0)

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

        PendingPointGrant.objects.create(
            github_id="",
            github_login=self.user.username,
            email="",
            amount=3000,
            point_type=PointType.GIFT,
            reason="按用户名匹配",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
        )
        PendingPointGrant.objects.create(
            github_id="",
            github_login="",
            email=self.user.email,
            amount=2000,
            point_type=PointType.GIFT,
            reason="按邮箱匹配",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
        )
        PendingPointGrant.objects.create(
            github_id="",
            github_login="other-user",
            email="other@example.com",
            amount=9999,
            point_type=PointType.GIFT,
            reason="不匹配",
            granter_type=ContentType.objects.get_for_model(User),
            granter_id=self.user.id,
            allocation=allocation,
        )

        summary = AllocationService.get_claimable_pending_points_summary(self.user)

        self.assertEqual(summary["claimable_count"], 2)
        self.assertEqual(summary["total_amount"], 5000)

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
            github_id="",
            github_login="",
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
