"""积分分配服务."""

import logging
import math
from decimal import Decimal

from django.db import connection, models, transaction
from django.db.models import Sum
from django.utils import timezone

from contributions.services import ContributionService

from common.constants import CODE_HOSTING_PROVIDERS

from .models import (
    AllocationStatus,
    PendingPointGrant,
    PointAllocation,
    PointSource,
    PointType,
)
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
    SOCIAL_AUTH_PREFETCH_ATTR = "prefetched_code_hosting_social_auth"
    # Deprecated: kept for backward compatibility with management commands
    GITHUB_SOCIAL_AUTH_PREFETCH_ATTR = "prefetched_code_hosting_social_auth"
    # 待领取积分批量写入的批大小,在大量未注册贡献者场景下显著降低 DB 往返次数
    PENDING_GRANT_BULK_BATCH_SIZE = 500

    @staticmethod
    def preview_allocation(allocation: PointAllocation) -> list[dict]:
        """
        预览积分分配.

        Returns:
            [
                {
                    "actor_id": "123",
                    "actor_login": "alice",
                    "email": "alice@example.com",
                    "is_registered": True,
                    "user_id": 1,
                    "contribution_score": 250.5,
                    "platform": "github",
                    "gitee_login": ""
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

        return results

    @staticmethod
    def execute_allocation(
        allocation: PointAllocation, allocations: list[dict]
    ) -> dict:
        """
        执行积分分配.

        Args:
            allocation: PointAllocation 记录
            allocations: 前端传入的分配列表, 每项含:
                actor_id, actor_login, platform, email,
                is_registered, user_id, contribution_score, amount

        Returns:
            {
                "success": 15,
                "pending": 5,
                "failed": 0,
                "total_points": 120000
            }

        """
        # 校验 sum(amount) == total_amount
        computed_total = sum(item["amount"] for item in allocations)
        if computed_total != allocation.total_amount:
            msg = (
                f"Sum of allocation amounts ({computed_total}) "
                f"does not match total_amount ({allocation.total_amount})."
            )
            raise ValueError(msg)

        # 防御性校验：每条 amount 不得为负
        if any(item["amount"] < 0 for item in allocations):
            msg = "Allocation amount must not be negative."
            raise ValueError(msg)

        AllocationService._mark_allocation_executing(allocation)

        try:
            with transaction.atomic():
                stats = AllocationService._apply_allocation_items(
                    allocation, allocations
                )
                AllocationService._deduct_source_pool(
                    allocation, stats["total_points"]
                )
                AllocationService._finalize_allocation(
                    allocation, allocations, stats
                )
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
        pending_grants = (
            PendingPointGrant.objects.filter(
                AllocationService._build_pending_claim_query(user)
            )
            .filter(AllocationService._build_unexpired_pending_grant_query())
            .select_related("tag")
        )

        claimed_count = 0
        total_amount = 0

        for grant in pending_grants:
            try:
                claimed_amount = AllocationService._claim_pending_grant(user, grant)
            except Exception:
                logger.exception(
                    "Failed to claim pending grant %s for user %s",
                    grant.id,
                    user.id,
                )
                continue

            if claimed_amount:
                claimed_count += 1
                total_amount += claimed_amount

        return {"claimed_count": claimed_count, "total_amount": total_amount}

    @staticmethod
    def get_claimable_pending_points_summary(user) -> dict:
        """获取用户当前可领取的待领取积分汇总."""
        pending_grants = PendingPointGrant.objects.filter(
            AllocationService._build_pending_claim_query(user)
        ).filter(AllocationService._build_unexpired_pending_grant_query())
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
            if c.get("actor_login") in allowed_users
            or str(c.get("actor_id")) in allowed_users
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
        return {**contrib}

    @staticmethod
    def _scale_results_to_total_amount(results: list[dict], total_amount: int) -> None:
        total_points = sum(r["adjusted_points"] for r in results)
        if total_points <= total_amount:
            return

        scale = total_amount / total_points
        remainders: list[tuple[float, int]] = []
        scaled_total = 0

        for index, result in enumerate(results):
            raw_scaled = result["adjusted_points"] * scale
            scaled_points = math.floor(raw_scaled)
            result["adjusted_points"] = scaled_points
            scaled_total += scaled_points
            remainders.append((raw_scaled - scaled_points, index))

        remainder = total_amount - scaled_total
        if remainder < 0:
            msg = "Scaled allocation exceeded the requested total amount."
            raise AssertionError(msg)

        remainders.sort(key=lambda item: (-item[0], item[1]))
        for _, index in remainders[:remainder]:
            results[index]["adjusted_points"] += 1

        final_total = sum(result["adjusted_points"] for result in results)
        if final_total != total_amount:
            msg = "Scaled allocation did not preserve the requested total amount."
            raise AssertionError(msg)

    @staticmethod
    def _mark_allocation_executing(allocation: PointAllocation) -> None:
        updated_rows = PointAllocation.objects.filter(
            id=allocation.id,
            status=AllocationStatus.DRAFT,
        ).update(status=AllocationStatus.EXECUTING)
        if updated_rows == 0:
            msg = f"Allocation {allocation.id} is not executable"
            raise RuntimeError(msg)

        allocation.status = AllocationStatus.EXECUTING

    @staticmethod
    def _mark_allocation_failed(allocation: PointAllocation) -> None:
        updated_rows = PointAllocation.objects.filter(
            id=allocation.id,
            status=AllocationStatus.EXECUTING,
        ).update(status=AllocationStatus.FAILED)
        if updated_rows:
            allocation.status = AllocationStatus.FAILED

    @staticmethod
    def _apply_allocation_items(
        allocation: PointAllocation, allocations: list[dict]
    ) -> dict:
        success_count = 0
        pending_count = 0
        failed_count = 0
        total_points = 0
        pending_buffer: list[PendingPointGrant] = []

        for item in allocations:
            amount = item["amount"]
            if amount <= 0:
                continue

            if item["is_registered"] and item.get("user_id"):
                success = AllocationService._grant_registered_points(
                    allocation, item, amount
                )
                if success:
                    success_count += 1
                    total_points += amount
                else:
                    failed_count += 1
                continue

            pending_buffer.append(
                AllocationService._build_pending_grant_instance(
                    allocation, item, amount
                )
            )
            pending_count += 1
            total_points += amount

        AllocationService._bulk_create_pending_grants(pending_buffer)

        return {
            "success": success_count,
            "pending": pending_count,
            "failed": failed_count,
            "total_points": total_points,
        }

    @staticmethod
    def _bulk_create_pending_grants(
        instances: list[PendingPointGrant],
    ) -> None:
        """以分批方式写入待领取积分,降低单条 INSERT 带来的开销."""
        if not instances:
            return
        PendingPointGrant.objects.bulk_create(
            instances,
            batch_size=AllocationService.PENDING_GRANT_BULK_BATCH_SIZE,
        )

    @staticmethod
    def _process_preview_item(allocation: PointAllocation, item: dict) -> tuple:
        amount = item.get("amount") or item.get("adjusted_points", 0)
        if amount <= 0:
            return (0, 0, 0, 0)

        if item["is_registered"] and item.get("user_id"):
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
    def _build_pending_grant_instance(
        allocation: PointAllocation, item: dict, amount: int
    ) -> PendingPointGrant:
        """构建未持久化的 PendingPointGrant 实例,供批量写入复用."""
        platform = (item.get("platform") or "").strip()
        if not platform:
            msg = (
                "Pending grant cannot be created without a platform; "
                "upstream contribution data must include 'platform'."
            )
            raise ValueError(msg)

        return PendingPointGrant(
            platform=platform.lower(),
            actor_id=item.get("actor_id", ""),
            actor_login=item.get("actor_login", ""),
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
    def _create_pending_grant(
        allocation: PointAllocation, item: dict, amount: int
    ) -> None:
        """保留单条写入入口,兼容历史调用方与 _process_preview_item 测试链路."""
        instance = AllocationService._build_pending_grant_instance(
            allocation, item, amount
        )
        instance.save()

    @staticmethod
    def _finalize_allocation(
        allocation: PointAllocation,
        allocations_with_amount: list[dict],
        stats: dict,
    ) -> None:
        """
        将执行结果与完整分配快照写入 PointAllocation.

        ``allocations_with_amount`` 来自 execute_allocation 的入参,
        每项包含 actor_id / actor_login / platform / email /
        is_registered / user_id / contribution_score / amount,
        作为后续交易记录/分配详情展示的不可变快照.
        """
        allocation.status = "completed"
        allocation.executed_at = timezone.now()
        allocation.total_recipients = len(allocations_with_amount)
        allocation.registered_recipients = stats["success"]
        allocation.unregistered_recipients = stats["pending"]
        allocation.contribution_data = AllocationService._build_contribution_snapshot(
            allocations_with_amount
        )
        allocation.save()

    @staticmethod
    def _build_contribution_snapshot(
        allocations_with_amount: list[dict],
    ) -> list[dict]:
        """
        构建持久化到 contribution_data 的分配快照.

        保留每个开发者完整的分配元数据(包含 amount),用于:
        - 分配详情页面的明细展示
        - 交易记录页关联回分配上下文
        - 历史审计/对账
        """
        return [
            AllocationService._normalize_contribution_item(item)
            for item in allocations_with_amount
        ]

    @staticmethod
    def _normalize_contribution_item(item: dict) -> dict:
        """标准化单项快照: 复制全部键(含 amount), 仅将 Decimal 贡献度转为 float 以便 JSON 序列化."""
        item_copy = item.copy()
        contribution_score = item_copy.get("contribution_score")
        if isinstance(contribution_score, Decimal):
            item_copy["contribution_score"] = float(contribution_score)
        return item_copy

    @staticmethod
    def _build_pending_claim_query(user) -> models.Q:
        """Build query to find claimable pending grants for a user across all platforms."""
        prefetched = getattr(
            user,
            AllocationService.SOCIAL_AUTH_PREFETCH_ATTR,
            None,
        )
        if prefetched is not None:
            social_auths = [(sa.provider, sa.uid) for sa in prefetched]
        else:
            social_auths = list(
                user.social_auth.filter(
                    provider__in=CODE_HOSTING_PROVIDERS
                ).values_list("provider", "uid")
            )

        conditions: list[models.Q] = []
        for provider, uid in social_auths:
            normalized_uid = str(uid).strip()
            if not normalized_uid:
                continue
            conditions.append(
                models.Q(platform=provider, actor_id=normalized_uid)
            )

        if not conditions:
            return models.Q(pk__isnull=True)

        combined = conditions[0]
        for c in conditions[1:]:
            combined |= c

        return models.Q(is_claimed=False) & combined

    @staticmethod
    def _build_unexpired_pending_grant_query() -> models.Q:
        now = timezone.now()
        return models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)

    @staticmethod
    @transaction.atomic
    def _claim_pending_grant(user, grant: PendingPointGrant) -> int:
        claimed_rows = (
            PendingPointGrant.objects.filter(
                id=grant.id,
                is_claimed=False,
            )
            .filter(AllocationService._build_unexpired_pending_grant_query())
            .update(
                is_claimed=True,
                claimed_by=user,
                claimed_at=timezone.now(),
            )
        )

        if claimed_rows == 0:
            return 0

        grant_points(
            owner=user,
            amount=grant.amount,
            point_type=grant.point_type,
            reason=grant.reason,
            tag_slug=grant.tag.slug if grant.tag else None,
            reference_id=grant.reference_id,
            created_by=None,
        )

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

        AllocationService._ensure_rollback_balance_sufficient(
            user,
            grants,
            lock_sources=True,
        )

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
            if connection.features.has_select_for_update_of:
                grants_queryset = grants_queryset.select_for_update(of=("self",))
            else:
                grants_queryset = grants_queryset.select_for_update()

        return list(grants_queryset)

    @staticmethod
    def _ensure_rollback_balance_sufficient(
        user,
        grants: list[PendingPointGrant],
        *,
        lock_sources: bool = False,
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
            tag_is_null,
        ), required_amount in required_by_bucket.items():
            available_amount = AllocationService._get_rollback_bucket_available_amount(
                wallet,
                point_type=point_type,
                tag_slug=tag_slug,
                tag_is_null=tag_is_null,
                lock_sources=lock_sources,
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
    def _get_rollback_bucket_available_amount(
        wallet,
        *,
        point_type: str,
        tag_slug: str | None,
        tag_is_null: bool,
        lock_sources: bool = False,
    ) -> int:
        if wallet is None:
            return 0

        sources_queryset = PointSource.objects.filter(
            wallet=wallet,
            point_type=point_type,
            remaining_amount__gt=0,
        ).order_by("created_at", "id")

        if point_type == PointType.GIFT:
            if tag_slug:
                sources_queryset = sources_queryset.filter(tag__slug=tag_slug)
            elif tag_is_null:
                sources_queryset = sources_queryset.filter(tag__isnull=True)

        if lock_sources:
            sources_queryset = sources_queryset.select_for_update()

        return sum(source.remaining_amount for source in sources_queryset)

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
