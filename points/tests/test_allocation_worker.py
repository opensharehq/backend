"""Worker restart, atomic acknowledgement and live-worker exclusion contracts."""

import json
import os
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier, Event
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command, get_commands, load_command_class
from django.db import OperationalError, connection, connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from django_tasks.backends.database.management.commands.db_worker import Worker
from django_tasks.backends.database.models import DBTaskResult

from accounts.models import User
from points.allocation_batches import execute_batched_allocation, queue_allocation
from points.allocation_funding import fail_allocation
from points.allocation_services import AllocationService
from points.allocation_worker import AllocationWorker
from points.models import (
    AllocationBatch,
    PendingPointGrant,
    PointAllocation,
    PointTransaction,
    PointType,
)
from points.services import get_balance, grant_points

CRASH_WORKER = """
import json, os, signal
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['PYTEST_VERSION'] = 'worker-crash-test'
from django.conf import settings
settings.DATABASES = {'default': json.loads(os.environ['ALLOCATION_TEST_DATABASE'])}
import django
django.setup()
from points.allocation_services import AllocationService
from points.allocation_worker import AllocationWorker
from django_tasks.backends.database.models import DBTaskResult

def crash(*args, **kwargs):
    os.kill(os.getpid(), signal.SIGKILL)

phase = os.environ['ALLOCATION_TEST_CRASH_PHASE']
if phase == 'after_batch':
    original = AllocationService._apply_allocation_items
    def apply(*args, **kwargs):
        original(*args, **kwargs)
        crash()
    AllocationService._apply_allocation_items = apply
elif phase == 'during_refund':
    from points.models import PointTransaction
    def fail(*args, **kwargs):
        raise RuntimeError('Injected fatal allocation error')
    AllocationService._apply_allocation_items = fail
    original = PointTransaction.save
    def save(self, *args, **kwargs):
        original(self, *args, **kwargs)
        if self.transaction_type == 'refund':
            crash()
    PointTransaction.save = save
elif phase == 'before_ack':
    DBTaskResult.set_succeeded = crash
elif phase == 'after_commit':
    original = AllocationWorker.run_task
    def run_task(*args, **kwargs):
        original(*args, **kwargs)
        crash()
    AllocationWorker.run_task = run_task

AllocationWorker(queue_names=['default'], interval=0, batch=True,
    backend_name='default', startup_delay=False, max_tasks=1,
    worker_id='killed-worker').run()
"""


