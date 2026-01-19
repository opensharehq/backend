"""积分分配服务."""

import logging
from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from contributions.services import ContributionService

from .models import PendingPointGrant, PointAllocation
from .services import grant_points
from .tag_operations import TagOperation

logger = logging.getLogger(__name__)


class AllocationService:
    """积分分配服务."""

    CONTRIBUTION_TO_POINTS_RATIO = 300  # 1 贡献度 = 300 积分

    @staticmethod
    def preview_allocation(allocation: PointAllocation) -> list[dict]:
        """
        预览积分分配.

        Returns:
            [
                {
                    "github_login": "alice",
                    "github_id": "123",
                    "email": "alice@example.com",
                    "is_registered": True,
                    "user_id": 1,
                    "contribution_score": 250.5,
                    "calculated_points": 75150,
                    "adjusted_points": 75150
                },
                ...
            ]

        """
        projects = AllocationService._get_project_identifiers(allocation)
        if not projects:
            return []

        contributions = AllocationService._get_contributions(allocation, projects)
        contributions = AllocationService._filter_contributions_by_user_scope(
            allocation, contributions
        )
        if not contributions:
            return []

        total_contribution = AllocationService._total_contribution(contributions)
        if total_contribution == 0:
            return []

        results = AllocationService._build_preview_results(allocation, contributions)
        AllocationService._scale_results_to_total_amount(
            results, allocation.total_amount
        )

        return results

    @staticmethod
    @transaction.atomic
    def execute_allocation(allocation: PointAllocation) -> dict:
        """
        执行积分分配.

        Returns:
            {
                "success": 15,
                "pending": 5,
                "failed": 0,
                "total_points": 120000
            }

        """
        AllocationService._mark_allocation_executing(allocation)

        try:
            preview = AllocationService.preview_allocation(allocation)
            stats = AllocationService._apply_allocation_items(allocation, preview)
            AllocationService._finalize_allocation(allocation, preview, stats)
            return stats
        except Exception:
            AllocationService._mark_allocation_failed(allocation)
            raise

    @staticmethod
    def claim_pending_points(user) -> dict:
        """
        用户注册后自动领取待领取积分.

        Args:
            user: 用户对象

        Returns:
            {
                "claimed_count": 5,
                "total_amount": 12000
            }

        """
        pending_grants = PendingPointGrant.objects.filter(
            AllocationService._build_pending_claim_query(user)
        )

        claimed_count = 0
        total_amount = 0

        for grant in pending_grants:
            claimed_amount = AllocationService._claim_pending_grant(user, grant)
            if claimed_amount:
                claimed_count += 1
                total_amount += claimed_amount

        return {"claimed_count": claimed_count, "total_amount": total_amount}

    @staticmethod
    def _get_project_identifiers(allocation: PointAllocation) -> list[str]:
        projects = TagOperation.evaluate_project_tags(
            allocation.project_scope["tags"], allocation.project_scope["operation"]
        )
        return list(projects)

    @staticmethod
    def _get_contributions(
        allocation: PointAllocation, projects: list[str]
    ) -> list[dict]:
        return ContributionService.get_contributions(
            project_identifiers=projects,
            start_month=allocation.start_month,
            end_month=allocation.end_month,
        )

    @staticmethod
    def _filter_contributions_by_user_scope(
        allocation: PointAllocation, contributions: list[dict]
    ) -> list[dict]:
        if not allocation.user_scope:
            return contributions

        allowed_users = TagOperation.evaluate_user_tags(
            allocation.user_scope["tags"], allocation.user_scope["operation"]
        )
        return [
            c
            for c in contributions
            if c.get("github_login") in allowed_users
            or str(c.get("github_id")) in allowed_users
        ]

    @staticmethod
    def _total_contribution(contributions: list[dict]) -> float:
        return sum(float(c["contribution_score"]) for c in contributions)

    @staticmethod
    def _build_preview_results(
        allocation: PointAllocation, contributions: list[dict]
    ) -> list[dict]:
        return [
            AllocationService._build_preview_item(allocation, contrib)
            for contrib in contributions
        ]

    @staticmethod
    def _build_preview_item(allocation: PointAllocation, contrib: dict) -> dict:
        calculated = int(
            float(contrib["contribution_score"])
            * AllocationService.CONTRIBUTION_TO_POINTS_RATIO
        )
        adjusted = int(calculated * float(allocation.adjustment_ratio))

        user_key = contrib.get("user_id") or contrib["github_login"]
        override = allocation.individual_adjustments.get(str(user_key))
        if override is not None:
            adjusted = override

        return {
            **contrib,
            "calculated_points": calculated,
            "adjusted_points": adjusted,
        }

    @staticmethod
    def _scale_results_to_total_amount(results: list[dict], total_amount: int) -> None:
        total_points = sum(r["adjusted_points"] for r in results)
        if total_points <= total_amount:
            return

        scale = total_amount / total_points
        for result in results:
            result["adjusted_points"] = int(result["adjusted_points"] * scale)

    @staticmethod
    def _mark_allocation_executing(allocation: PointAllocation) -> None:
        allocation.status = "executing"
        allocation.save()

    @staticmethod
    def _mark_allocation_failed(allocation: PointAllocation) -> None:
        allocation.status = "failed"
        allocation.save()

    @staticmethod
    def _apply_allocation_items(
        allocation: PointAllocation, preview: list[dict]
    ) -> dict:
        success_count = 0
        pending_count = 0
        failed_count = 0
        total_points = 0

        for item in preview:
            success_inc, pending_inc, failed_inc, total_inc = (
                AllocationService._process_preview_item(allocation, item)
            )
            success_count += success_inc
            pending_count += pending_inc
            failed_count += failed_inc
            total_points += total_inc

        return {
            "success": success_count,
            "pending": pending_count,
            "failed": failed_count,
            "total_points": total_points,
        }

    @staticmethod
    def _process_preview_item(allocation: PointAllocation, item: dict) -> tuple:
        amount = item["adjusted_points"]
        if amount <= 0:
            return (0, 0, 0, 0)

        if item["is_registered"]:
            success = AllocationService._grant_registered_points(
                allocation, item, amount
            )
            if success:
                return (1, 0, 0, amount)
            return (0, 0, 1, amount)

        AllocationService._create_pending_grant(allocation, item, amount)
        return (0, 1, 0, amount)

    @staticmethod
    def _grant_registered_points(
        allocation: PointAllocation, item: dict, amount: int
    ) -> bool:
        try:
            from accounts.models import User

            user = User.objects.get(id=item["user_id"])
            grant_points(
                owner=user,
                amount=amount,
                point_type=allocation.source_pool.point_type,
                reason=(
                    f"贡献度奖励 ({allocation.start_month} - {allocation.end_month})"
                ),
                tag_slug=(
                    allocation.source_pool.tag.slug
                    if allocation.source_pool.tag
                    else None
                ),
                reference_id=f"allocation_{allocation.id}",
                created_by=None,
            )
        except Exception:
            logger.exception(
                "Failed to grant points for allocation %s to user %s",
                allocation.id,
                item.get("user_id"),
            )
            return False
        return True

    @staticmethod
    def _create_pending_grant(
        allocation: PointAllocation, item: dict, amount: int
    ) -> None:
        PendingPointGrant.objects.create(
            github_id=item.get("github_id", ""),
            github_login=item["github_login"],
            email=item.get("email", ""),
            amount=amount,
            point_type=allocation.source_pool.point_type,
            reason=(f"贡献度奖励 ({allocation.start_month} - {allocation.end_month})"),
            tag=allocation.source_pool.tag,
            reference_id=f"allocation_{allocation.id}",
            granter_type=allocation.initiator_type,
            granter_id=allocation.initiator_id,
            allocation=allocation,
        )

    @staticmethod
    def _finalize_allocation(
        allocation: PointAllocation, preview: list[dict], stats: dict
    ) -> None:
        allocation.status = "completed"
        allocation.executed_at = timezone.now()
        allocation.total_recipients = len(preview)
        allocation.registered_recipients = stats["success"]
        allocation.unregistered_recipients = stats["pending"]
        allocation.contribution_data = AllocationService._build_contribution_snapshot(
            preview
        )
        allocation.save()

    @staticmethod
    def _build_contribution_snapshot(preview: list[dict]) -> list[dict]:
        return [
            AllocationService._normalize_contribution_item(item) for item in preview
        ]

    @staticmethod
    def _normalize_contribution_item(item: dict) -> dict:
        item_copy = item.copy()
        contribution_score = item_copy.get("contribution_score")
        if isinstance(contribution_score, Decimal):
            item_copy["contribution_score"] = float(contribution_score)
        return item_copy

    @staticmethod
    def _build_pending_claim_query(user) -> models.Q:
        github_social = user.social_auth.filter(provider="github").first()
        github_id = github_social.uid if github_social else None

        query = models.Q(is_claimed=False)
        if github_id:
            return query & (
                models.Q(github_id=github_id)
                | models.Q(github_login=user.username)
                | models.Q(email=user.email)
            )

        return query & (
            models.Q(github_login=user.username) | models.Q(email=user.email)
        )

    @staticmethod
    def _claim_pending_grant(user, grant: PendingPointGrant) -> int:
        try:
            grant_points(
                owner=user,
                amount=grant.amount,
                point_type=grant.point_type,
                reason=grant.reason,
                tag_slug=grant.tag.slug if grant.tag else None,
                reference_id=grant.reference_id,
                created_by=None,
            )

            grant.is_claimed = True
            grant.claimed_by = user
            grant.claimed_at = timezone.now()
            grant.save()
        except Exception:
            logger.exception(
                "Failed to claim pending grant %s for user %s",
                grant.id,
                user.id,
            )
            return 0
        return grant.amount
