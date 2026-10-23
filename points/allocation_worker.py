"""Database worker with transaction-backed recovery for point allocations."""

import logging
import random
import time
from datetime import timedelta

from django.db import OperationalError, close_old_connections, transaction
from django.utils import timezone
from django_tasks.backends.database.management.commands.db_worker import Worker
from django_tasks.backends.database.models import DBTaskResult
from django_tasks.backends.database.utils import exclusive_transaction
from django_tasks.task import ResultStatus

from .allocation_funding import fail_allocation, prepare_allocation
from .models import AllocationStatus, PointAllocation

logger = logging.getLogger(__name__)
ALLOCATION_TASK = "points.allocation_batches.execute_batched_allocation"
RECOVERY_GRACE = timedelta(seconds=30)
RECOVERY_INTERVAL = 10
RECOVERY_BATCH_SIZE = 100


def allocation_id_for(task_result):
    """Resolve both positional and keyword calls stored by django_tasks."""
    arguments = task_result.args_kwargs
    return (
        arguments["args"][0]
        if arguments["args"]
        else arguments["kwargs"]["allocation_id"]
    )


def reset_task(task_result, *, delay=timedelta()):
    """Retry the original task, retaining its ID and worker attempt history."""
    task_result.status = ResultStatus.READY
    task_result.started_at = None
    task_result.finished_at = None
    task_result.exception_class_path = ""
    task_result.traceback = ""
    task_result.return_value = None
    task_result.run_after = timezone.now() + delay
    task_result.save(
        update_fields=[
            "status",
            "started_at",
            "finished_at",
            "exception_class_path",
            "traceback",
            "return_value",
            "run_after",
        ]
    )


class AllocationWorker(Worker):
    """Keep the queue acknowledgement and allocation writes in one transaction."""

    def scoped_tasks(self):
        """Respect the same backend and queue selection for claims and recovery."""
        tasks = DBTaskResult.objects.filter(backend_name=self.backend_name)
        if not self.process_all_queues:
            tasks = tasks.filter(queue_name__in=self.queue_names)
        return tasks

    def recover_allocations(self):
        """Reclaim abandoned allocations without interrupting live workers."""
        tasks = self.scoped_tasks().filter(
            task_path=ALLOCATION_TASK,
            status=ResultStatus.RUNNING,
            started_at__lte=timezone.now() - RECOVERY_GRACE,
        )
        recovered = 0
        # SQLite uses an exclusive transaction; production PostgreSQL skips live
        # workers' row locks. Age only protects the short claim-to-run gap.
        with exclusive_transaction(tasks.db):
            for task_result in tasks.select_for_update(skip_locked=True).order_by(
                "started_at", "pk"
            )[:RECOVERY_BATCH_SIZE]:
                allocation_id = allocation_id_for(task_result)
                allocations = PointAllocation.objects.filter(pk=allocation_id)
                allocation = allocations.select_for_update(skip_locked=True).first()
                if allocation is None and allocations.exists():
                    # Older workers lock only the allocation, not the task row.
                    continue
                if allocation and allocation.status == AllocationStatus.COMPLETED:
                    task_result.set_succeeded(None)
                elif allocation and allocation.status in (
                    AllocationStatus.QUEUED,
                    AllocationStatus.EXECUTING,
                ):
                    reset_task(task_result)
                    allocation.status = AllocationStatus.QUEUED
                    allocation.save(update_fields=["status"])
                    recovered += 1
                    logger.warning(
                        "Recovered allocation %s, task %s; retrying rolled-back transfer",
                        allocation.pk,
                        task_result.pk,
                    )
                else:
                    task_result.set_failed(
                        RuntimeError("Allocation is missing or no longer executable.")
                    )
        return recovered

    def run_task(self, db_task_result):
        """Protect allocation execution and its acknowledgement with one lock."""
        if db_task_result.task_path != ALLOCATION_TASK:
            return super().run_task(db_task_result)

        allocation_id = allocation_id_for(db_task_result)
        # Prepay legacy queued tasks in a short commit before the long transfer.
        # Verify ownership first, so a delayed claimant cannot touch a newer run.
        with transaction.atomic():
            locked = DBTaskResult.objects.select_for_update().get(pk=db_task_result.pk)
            if not self.owns_claim(locked, db_task_result):
                return None
            try:
                prepare_allocation(allocation_id)
            except Exception as exc:
                fail_allocation(allocation_id, exc)
                locked.set_failed(exc)
                self._run_tasks += 1
                logger.exception("Could not prepay allocation %s", allocation_id)
                return None
        with transaction.atomic():
            locked = DBTaskResult.objects.select_for_update().get(pk=db_task_result.pk)
            if not self.owns_claim(locked, db_task_result):
                # A paused claimant may have been recovered before taking its lock.
                return None
            super().run_task(locked)
            if locked.status == ResultStatus.FAILED:
                status = (
                    PointAllocation.objects.filter(pk=allocation_id)
                    .values_list("status", flat=True)
                    .first()
                )
                if status == AllocationStatus.EXECUTING:
                    # The base worker catches SystemExit/KeyboardInterrupt too.
                    # Their interrupted inner allocation transaction rolled back.
                    reset_task(locked, delay=RECOVERY_GRACE)
                elif status == AllocationStatus.COMPLETED:
                    # A failure acknowledging success must not commit the transfer.
                    # Leave RUNNING on rollback, for normal recovery to reclaim it.
                    transaction.set_rollback(True)
        return None

    def owns_claim(self, locked, original):
        """Reject stale claims, including reuse of a configured worker ID."""
        return (
            locked.status == ResultStatus.RUNNING
            and locked.worker_ids[-1:] == [self.worker_id]
            and locked.started_at == original.started_at
        )

    def claim_task(self):
        """Use django_tasks' normal short, exclusive claim transaction."""
        tasks = self.scoped_tasks().ready()
        with exclusive_transaction(tasks.db):
            task_result = tasks.get_locked()
            if task_result is not None:
                task_result.claim(self.worker_id)
        return task_result

    def run(self):
        """Poll tasks and periodically recover abandoned allocation executions."""
        logger.info("Starting allocation-aware worker %s", self.worker_id)
        if self.startup_delay and self.interval:
            time.sleep(random.SystemRandom().random())
        next_recovery = 0
        while self.running:
            task_result = None
            try:
                if time.monotonic() >= next_recovery:
                    self.recover_allocations()
                    next_recovery = time.monotonic() + RECOVERY_INTERVAL
                task_result = self.claim_task()
            except OperationalError as exc:
                if "is locked" not in str(exc):
                    raise
            if task_result is not None:
                self.run_task(task_result)
            if self.batch and task_result is None:
                return
            if self.max_tasks is not None and self._run_tasks >= self.max_tasks:
                return
            close_old_connections()
            if self.running and task_result is None:
                time.sleep(self.interval)
