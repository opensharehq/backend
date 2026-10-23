"""Prepay queued allocations and refund unused funds without changing expiry."""

from django.db import transaction
from django.utils import timezone

from .models import (
    AllocationFundingLot,
    AllocationStatus,
    PointAllocation,
    PointSource,
    PointTransaction,
    PointType,
    TransactionType,
)
from .services import InsufficientPointsError, spend_points


def reserve_funds(allocation):
    """Debit once while the caller holds the allocation lock in a transaction."""
    if allocation.funds_reserved:
        return
    source = allocation.source_pool
    debits = (
        spend_points(
            owner=source.wallet.owner,
            amount=allocation.total_amount,
            point_type=source.point_type,
            description=f"贡献度分配预扣 ({allocation.start_month} - {allocation.end_month})",
            tag_slug=source.tag.slug if source.tag else None,
            tag_is_null=source.point_type == PointType.GIFT and source.tag is None,
            reference_id=f"allocation_{allocation.pk}",
        )
        if allocation.total_amount
        else []
    )
    AllocationFundingLot.objects.bulk_create(
        [
            AllocationFundingLot(
                allocation=allocation,
                source_id=debit.source_id,
                debit=debit,
                amount=-debit.amount,
                remaining_amount=-debit.amount,
            )
            for debit in debits
        ],
        batch_size=500,
    )
    allocation.funds_reserved = True
    allocation.refunded_amount = 0
    allocation.save(update_fields=["funds_reserved", "refunded_amount"])


@transaction.atomic
def prepare_allocation(allocation_id):
    """Publish progress and prepay legacy queued tasks before the long transaction."""
    allocation = PointAllocation.objects.select_for_update().get(pk=allocation_id)
    if allocation.status not in (AllocationStatus.QUEUED, AllocationStatus.EXECUTING):
        return False
    reserve_funds(allocation)
    allocation.status = AllocationStatus.EXECUTING
    allocation.save(update_fields=["status"])
    return True


def load_funding(allocation):
    """Load the original funding restrictions, independent of wallet activity."""
    lots = [
        [lot.source, lot.remaining_amount]
        for lot in allocation.funding_lots.filter(remaining_amount__gt=0)
        .select_related("source__tag")
        .order_by("id")
    ]
    if sum(amount for _, amount in lots) != allocation.total_amount:
        msg = "Allocation funding does not match its requested amount."
        raise ValueError(msg)
    if any(
        source.expires_at and source.expires_at <= timezone.now() for source, _ in lots
    ):
        msg = "Reserved allocation points have expired."
        raise ValueError(msg)
    return lots


def settle_funds(allocation, unused=None):
    """Settle once; refund all held funds on failure or just unused portions."""
    if not allocation.funds_reserved:
        return
    unused_by_source = (
        {source.pk: amount for source, amount in unused} if unused is not None else None
    )
    refunded = 0
    for lot in allocation.funding_lots.filter(remaining_amount__gt=0).select_related(
        "source__wallet", "source__tag"
    ):
        amount = (
            lot.remaining_amount
            if unused_by_source is None
            else unused_by_source[lot.source_id]
        )
        if not 0 <= amount <= lot.remaining_amount:
            msg = "Invalid allocation refund amount."
            raise ValueError(msg)
        if amount:
            original = lot.source
            wallet = original.wallet
            reason = f"贡献度分配未发放积分退回 (#{allocation.pk})"
            source = PointSource.objects.create(
                wallet=wallet,
                point_type=original.point_type,
                tag=original.tag,
                original_amount=amount,
                remaining_amount=amount,
                reason=reason,
                reference_id=f"allocation_{allocation.pk}",
                expires_at=original.expires_at,
            )
            PointTransaction.objects.create(
                wallet=wallet,
                transaction_type=TransactionType.REFUND,
                point_type=original.point_type,
                amount=amount,
                balance_after=wallet.get_cash_balance()
                if original.point_type == PointType.CASH
                else wallet.get_gift_balance(),
                description=reason,
                reference_id=f"allocation_{allocation.pk}",
                source=source,
                tag=original.tag,
            )
            refunded += amount
    allocation.funding_lots.filter(remaining_amount__gt=0).update(remaining_amount=0)
    allocation.funds_reserved = False
    allocation.refunded_amount = refunded
    allocation.save(update_fields=["funds_reserved", "refunded_amount"])


@transaction.atomic
def fail_allocation(allocation_id, exc):
    """Refund and mark a fatal failure atomically, after transfer rollback."""
    allocation = PointAllocation.objects.select_for_update().get(pk=allocation_id)
    if allocation.status not in (AllocationStatus.QUEUED, AllocationStatus.EXECUTING):
        return
    settle_funds(allocation)
    allocation.status = AllocationStatus.FAILED
    allocation.execution_error = (
        "Insufficient points to prepay this allocation. No points were distributed."
        if isinstance(exc, InsufficientPointsError)
        else "Allocation failed. No points were distributed; any prepaid points were refunded."
    )
    allocation.save(update_fields=["status", "execution_error"])
