"""积分分配服务."""

import logging
from decimal import Decimal

from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone

from contributions.services import ContributionService

from .models import PendingPointGrant, PointAllocation, PointSource, PointType
from .services import (
    InsufficientPointsError,
    get_wallet_or_none,
    grant_points,
    spend_points,
)
from .tag_operations import TagOperation

logger = logging.getLogger(__name__)


class AllocationService:
    """积分分配服务."""

    CONTRIBUTION_TO_POINTS_RATIO = 300  # 1 贡献度 = 300 积分
    GITHUB_SOCIAL_AUTH_PREFETCH_ATTR = "prefetched_github_social_auth"

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
            AllocationService._deduct_source_pool(allocation, stats["total_points"])
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
    def get_claimable_pending_points_summary(user) -> dict:
        """获取用户当前可领取的待领取积分汇总."""
        pending_grants = PendingPointGrant.objects.filter(
            AllocationService._build_pending_claim_query(user)
        )
        summary = pending_grants.aggregate(
            claimable_count=models.Count("id"),
            total_amount=Sum("amount"),
        )
        return {
            "claimable_count": summary["claimable_count"] or 0,
            "total_amount": summary["total_amount"] or 0,
        }

    @staticmethod
    def _get_project_identifiers(allocation: PointAllocation) -> list[str]:
        project_scope = allocation.project_scope or {}
        tags = project_scope.get("tags", [])
        normalized = []
        for tag in tags:
            if tag is None:
                continue
            tag_str = str(tag).strip()
            if tag_str:
                normalized.append(tag_str)
        return normalized

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
            return (0, 0, 1, 0)

        AllocationService._create_pending_grant(allocation, item, amount)
        return (0, 1, 0, amount)

    @staticmethod
    def _deduct_source_pool(allocation: PointAllocation, amount: int) -> None:
        if amount <= 0:
            return

        source_pool = PointSource.objects.select_related("wallet", "tag").get(
            id=allocation.source_pool_id
        )
        tag_slug = source_pool.tag.slug if source_pool.tag else None
        tag_is_null = (
            source_pool.point_type == PointType.GIFT and source_pool.tag is None
        )

        spend_points(
            owner=source_pool.wallet.owner,
            amount=amount,
            point_type=source_pool.point_type,
            description=(
                f"贡献度分配 ({allocation.start_month} - {allocation.end_month})"
            ),
            tag_slug=tag_slug,
            tag_is_null=tag_is_null,
            reference_id=f"allocation_{allocation.id}",
            created_by=None,
        )

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
    def _get_github_social_auth(user):
        prefetched_social_auth = getattr(
            user,
            AllocationService.GITHUB_SOCIAL_AUTH_PREFETCH_ATTR,
            None,
        )
        if prefetched_social_auth is not None:
            return prefetched_social_auth[0] if prefetched_social_auth else None

        return user.social_auth.filter(provider="github").only("uid").first()

    @staticmethod
    def _build_pending_claim_query(user) -> models.Q:
        github_social = AllocationService._get_github_social_auth(user)
        github_id = (
            str(github_social.uid).strip()
            if github_social and github_social.uid
            else ""
        )
        github_login = (user.username or "").strip()
        email = (user.email or "").strip()

        identifier_conditions: list[models.Q] = []
        if github_id:
            identifier_conditions.append(models.Q(github_id=github_id))
        if github_login:
            identifier_conditions.append(models.Q(github_login=github_login))
        if email:
            identifier_conditions.append(models.Q(email=email))

        if not identifier_conditions:
            return models.Q(pk__isnull=True)

        identifier_query = identifier_conditions[0]
        for condition in identifier_conditions[1:]:
            identifier_query |= condition

        return models.Q(is_claimed=False) & identifier_query

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

    @staticmethod
    @transaction.atomic
    def rollback_claimed_points_for_user(
        user, grant_ids: list[int] | None = None
    ) -> dict:
        """
        回退用户已领取的待领取积分记录, 并扣除对应积分.

        Args:
            user: 用户对象
            grant_ids: 可选, 仅回退指定的待领取记录 ID 列表

        Returns:
            {
                "rolled_back_count": 3,
                "total_amount": 9000
            }

        """
        grants = AllocationService._get_rollback_target_grants(
            user=user,
            grant_ids=grant_ids,
            for_update=True,
        )
        if not grants:
            return {"rolled_back_count": 0, "total_amount": 0}

        AllocationService._ensure_rollback_balance_sufficient(user, grants)

        rolled_back_count = 0
        total_amount = 0

        for grant in grants:
            AllocationService._rollback_single_grant(user, grant)
            rolled_back_count += 1
            total_amount += grant.amount

        return {"rolled_back_count": rolled_back_count, "total_amount": total_amount}

    @staticmethod
    def get_rollback_claimed_points_summary(
        user,
        grant_ids: list[int] | None = None,
    ) -> dict:
        """获取用户可回退领取记录的汇总信息."""
        grants = AllocationService._get_rollback_target_grants(
            user=user,
            grant_ids=grant_ids,
            for_update=False,
        )
        if not grants:
            return {
                "rollbackable_count": 0,
                "total_amount": 0,
                "can_execute": True,
                "blocking_error": "",
            }

        can_execute = True
        blocking_error = ""
        try:
            AllocationService._ensure_rollback_balance_sufficient(user, grants)
        except InsufficientPointsError as err:
            can_execute = False
            blocking_error = str(err)

        return {
            "rollbackable_count": len(grants),
            "total_amount": sum(grant.amount for grant in grants),
            "can_execute": can_execute,
            "blocking_error": blocking_error,
        }

    @staticmethod
    def _get_rollback_target_grants(
        user,
        grant_ids: list[int] | None = None,
        *,
        for_update: bool = False,
    ) -> list[PendingPointGrant]:
        grants_queryset = PendingPointGrant.objects.filter(
            is_claimed=True,
            claimed_by=user,
        )
        if grant_ids:
            grants_queryset = grants_queryset.filter(id__in=grant_ids)

        grants_queryset = grants_queryset.select_related("tag").order_by(
            "claimed_at",
            "id",
        )
        if for_update:
            grants_queryset = grants_queryset.select_for_update()

        return list(grants_queryset)

    @staticmethod
    def _ensure_rollback_balance_sufficient(
        user, grants: list[PendingPointGrant]
    ) -> None:
        required_by_bucket: dict[tuple[str, str | None, bool], int] = {}
        for grant in grants:
            if grant.point_type == PointType.CASH:
                bucket = (PointType.CASH, None, False)
            elif grant.tag:
                bucket = (PointType.GIFT, grant.tag.slug, False)
            else:
                bucket = (PointType.GIFT, None, True)

            required_by_bucket[bucket] = (
                required_by_bucket.get(bucket, 0) + grant.amount
            )

        wallet = get_wallet_or_none(user)

        for (
            point_type,
            tag_slug,
            _tag_is_null,
        ), required_amount in required_by_bucket.items():
            if point_type == PointType.CASH:
                available_amount = wallet.get_cash_balance() if wallet else 0
            elif tag_slug:
                available_amount = (
                    wallet.get_gift_balance(tag_slug=tag_slug) if wallet else 0
                )
            elif wallet is None:
                available_amount = 0
            else:
                available_amount = (
                    wallet.sources.filter(
                        point_type=PointType.GIFT,
                        tag__isnull=True,
                        remaining_amount__gt=0,
                    ).aggregate(total=Sum("remaining_amount"))["total"]
                    or 0
                )

            if available_amount < required_amount:
                bucket_name = (
                    "现金积分"
                    if point_type == PointType.CASH
                    else f"礼物积分(tag={tag_slug or '无标签'})"
                )
                msg = (
                    f"用户 {user.username} 余额不足，无法回退 {bucket_name}："
                    f"需要 {required_amount}，可用 {available_amount}"
                )
                raise InsufficientPointsError(msg)

    @staticmethod
    def _rollback_single_grant(user, grant: PendingPointGrant) -> None:
        spend_points(
            owner=user,
            amount=grant.amount,
            point_type=grant.point_type,
            description=f"回退待领取积分 #{grant.id}",
            tag_slug=grant.tag.slug if grant.tag else None,
            tag_is_null=(grant.point_type == PointType.GIFT and grant.tag is None),
            reference_id=f"pending_grant_rollback:{grant.id}",
            created_by=None,
        )

        grant.is_claimed = False
        grant.claimed_by = None
        grant.claimed_at = None
        grant.save(update_fields=["is_claimed", "claimed_by", "claimed_at"])
