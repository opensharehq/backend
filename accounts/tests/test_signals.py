from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from social_django.models import UserSocialAuth

from accounts.signals import claim_pending_points_on_login
from points.models import PendingPointGrant, PointAllocation, PointType
from points.services import get_balance, grant_points

User = get_user_model()


class ClaimPendingPointsSignalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="signal-user", email="signal@example.com", password="testpass"
        )

    def _build_instance(self, provider="github"):
        return UserSocialAuth(user=self.user, provider=provider)

    @mock.patch("accounts.signals.logger.info")
    @mock.patch("points.allocation_services.AllocationService.claim_pending_points")
    def test_logs_claim_summary_when_grants_awarded(self, mock_claim, mock_logger):
        mock_claim.return_value = {"claimed_count": 2, "total_amount": 5000}
        social_auth = self._build_instance()

        claim_pending_points_on_login(UserSocialAuth, social_auth, created=True)

        mock_claim.assert_called_once_with(self.user)
        mock_logger.assert_called_once_with(
            "User %s claimed %d pending point grants totaling %d points",
            self.user.username,
            2,
            5000,
        )

    @mock.patch("accounts.signals.logger.info")
    @mock.patch("points.allocation_services.AllocationService.claim_pending_points")
    def test_skips_logging_when_no_grants(self, mock_claim, mock_logger):
        mock_claim.return_value = {"claimed_count": 0, "total_amount": 0}
        social_auth = self._build_instance()

        claim_pending_points_on_login(UserSocialAuth, social_auth, created=True)

        mock_logger.assert_not_called()


class ClaimPendingPointsSignalIntegrationTests(TestCase):
    """Exercise the real post-save signal against pending grants."""

    def setUp(self):
        self.source = User.objects.create_user(
            username="grant-source",
            email="grant-source@example.com",
            password="testpass123",
        )
        self.claimant = User.objects.create_user(
            username="claimed-user",
            email="claimed-user@example.com",
            password="testpass123",
        )
        self.source_pool = grant_points(
            self.source,
            5000,
            PointType.CASH,
            "Seed allocation pool",
            created_by=self.source,
        )
        source_type = ContentType.objects.get_for_model(self.source)
        self.allocation = PointAllocation.objects.create(
            initiator_type=source_type,
            initiator_id=self.source.id,
            source_pool=self.source_pool,
            total_amount=1200,
            project_scope={"tags": ["demo/project"], "operation": "AND"},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 1, 1),
        )

    def test_social_auth_creation_claims_matching_pending_grant(self):
        grant = PendingPointGrant.objects.create(
            platform="github",
            actor_id="123456",
            actor_login=self.claimant.username,
            email=self.claimant.email,
            amount=800,
            point_type=PointType.CASH,
            reason="Pending allocation reward",
            granter_type=ContentType.objects.get_for_model(self.source),
            granter_id=self.source.id,
            allocation=self.allocation,
        )

        UserSocialAuth.objects.create(
            user=self.claimant,
            provider="github",
            uid="123456",
        )

        grant.refresh_from_db()
        self.assertTrue(grant.is_claimed)
        self.assertEqual(grant.claimed_by, self.claimant)
        self.assertIsNotNone(grant.claimed_at)
        self.assertEqual(get_balance(self.claimant, PointType.CASH), 800)

    def test_gitee_social_auth_claims_pending_grant(self):
        """Gitee 用户绑定账号时能认领对应平台的待领取积分"""
        grant = PendingPointGrant.objects.create(
            platform="gitee",
            actor_id="99999",
            actor_login="gitee_user",
            amount=500,
            point_type=PointType.CASH,
            reason="Gitee contribution reward",
            granter_type=ContentType.objects.get_for_model(self.source),
            granter_id=self.source.id,
            allocation=self.allocation,
        )
        UserSocialAuth.objects.create(
            user=self.claimant,
            provider="gitee",
            uid="99999",
        )
        grant.refresh_from_db()
        assert grant.is_claimed is True
        assert grant.claimed_by == self.claimant

    def test_cross_platform_no_mismatch(self):
        """GitHub 用户不应认领 Gitee 平台的同名/同ID待领取积分"""
        grant = PendingPointGrant.objects.create(
            platform="gitee",
            actor_id="123456",  # 与 GitHub uid 相同但平台不同
            actor_login="same_name",
            amount=300,
            point_type=PointType.CASH,
            reason="Cross platform test",
            granter_type=ContentType.objects.get_for_model(self.source),
            granter_id=self.source.id,
            allocation=self.allocation,
        )
        # 绑定 GitHub 账号（不是 Gitee）
        UserSocialAuth.objects.create(
            user=self.claimant,
            provider="github",
            uid="123456",
        )
        grant.refresh_from_db()
        assert grant.is_claimed is False  # 不应被认领

    def test_multi_platform_claims_all_matching(self):
        """用户绑定多个平台账号后能认领所有匹配平台的待领取积分"""
        # 创建两个不同平台的待领取记录
        grant_gh = PendingPointGrant.objects.create(
            platform="github",
            actor_id="111",
            actor_login="user1",
            amount=100,
            point_type=PointType.CASH,
            reason="GH reward",
            granter_type=ContentType.objects.get_for_model(self.source),
            granter_id=self.source.id,
            allocation=self.allocation,
        )
        grant_gitee = PendingPointGrant.objects.create(
            platform="gitee",
            actor_id="222",
            actor_login="user1",
            amount=200,
            point_type=PointType.CASH,
            reason="Gitee reward",
            granter_type=ContentType.objects.get_for_model(self.source),
            granter_id=self.source.id,
            allocation=self.allocation,
        )
        # 绑定 GitHub
        UserSocialAuth.objects.create(user=self.claimant, provider="github", uid="111")
        grant_gh.refresh_from_db()
        assert grant_gh.is_claimed is True

        # 绑定 Gitee
        UserSocialAuth.objects.create(user=self.claimant, provider="gitee", uid="222")
        grant_gitee.refresh_from_db()
        assert grant_gitee.is_claimed is True