class AllocationWorkerTests(TransactionTestCase):
    def setUp(self):
        self.operator = User.objects.create_user(username="restart-operator")
        self.recipient = User.objects.create_user(username="restart-recipient")
        source = grant_points(
            owner=self.operator, amount=100, point_type=PointType.GIFT, reason="Fixture"
        )
        self.allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.operator.pk,
            source_pool=source,
            total_amount=3,
            total_recipients=3,
            batch_count=2,
            project_scope={"tags": ["repo:test"]},
            user_scope={"type": "all"},
            start_month=date(2026, 8, 1),
            end_month=date(2026, 9, 1),
            note="Restart test",
        )
        items = [
            {
                "actor_id": str(index),
                "actor_login": f"developer-{index}",
                "platform": "GitHub",
                "amount": 1,
                "is_registered": index == 0,
                "user_id": self.recipient.pk if index == 0 else None,
            }
            for index in range(3)
        ]
        for index, batch in enumerate((items[:2], items[2:])):
            AllocationBatch.objects.create(
                allocation=self.allocation,
                index=index,
                items=batch,
                digest="fixture",
                total_amount=len(batch),
                recipient_count=len(batch),
                registered_count=int(index == 0),
            )
        queue_allocation(self.allocation)
        self.task = DBTaskResult.objects.get()

    def worker(self, **kwargs):
        return AllocationWorker(
            **{
                "queue_names": ["default"],
                "interval": 0,
                "batch": True,
                "backend_name": "default",
                "startup_delay": False,
                "max_tasks": 1,
                "worker_id": "restarted-worker",
                **kwargs,
            }
        )

    def abandon(self, status="executing"):
        self.task.claim("old-worker")
        DBTaskResult.objects.filter(pk=self.task.pk).update(
            started_at=timezone.now() - timedelta(hours=2)
        )
        PointAllocation.objects.filter(pk=self.allocation.pk).update(status=status)
        self.task.refresh_from_db()

    def assert_complete_once(self):
        self.allocation.refresh_from_db()
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "SUCCEEDED", self.task.traceback)
        self.assertEqual(self.allocation.status, "completed")
        self.assertEqual(get_balance(self.operator), 97)
        self.assertEqual(get_balance(self.recipient), 1)
        self.assertEqual(PendingPointGrant.objects.count(), 2)
        self.assertEqual(
            PointTransaction.objects.filter(
                reference_id=f"allocation_{self.allocation.pk}",
                transaction_type="spend",
            ).count(),
            1,
        )
        self.assertEqual(DBTaskResult.objects.count(), 1)

    def assert_rolled_back(self):
        self.assertEqual(get_balance(self.operator), 97)
        self.assertEqual(get_balance(self.recipient), 0)
        self.assertFalse(PendingPointGrant.objects.exists())
        self.assertEqual(PointTransaction.objects.count(), 2)
        self.allocation.refresh_from_db()
        self.assertTrue(self.allocation.funds_reserved)
        self.assertEqual(self.allocation.funding_lots.get().remaining_amount, 3)

    def run_crashing_worker(self, phase):
        # The script is a test constant and uses only this test database.
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-c", CRASH_WORKER],
            env={
                **os.environ,
                "ALLOCATION_TEST_DATABASE": json.dumps(connection.settings_dict),
                "ALLOCATION_TEST_CRASH_PHASE": phase,
            },
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, -signal.SIGKILL, result.stderr)

    def test_restarts_original_task_and_does_not_repeat_committed_transfer(self):
        self.abandon()
        self.worker().run()
        self.assert_complete_once()
        self.assertEqual(self.task.worker_ids, ["old-worker", "restarted-worker"])
        self.worker().run()
        self.assert_complete_once()

    def test_fresh_claim_is_not_reclaimed(self):
        self.task.claim("fresh-worker")
        self.assertEqual(self.worker().recover_allocations(), 0)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "RUNNING")

    def test_lost_claim_cannot_execute_even_when_worker_id_is_reused(self):
        self.abandon()
        self.assertEqual(self.worker().recover_allocations(), 1)
        new_claim = DBTaskResult.objects.get(pk=self.task.pk)
        new_claim.claim("old-worker")
        self.worker(worker_id="old-worker").run_task(self.task)
        self.assert_rolled_back()
        self.worker(worker_id="old-worker").run_task(new_claim)
        self.assert_complete_once()

    def test_business_failure_rolls_back_and_requires_explicit_retry(self):
        with patch.object(
            AllocationService,
            "_apply_allocation_items",
            side_effect=RuntimeError("fatal"),
        ):
            self.worker().run()
        self.task.refresh_from_db()
        self.allocation.refresh_from_db()
        self.assertEqual(self.task.status, "FAILED")
        self.assertEqual(self.allocation.status, "failed")
        self.assertIn("refunded", self.allocation.execution_error)
        self.assertEqual(get_balance(self.operator), 100)
        self.assertEqual(self.allocation.refunded_amount, 3)
        self.assertFalse(self.allocation.funds_reserved)
        self.assertFalse(PendingPointGrant.objects.exists())
        self.assertEqual(get_balance(self.recipient), 0)
        self.assertEqual(self.worker().recover_allocations(), 0)

    def test_interrupted_execution_rolls_back_and_delays_retry(self):
        real_apply = AllocationService._apply_allocation_items

        def interrupt(*args, **kwargs):
            real_apply(*args, **kwargs)
            raise SystemExit(1)

        with patch.object(AllocationService, "_apply_allocation_items", interrupt):
            self.worker().run()
        self.assert_rolled_back()
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "READY")
        self.assertGreater(self.task.run_after, timezone.now())
        DBTaskResult.objects.filter(pk=self.task.pk).update(run_after=timezone.now())
        self.worker().run()
        self.assert_complete_once()

    def test_acknowledgement_error_rolls_back_completed_allocation(self):
        with patch.object(
            DBTaskResult, "set_succeeded", side_effect=RuntimeError("ack")
        ):
            self.worker().run()
        self.assert_rolled_back()
        self.task.refresh_from_db()
        self.allocation.refresh_from_db()
        self.assertEqual(self.task.status, "RUNNING")
        self.assertEqual(self.allocation.status, "executing")
        self.abandon()
        self.worker().run()
        self.assert_complete_once()

    def test_recovery_of_legacy_completed_task_only_acknowledges(self):
        execute_batched_allocation.func(self.allocation.pk)
        self.abandon(status="completed")
        self.assertEqual(self.worker().recover_allocations(), 0)
        self.assert_complete_once()

    def test_recovery_of_failed_allocation_does_not_transfer_or_refund_twice(self):
        fail_allocation(self.allocation.pk, RuntimeError("fatal"))
        self.abandon(status="failed")
        self.assertEqual(self.worker().recover_allocations(), 0)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "FAILED")
        self.assertEqual(get_balance(self.operator), 100)
        self.assertEqual(
            PointTransaction.objects.filter(transaction_type="refund").count(), 1
        )

    def test_recovery_of_missing_legacy_allocation_does_not_transfer(self):
        self.abandon()
        DBTaskResult.objects.filter(pk=self.task.pk).update(
            args_kwargs={"args": [0], "kwargs": {}}
        )
        self.assertEqual(self.worker().recover_allocations(), 0)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, "FAILED")
        self.assert_rolled_back()

    def test_recovery_respects_queue_backend_and_task_type(self):
        self.abandon(status="queued")
        self.assertEqual(self.worker(queue_names=["other"]).recover_allocations(), 0)
        self.assertEqual(self.worker(backend_name="other").recover_allocations(), 0)
        DBTaskResult.objects.filter(pk=self.task.pk).update(task_path="other.task")
        self.assertEqual(self.worker().recover_allocations(), 0)
        self.task.refresh_from_db()
        with patch.object(Worker, "run_task") as ordinary_task:
            self.worker().run_task(self.task)
        ordinary_task.assert_called_once_with(self.task)

    def test_keyword_task_call_and_all_queues_are_supported(self):
        self.abandon(status="queued")
        DBTaskResult.objects.filter(pk=self.task.pk).update(
            args_kwargs={"args": [], "kwargs": {"allocation_id": self.allocation.pk}},
        )
        self.worker(queue_names=["*"]).run()
        self.assert_complete_once()

    def test_recovery_runs_periodically_without_restarting_idle_worker(self):
        self.abandon()
        worker = self.worker(batch=False)
        # First scan is too early; a later scan must recover without a restart.
        original = worker.recover_allocations
        calls = 0

        def scan():
            nonlocal calls
            calls += 1
            return 0 if calls == 1 else original()

        with (
            patch.object(worker, "recover_allocations", side_effect=scan) as recover,
            patch("points.allocation_worker.time") as clock,
        ):
            clock.monotonic.side_effect = [0, 0, 11, 11]
            worker.run()
            clock.sleep.assert_called_once()
        self.assertEqual(recover.call_count, 2)
        self.assert_complete_once()

    def test_sqlite_contention_is_retried_but_other_database_errors_surface(self):
        worker = self.worker(batch=False, startup_delay=True, interval=0.01)
        with (
            patch.object(
                worker,
                "recover_allocations",
                side_effect=[OperationalError("database is locked"), 0],
            ),
            patch("points.allocation_worker.time.sleep") as sleep,
        ):
            worker.run()
        self.assertEqual(sleep.call_count, 2)
        self.assert_complete_once()
        with (
            patch.object(
                worker,
                "recover_allocations",
                side_effect=OperationalError("connection failed"),
            ),
            self.assertRaisesMessage(OperationalError, "connection failed"),
        ):
            worker.run()

    def test_existing_db_worker_command_uses_recovery_and_disables_default_reload(self):
        self.assertEqual(get_commands()["db_worker"], "points")
        command = load_command_class("points", "db_worker")
        parser = command.create_parser("manage.py", "db_worker")
        self.assertFalse(parser.parse_args([]).reload)
        self.abandon()
        with patch.object(AllocationWorker, "configure_signals"):
            call_command("db_worker", batch=True, startup_delay=False, verbosity=0)
        self.assert_complete_once()

    def test_explicit_reload_preserves_standard_command_behavior(self):
        for child in ("true", "false"):
            with (
                self.subTest(child=child),
                patch.dict(os.environ, {"RUN_MAIN": child}),
                patch(
                    "points.management.commands.db_worker.run_with_reloader"
                ) as reload,
                patch.object(AllocationWorker, "configure_signals") as signals,
            ):
                call_command("db_worker", reload=True, verbosity=0)
                self.assertEqual(signals.call_count, int(child == "true"))
                reload.assert_called_once()

    @skipUnlessDBFeature("has_select_for_update_skip_locked")
    def test_sigkill_after_partial_transfer_or_before_ack_rolls_back_and_restarts(self):
        for phase in ("after_batch", "before_ack", "during_refund"):
            with self.subTest(phase=phase):
                self.run_crashing_worker(phase)
                self.task.refresh_from_db()
                self.allocation.refresh_from_db()
                self.assertEqual(self.task.status, "RUNNING")
                self.assertEqual(self.allocation.status, "executing")
                self.assert_rolled_back()
                DBTaskResult.objects.filter(pk=self.task.pk).update(
                    started_at=timezone.now() - timedelta(hours=2)
                )
                self.worker().recover_allocations()
        self.worker().run()
        self.assert_complete_once()
        self.assertEqual(
            self.task.worker_ids, ["killed-worker"] * 3 + ["restarted-worker"]
        )

    @skipUnlessDBFeature("has_select_for_update_skip_locked")
    def test_sigkill_after_commit_does_not_repeat_allocation(self):
        self.run_crashing_worker("after_commit")
        self.worker().run()
        self.assert_complete_once()
        self.assertEqual(self.task.worker_ids, ["killed-worker"])

    @skipUnlessDBFeature("has_select_for_update_skip_locked")
    def test_recovery_skips_live_long_running_workers_including_legacy_worker(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                self.abandon()
                started, release = Event(), Event()

                def run(legacy=legacy, started=started, release=release):
                    try:
                        with patch.object(
                            AllocationService, "_apply_allocation_items"
                        ) as deduct:

                            def pause(*args, **kwargs):
                                started.set()
                                self.assertTrue(release.wait(15))
                                raise SystemExit(1)

                            deduct.side_effect = pause
                            if legacy:
                                with self.assertRaises(SystemExit):
                                    execute_batched_allocation.func(self.allocation.pk)
                            else:
                                self.worker(worker_id="old-worker").run_task(self.task)
                    finally:
                        connections.close_all()

                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(run)
                    try:
                        self.assertTrue(started.wait(15))
                        self.assertEqual(self.worker().recover_allocations(), 0)
                    finally:
                        release.set()
                    future.result(timeout=15)
                self.assert_rolled_back()

    @skipUnlessDBFeature("has_select_for_update_skip_locked")
    def test_three_workers_recover_abandoned_task_only_once(self):
        self.abandon()
        barrier = Barrier(3, timeout=15)

        def run(index):
            try:
                barrier.wait()
                self.worker(worker_id=f"recovery-{index}").run()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(run, index) for index in range(3)]
            for future in futures:
                future.result(timeout=20)
        self.assert_complete_once()
        self.assertEqual(len(self.task.worker_ids), 2)
