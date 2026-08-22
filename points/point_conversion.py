"""One-time conversion of existing point liabilities to the USD-based scale."""

from dataclasses import asdict, dataclass
from itertools import groupby
from typing import Any

from django.utils import timezone

CONVERSION_NUMERATOR = 10
CONVERSION_DENOMINATOR = 67
CONVERSION_REFERENCE_PREFIX = "point_conversion:rmb_to_usd_2026"
CONVERSION_TRANSACTION_TYPE = "spend"
CONVERSION_DESCRIPTION = (
    "积分计价调整：1 RMB = 10 积分改为 1 USD = 10 积分（余额 ÷ 6.7 向下取整）"
)
BLOCKING_ALLOCATION_STATUSES = ("draft", "previewing", "executing")
BLOCKING_WITHDRAWAL_STATUSES = ("pending", "approved")
BATCH_SIZE = 1000


class PointConversionBlocked(RuntimeError):
    """Raised when in-flight point operations make conversion unsafe."""


@dataclass(frozen=True)
class PointConversionSummary:
    """Read-only summary of the changes a conversion would make."""

    source_rows: int = 0
    wallet_buckets: int = 0
    wallet_old_total: int = 0
    wallet_new_total: int = 0
    pending_rows: int = 0
    pending_unclaimed_rows: int = 0
    pending_old_total: int = 0
    pending_new_total: int = 0
    pending_unclaimed_zero_after: int = 0
    outreach_unclaimed_rows: int = 0
    outreach_old_total: int = 0
    outreach_new_total: int = 0
    outreach_zero_after: int = 0
    blocking_allocations: int = 0
    blocking_withdrawals: int = 0

    @property
    def has_blockers(self) -> bool:
        """Return whether conversion must stop for manual resolution."""
        return bool(self.blocking_allocations or self.blocking_withdrawals)

    def as_dict(self) -> dict[str, int | bool]:
        """Return a JSON-serializable representation."""
        return {**asdict(self), "has_blockers": self.has_blockers}


def convert_amount(amount: int) -> int:
    """Divide a non-negative point amount by 6.7, rounding down exactly."""
    if amount < 0:
        msg = "Point conversion only accepts non-negative amounts."
        raise ValueError(msg)
    return amount * CONVERSION_NUMERATOR // CONVERSION_DENOMINATOR


def apportion_source_amounts(items: list[tuple[int, int]]) -> dict[int, int]:
    """
    Convert a wallet bucket while preserving its rounded aggregate total.

    Converting every source independently can lose more points than converting the
    wallet balance once. Floor every source first, then distribute the aggregate
    remainder to sources with the largest fractional remainders. Source IDs provide
    deterministic tie-breaking.
    """
    if not items:
        return {}
    if any(amount < 0 for _, amount in items):
        msg = "Point source amounts must be non-negative."
        raise ValueError(msg)

    target_total = convert_amount(sum(amount for _, amount in items))
    converted = {source_id: convert_amount(amount) for source_id, amount in items}
    remainder = target_total - sum(converted.values())
    ranked_ids = sorted(
        (
            (amount * CONVERSION_NUMERATOR) % CONVERSION_DENOMINATOR,
            source_id,
        )
        for source_id, amount in items
    )
    for _, source_id in sorted(ranked_ids, key=lambda item: (-item[0], item[1]))[
        :remainder
    ]:
        converted[source_id] += 1
    return converted


def _source_groups(PointSource):
    sources = PointSource.objects.order_by(
        "wallet_id",
        "point_type",
        "id",
    ).iterator(chunk_size=BATCH_SIZE)
    return groupby(sources, key=lambda source: (source.wallet_id, source.point_type))


