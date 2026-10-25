# ruff: noqa: EM101
"""Bounded uploads and transactional background execution of large allocations."""

import hashlib
import json
import logging

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone
from django_tasks import task

from config.api_common import ApiError

from .allocation_funding import (
    fail_allocation,
    load_funding,
    prepare_allocation,
    reserve_funds,
    settle_funds,
)
from .allocation_services import AllocationService
from .models import AllocationBatch, AllocationStatus, PointAllocation
from .services import InsufficientPointsError

logger = logging.getLogger(__name__)
BATCH_SIZE = 1000


def upload_stats(allocation):
    """Read only batch metadata, never the full recipient JSON."""
    return allocation.batches.aggregate(
        count=Count("id"), recipients=Sum("recipient_count"), amount=Sum("total_amount")
    )


def batch_status(allocation):
    """Return a bounded response for retries and status polling."""
    uploaded = upload_stats(allocation)
    return {
        "id": allocation.id,
        "status": allocation.status,
        "batch_size": BATCH_SIZE,
        "batch_count": allocation.batch_count,
        "uploaded_batches": uploaded["count"],
        "uploaded_recipients": uploaded["recipients"] or 0,
        "total_recipients": allocation.total_recipients,
        "error": allocation.execution_error,
        "funds_reserved": allocation.funds_reserved,
        "refunded_amount": allocation.refunded_amount,
        "result": {
            "success": allocation.registered_recipients,
            "pending": allocation.unregistered_recipients,
            "failed": allocation.failed_recipients,
            "total_points": allocation.total_amount,
        }
        if allocation.status == AllocationStatus.COMPLETED
        else None,
    }


@transaction.atomic
def store_batch(allocation, index, items):
    """Accept identical retries but never overwrite a previously uploaded batch."""
    allocation = PointAllocation.objects.select_for_update().get(pk=allocation.pk)
    expected_size = min(BATCH_SIZE, allocation.total_recipients - index * BATCH_SIZE)
    if index < 0 or index >= allocation.batch_count or len(items) != expected_size:
        raise ApiError(
            "validation_error", 422, "Unexpected allocation batch size or index."
        )
    platforms = allocation.project_scope.get("platforms")
    if any(item["amount"] < 0 for item in items) or (
        platforms is not None
        and any(
            item["platform"].lower() not in {p.lower() for p in platforms}
            for item in items
        )
    ):
        raise ApiError(
            "validation_error", 422, "Invalid allocation amount or platform."
        )
    digest = hashlib.sha256(
        json.dumps(items, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    existing = allocation.batches.filter(index=index).first()
    if existing:
        if existing.digest != digest:
            raise ApiError(
                "batch_conflict",
                409,
                "This batch has already been uploaded with different recipients.",
            )
        return
    if allocation.status != AllocationStatus.DRAFT:
        raise ApiError(
            "allocation_locked", 409, "This allocation is no longer accepting uploads."
        )
    AllocationBatch.objects.create(
        allocation=allocation,
        index=index,
        items=items,
        digest=digest,
        total_amount=sum(item["amount"] for item in items),
        recipient_count=len(items),
        registered_count=sum(
            bool(item["is_registered"] and item["amount"] > 0) for item in items
        ),
    )


@transaction.atomic
def queue_allocation(allocation):
    """Validate the entire upload and enqueue once in the same database commit."""
    allocation = PointAllocation.objects.select_for_update().get(pk=allocation.pk)
    if allocation.status in (
        AllocationStatus.QUEUED,
        AllocationStatus.EXECUTING,
        AllocationStatus.COMPLETED,
    ):
        return allocation
    uploaded = upload_stats(allocation)
    if (
        uploaded["count"] != allocation.batch_count
        or uploaded["recipients"] != allocation.total_recipients
        or uploaded["amount"] != allocation.total_amount
    ):
        raise ApiError(
            "incomplete_allocation",
            409,
            "Upload all batches and verify the total amount before execution.",
        )
    try:
        reserve_funds(allocation)
    except InsufficientPointsError as exc:
        raise ApiError(
            "insufficient_points",
            409,
            "The selected point pool no longer has enough balance. No task was queued.",
        ) from exc
    allocation.status = AllocationStatus.QUEUED
    allocation.execution_error = ""
    allocation.save(update_fields=["status", "execution_error"])
    execute_batched_allocation.enqueue(allocation.id)
    return allocation


@task(enqueue_on_commit=False)
def execute_batched_allocation(allocation_id):
    """Stream batches under one transaction; retries cannot duplicate transfers."""
    try:
        if not prepare_allocation(allocation_id):
            return
        with transaction.atomic():
            # Lock only the allocation. Joining the nullable source tag here
            # makes PostgreSQL reject FOR UPDATE on the outer join.
            allocation = PointAllocation.objects.select_for_update().get(
                pk=allocation_id
            )
            if allocation.status != AllocationStatus.EXECUTING:
                return
            funding_lots = load_funding(allocation)
            stats = {"success": 0, "pending": 0, "failed": 0, "total_points": 0}
            # Fetch one batch row by index per iteration. Its JSON holds at most
            # BATCH_SIZE recipients, keeping recipient reads bounded.
            for index in range(allocation.batch_count):
                batch = allocation.batches.get(index=index)
                result = AllocationService._apply_allocation_items(
                    allocation, batch.items, funding_lots=funding_lots
                )
                for key in stats:
                    stats[key] += result[key]
            settle_funds(allocation, funding_lots)
            allocation.status = AllocationStatus.COMPLETED
            allocation.total_amount = stats["total_points"]
            allocation.registered_recipients = stats["success"]
            allocation.unregistered_recipients = stats["pending"]
            allocation.failed_recipients = stats["failed"]
            allocation.executed_at = timezone.now()
            allocation.save(
                update_fields=[
                    "status",
                    "total_amount",
                    "registered_recipients",
                    "unregistered_recipients",
                    "failed_recipients",
                    "executed_at",
                ]
            )
    except Exception as exc:
        fail_allocation(allocation_id, exc)
        logger.exception("Batched allocation %s failed", allocation_id)
        raise


def registered_recipients(allocation):
    """Assemble all registered recipients without caching every batch model."""
    batches = (
        allocation.batches.filter(registered_count__gt=0)
        .values_list("items", flat=True)
        .iterator(chunk_size=1)
    )
    return [
        item
        for items in batches
        for item in items
        if item["is_registered"] and item["amount"] > 0
    ]