def _pending_groups(PendingPointGrant):
    unclaimed = PendingPointGrant.objects.filter(is_claimed=False).order_by(
        "platform",
        "actor_id",
        "point_type",
        "tag_id",
        "id",
    )

    def unclaimed_key(grant):
        if not grant.actor_id:
            return ("unclaimable", str(grant.id), "", "", None)
        return (
            "claimable",
            grant.platform,
            grant.actor_id,
            grant.point_type,
            grant.tag_id,
        )

    for _, grant_group in groupby(
        unclaimed.iterator(chunk_size=BATCH_SIZE),
        key=unclaimed_key,
    ):
        yield True, grant_group

    claimed = PendingPointGrant.objects.filter(is_claimed=True).order_by(
        "claimed_by_id",
        "point_type",
        "tag_id",
        "id",
    )

    def claimed_key(grant):
        if grant.claimed_by_id is None:
            return ("deleted-claimant", str(grant.id), "", None)
        return (
            "claimed",
            str(grant.claimed_by_id),
            grant.point_type,
            grant.tag_id,
        )

    for _, grant_group in groupby(
        claimed.iterator(chunk_size=BATCH_SIZE),
        key=claimed_key,
    ):
        yield False, grant_group


def build_conversion_summary(
    *,
    PointSource,
    PendingPointGrant,
    PointAllocation,
    WithdrawalRequest,
    OutreachRecipient,
) -> PointConversionSummary:
    """Inspect all affected rows without modifying them."""
    source_rows = 0
    wallet_buckets = 0
    wallet_old_total = 0
    wallet_new_total = 0
    for _, source_group in _source_groups(PointSource):
        amounts = [source.remaining_amount for source in source_group]
        source_rows += len(amounts)
        wallet_buckets += 1
        old_total = sum(amounts)
        wallet_old_total += old_total
        wallet_new_total += convert_amount(old_total)

    pending_rows = 0
    pending_unclaimed_rows = 0
    pending_old_total = 0
    pending_new_total = 0
    pending_unclaimed_zero_after = 0
    for is_unclaimed, pending_group in _pending_groups(PendingPointGrant):
        grants = list(pending_group)
        converted = apportion_source_amounts(
            [(grant.id, grant.amount) for grant in grants]
        )
        pending_rows += len(grants)
        pending_old_total += sum(grant.amount for grant in grants)
        pending_new_total += sum(converted.values())
        if is_unclaimed:
            pending_unclaimed_rows += len(grants)
            pending_unclaimed_zero_after += sum(
                converted[grant.id] == 0 for grant in grants
            )

    outreach_unclaimed_rows = 0
    outreach_old_total = 0
    outreach_new_total = 0
    outreach_zero_after = 0
    outreach_values = (
        OutreachRecipient.objects.filter(
            is_rewarded=False,
            reward_expired=False,
        )
        .order_by("id")
        .values_list("reward_amount", flat=True)
    )
    for amount in outreach_values.iterator(chunk_size=BATCH_SIZE):
        converted = convert_amount(amount)
        outreach_unclaimed_rows += 1
        outreach_old_total += amount
        outreach_new_total += converted
        if converted == 0:
            outreach_zero_after += 1

    return PointConversionSummary(
        source_rows=source_rows,
        wallet_buckets=wallet_buckets,
        wallet_old_total=wallet_old_total,
        wallet_new_total=wallet_new_total,
        pending_rows=pending_rows,
        pending_unclaimed_rows=pending_unclaimed_rows,
        pending_old_total=pending_old_total,
        pending_new_total=pending_new_total,
        pending_unclaimed_zero_after=pending_unclaimed_zero_after,
        outreach_unclaimed_rows=outreach_unclaimed_rows,
        outreach_old_total=outreach_old_total,
        outreach_new_total=outreach_new_total,
        outreach_zero_after=outreach_zero_after,
        blocking_allocations=PointAllocation.objects.filter(
            status__in=BLOCKING_ALLOCATION_STATUSES,
        ).count(),
        blocking_withdrawals=WithdrawalRequest.objects.filter(
            status__in=BLOCKING_WITHDRAWAL_STATUSES,
        ).count(),
    )


def _flush_updates(model, objects: list[Any], field_name: str) -> None:
    if objects:
        model.objects.bulk_update(objects, [field_name], batch_size=BATCH_SIZE)
        objects.clear()


def _flush_creates(model, objects: list[Any]) -> None:
    if objects:
        model.objects.bulk_create(objects, batch_size=BATCH_SIZE)
        objects.clear()


def _convert_sources(PointSource, PointTransaction) -> None:
    source_updates: list[Any] = []
    transaction_creates: list[Any] = []
    converted_at = timezone.now()

    for (wallet_id, point_type), source_group in _source_groups(PointSource):
        sources = list(source_group)
        old_total = sum(source.remaining_amount for source in sources)
        new_amounts = apportion_source_amounts(
            [(source.id, source.remaining_amount) for source in sources]
        )
        new_total = sum(new_amounts.values())

        for source in sources:
            new_amount = new_amounts[source.id]
            if source.remaining_amount == new_amount:
                continue
            source.remaining_amount = new_amount
            source_updates.append(source)

        if new_total != old_total:
            transaction_creates.append(
                PointTransaction(
                    wallet_id=wallet_id,
                    # Keep the stored value migration-stable instead of coupling an
                    # old data migration to the current runtime TextChoices class.
                    transaction_type=CONVERSION_TRANSACTION_TYPE,
                    point_type=point_type,
                    amount=new_total - old_total,
                    balance_after=new_total,
                    description=CONVERSION_DESCRIPTION,
                    reference_id=(
                        f"{CONVERSION_REFERENCE_PREFIX}:{wallet_id}:{point_type}"
                    ),
                    source_id=None,
                    tag_id=None,
                    created_by_id=None,
                    created_at=converted_at,
                )
            )

        if len(source_updates) >= BATCH_SIZE:
            _flush_updates(PointSource, source_updates, "remaining_amount")
        if len(transaction_creates) >= BATCH_SIZE:
            _flush_creates(PointTransaction, transaction_creates)

    _flush_updates(PointSource, source_updates, "remaining_amount")
    _flush_creates(PointTransaction, transaction_creates)


def _convert_scalar_field(model, queryset, field_name: str) -> None:
    updates: list[Any] = []
    for instance in queryset.iterator(chunk_size=BATCH_SIZE):
        old_amount = getattr(instance, field_name)
        new_amount = convert_amount(old_amount)
        if old_amount == new_amount:
            continue
        setattr(instance, field_name, new_amount)
        updates.append(instance)
        if len(updates) >= BATCH_SIZE:
            _flush_updates(model, updates, field_name)
    _flush_updates(model, updates, field_name)


def _convert_pending_grants(PendingPointGrant) -> None:
    updates: list[Any] = []
    for _, pending_group in _pending_groups(PendingPointGrant):
        grants = list(pending_group)
        converted = apportion_source_amounts(
            [(grant.id, grant.amount) for grant in grants]
        )
        for grant in grants:
            new_amount = converted[grant.id]
            if grant.amount == new_amount:
                continue
            grant.amount = new_amount
            updates.append(grant)
        if len(updates) >= BATCH_SIZE:
            _flush_updates(PendingPointGrant, updates, "amount")
    _flush_updates(PendingPointGrant, updates, "amount")


def apply_point_conversion(  # noqa: PLR0913
    *,
    PointSource,
    PointTransaction,
    PendingPointGrant,
    PointAllocation,
    WithdrawalRequest,
    OutreachRecipient,
) -> PointConversionSummary:
    """Apply the irreversible conversion after validating operational blockers."""
    summary = build_conversion_summary(
        PointSource=PointSource,
        PendingPointGrant=PendingPointGrant,
        PointAllocation=PointAllocation,
        WithdrawalRequest=WithdrawalRequest,
        OutreachRecipient=OutreachRecipient,
    )
    if summary.has_blockers:
        msg = (
            "Point conversion blocked: "
            f"active allocations={summary.blocking_allocations}, "
            f"pending/approved withdrawals={summary.blocking_withdrawals}. "
            "Resolve them and deploy again."
        )
        raise PointConversionBlocked(msg)

    _convert_sources(PointSource, PointTransaction)
    _convert_pending_grants(PendingPointGrant)
    _convert_scalar_field(
        OutreachRecipient,
        OutreachRecipient.objects.filter(
            is_rewarded=False,
            reward_expired=False,
        ).order_by("id"),
        "reward_amount",
    )
    return summary


def lock_conversion_tables(connection, models: list[Any]) -> None:
    """Block concurrent point writes for the duration of a PostgreSQL migration."""
    if connection.vendor != "postgresql":
        return
    quote_name = connection.ops.quote_name
    table_names = ", ".join(quote_name(model._meta.db_table) for model in models)
    with connection.cursor() as cursor:
        cursor.execute(f"LOCK TABLE {table_names} IN ACCESS EXCLUSIVE MODE")
