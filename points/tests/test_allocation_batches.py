"""Batch upload, retry, atomicity and bounded-memory allocation contracts."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import close_old_connections, connections
from django.test import (
    RequestFactory,
    TestCase,
    TransactionTestCase,
    override_settings,
    skipUnlessDBFeature,
)
from django_tasks.backends.database.models import DBTaskResult

from accounts.models import Organization, OrganizationMembership, User
from accounts.services.jwt_tokens import create_access_token
from common.middleware import show_debug_toolbar
from points.allocation_batches import (
    execute_batched_allocation,
    queue_allocation,
    registered_recipients,
)
from points.allocation_funding import fail_allocation
from points.allocation_worker import AllocationWorker as Worker
from points.models import (
    AllocationBatch,
    PendingPointGrant,
    PointAllocation,
    PointTransaction,
    PointType,
)
from points.services import get_balance, grant_points


class AllocationBatchTests(TestCase):
    def setUp(self):
        self.operator = User.objects.create_user(
            username="batch-operator", is_staff=True
        )
        self.recipient = User.objects.create_user(username="batch-recipient")
        grant_points(
            owner=self.operator,
            amount=10_000_000,
            point_type=PointType.GIFT,
            reason="Fixture",
        )
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.operator)}"
        }
        self.config = {
            "submission_id": str(uuid4()),
            "total_recipients": 3,
            "total_amount": 3,
            "source_selector": {"owner_type": "user", "point_type": "gift"},
            "project_scope": {"tags": ["repo:test"], "platforms": None},
            "start_month": "2026-08-01",
            "end_month": "2026-09-01",
            "note": "感谢贡献",
        }
        for target in (
            "points.api_v1.BATCH_SIZE",
            "points.allocation_batches.BATCH_SIZE",
        ):
            patcher = patch(target, 2)
            patcher.start()
            self.addCleanup(patcher.stop)

    def post(self, path, payload=None):
        return self.client.post(
            path, data=payload or {}, content_type="application/json", **self.headers
        )

    def create(self):
        response = self.post("/api/v1/points/allocation-uploads", self.config)
        self.assertEqual(response.status_code, 201, response.content)
        self.allocation = PointAllocation.objects.get(id=response.json()["id"])
        self.path = f"/api/v1/points/allocation-uploads/{self.allocation.id}"
        return response

    def item(self, index, registered=False, amount=1):
        return {
            "actor_id": str(index),
            "actor_login": f"developer-{index}",
            "platform": "GitHub",
            "is_registered": registered,
            "user_id": self.recipient.id if registered else None,
            "contribution_score": 1,
            "amount": amount,
        }

    def upload(self, index, items):
        return self.client.put(
            f"{self.path}/batches/{index}",
            data={"allocations": items},
            content_type="application/json",
            **self.headers,
        )

    def upload_all(self):
        self.assertEqual(
            self.upload(0, [self.item(0, True), self.item(1)]).status_code, 200
        )
        self.assertEqual(self.upload(1, [self.item(2)]).status_code, 200)

    def queue(self):
        response = self.post(f"{self.path}/execute")
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def test_upload_and_execution_retries_do_not_duplicate_points(self):
        self.create()
        response = self.post("/api/v1/points/allocation-uploads", self.config)
        self.assertEqual(response.status_code, 200)
        self.upload_all()
        self.assertEqual(
            self.upload(0, [self.item(0, True), self.item(1)]).status_code, 200
        )
        self.assertEqual(AllocationBatch.objects.count(), 2)
        self.assertEqual(get_balance(self.operator), 10_000_000)
        self.queue()
        self.queue()
        self.assertEqual(get_balance(self.operator), 9_999_997)
        self.assertEqual(DBTaskResult.objects.count(), 1)
        execute_batched_allocation.func(self.allocation.id)
        execute_batched_allocation.func(self.allocation.id)
        self.assertEqual(PendingPointGrant.objects.count(), 2)
        self.assertEqual(get_balance(self.operator), 9_999_997)
        self.assertEqual(get_balance(self.recipient), 1)
        self.assertIn("感谢贡献", PendingPointGrant.objects.first().reason)
        status = self.client.get(self.path, **self.headers).json()
        self.assertEqual(status["status"], "completed")
        self.assertEqual(
            status["result"],
            {"success": 1, "pending": 2, "failed": 0, "total_points": 3},
        )
        self.queue()
        self.assertEqual(DBTaskResult.objects.count(), 1)
        detail = self.client.get(
            f"/api/v1/points/allocations/{self.allocation.id}", **self.headers
        ).json()
        self.assertFalse(detail["paginated"])
        self.assertEqual(len(detail["contribution_data"]), 1)
        self.assertEqual(len(detail["pending_grants"]), 2)

    def test_missing_batches_and_mismatched_totals_cannot_execute(self):
        self.create()
        self.assertEqual(self.post(f"{self.path}/execute").status_code, 409)
        self.upload_all()
        PointAllocation.objects.filter(pk=self.allocation.pk).update(total_amount=4)
        self.assertEqual(self.post(f"{self.path}/execute").status_code, 409)
        self.assertFalse(DBTaskResult.objects.exists())

    def test_immutable_batches_and_input_validation(self):
        self.create()
        for index, items in (
            (-1, [self.item(0)]),
            (2, [self.item(0)]),
            (0, [self.item(0)]),
            (0, [self.item(0, amount=-1), self.item(1)]),
        ):
            self.assertEqual(self.upload(index, items).status_code, 422)
        self.assertEqual(self.upload(0, [self.item(0), self.item(1)]).status_code, 200)
        self.assertEqual(
            self.upload(0, [self.item(0, amount=2), self.item(1)]).status_code, 409
        )
        PointAllocation.objects.filter(pk=self.allocation.pk).update(status="queued")
        self.assertEqual(self.upload(1, [self.item(2)]).status_code, 409)
        self.config["note"] = "different"
        self.assertEqual(
            self.post("/api/v1/points/allocation-uploads", self.config).status_code, 409
        )

    def test_selected_platforms_are_enforced(self):
        self.create()
        self.allocation.project_scope["platforms"] = ["Gitee"]
        self.allocation.save()
        self.assertEqual(self.upload(0, [self.item(0), self.item(1)]).status_code, 422)

    def test_uploads_are_authorized_and_recipient_limit_is_preserved(self):
        self.create()
        self.assertEqual(self.client.get(self.path).status_code, 401)
        other_headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.recipient)}"
        }
        self.assertEqual(self.client.get(self.path, **other_headers).status_code, 404)
        self.headers = other_headers
        self.assertEqual(
            self.post("/api/v1/points/allocation-uploads", self.config).status_code, 409
        )
        self.config.update(submission_id=str(uuid4()), total_recipients=3_000_000)
        self.assertEqual(
            self.post("/api/v1/points/allocation-uploads", self.config).status_code, 422
        )

    def test_execution_and_retry_recheck_organization_spending_permission(self):
        organization = Organization.objects.create(name="Batch Org", slug="batch-org")
        membership = OrganizationMembership.objects.create(
            user=self.operator,
            organization=organization,
            role=OrganizationMembership.Role.ADMIN,
        )
        grant_points(owner=organization, amount=10, point_type="gift", reason="Fixture")
        self.config["source_selector"].update(
            owner_type="organization", owner_slug=organization.slug
        )
        self.create()
        self.upload_all()
        membership.role = OrganizationMembership.Role.MEMBER
        membership.save()
        self.assertEqual(self.post(f"{self.path}/execute").status_code, 403)
        self.assertEqual(get_balance(organization), 10)
        self.assertFalse(DBTaskResult.objects.exists())
        membership.role = OrganizationMembership.Role.ADMIN
        membership.save()
        self.queue()
        self.assertEqual(get_balance(organization), 7)
        fail_allocation(self.allocation.pk, RuntimeError("Injected failure"))
        membership.delete()
        self.assertEqual(self.post(f"{self.path}/execute").status_code, 403)
        self.assertEqual(get_balance(organization), 10)
        self.assertEqual(DBTaskResult.objects.count(), 1)

    def test_execution_rechecks_recipient_limit_after_staff_access_is_revoked(self):
        self.create()
        self.upload_all()
        self.operator.is_staff = False
        self.operator.save()
        with patch(
            "points.allocation_services.AllocationService.DEFAULT_RECIPIENT_LIMIT", 2
        ):
            self.assertEqual(self.post(f"{self.path}/execute").status_code, 422)
        self.assertEqual(get_balance(self.operator), 10_000_000)
        self.assertFalse(DBTaskResult.objects.exists())

    def test_failure_in_later_batch_rolls_back_all_transfers_and_can_retry(self):
        self.create()
        self.upload_all()
        self.queue()
        initial_transactions = PointTransaction.objects.count()
        from points.allocation_services import AllocationService

        real_apply = AllocationService._apply_allocation_items
        calls = 0

        def apply(allocation, items, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("Injected failure in second batch")
            return real_apply(allocation, items, **kwargs)

        with patch.object(
            AllocationService, "_apply_allocation_items", side_effect=apply
        ):
            with self.assertRaises(RuntimeError):
                execute_batched_allocation.func(self.allocation.id)
        self.assertFalse(PendingPointGrant.objects.exists())
        self.assertEqual(PointTransaction.objects.count(), initial_transactions + 1)
        self.assertEqual(
            PointTransaction.objects.get(transaction_type="refund").amount, 3
        )
        self.assertEqual(get_balance(self.operator), 10_000_000)
        self.allocation.refresh_from_db()
        self.assertEqual(self.allocation.status, "failed")
        self.queue()
        execute_batched_allocation.func(self.allocation.id)
        self.assertEqual(PendingPointGrant.objects.count(), 2)

    def test_balance_is_checked_when_queuing_before_any_worker_runs(self):
        self.create()
        self.upload_all()
        self.allocation.source_pool.remaining_amount = 0
        self.allocation.source_pool.save()
        response = self.post(f"{self.path}/execute")
        self.assertEqual(response.status_code, 409)
        self.allocation.refresh_from_db()
        self.assertEqual(self.allocation.status, "draft")
        self.assertFalse(DBTaskResult.objects.exists())
        self.assertFalse(PendingPointGrant.objects.exists())

    def test_registered_recipients_cross_batch_boundaries(self):
        self.create()
        self.upload(0, [self.item(0, True), self.item(1, True, amount=0)])
        self.upload(1, [self.item(2, True)])
        with self.assertNumQueries(1):
            items = registered_recipients(self.allocation)
        self.assertEqual([item["actor_id"] for item in items], ["0", "2"])

    def test_detail_returns_all_registered_and_pending_recipients(self):
        # Both lists exceed the former server page size and span many batches.
        self.config.update(total_recipients=44, total_amount=43)
        self.create()
        items = [
            self.item(i, registered=i < 22, amount=0 if i == 21 else 1)
            for i in range(44)
        ]
        for start in range(0, len(items), 2):
            self.assertEqual(
                self.upload(start // 2, items[start : start + 2]).status_code, 200
            )
        self.queue()
        execute_batched_allocation.func(self.allocation.id)
        url = f"/api/v1/points/allocations/{self.allocation.id}"
        response = self.client.get(url, **self.headers)
        self.assertEqual(response.status_code, 200)
        detail = response.json()
        self.assertFalse(detail["paginated"])
        self.assertEqual(detail["registered_count"], 21)
        self.assertEqual(detail["pending_count"], 22)
        self.assertEqual(
            [item["actor_id"] for item in detail["contribution_data"]],
            [str(i) for i in range(21)],
        )
        self.assertEqual(
            [item["actor_id"] for item in detail["pending_grants"]],
            [str(i) for i in range(22, 44)],
        )
        # Older clients may still send page parameters; these must not truncate.
        self.assertEqual(
            self.client.get(
                url, {"registered_page": 2, "pending_page": 2}, **self.headers
            ).json(),
            detail,
        )

    @override_settings(INSTALLED_APPS=[*settings.INSTALLED_APPS, "debug_toolbar"])
    def test_legacy_oversize_request_is_413_even_with_debug_toolbar(self):
        middleware = [
            "debug_toolbar.middleware.DebugToolbarMiddleware",
            *settings.MIDDLEWARE,
        ]
        for debug in (False, True):
            with (
                self.subTest(debug=debug),
                override_settings(
                    DEBUG=debug,
                    MIDDLEWARE=middleware,
                    INTERNAL_IPS=["127.0.0.1"],
                    DATA_UPLOAD_MAX_MEMORY_SIZE=10,
                ),
            ):
                response = self.post(
                    "/api/v1/points/allocations", {"padding": "a" * 20}
                )
                self.assertEqual(response.status_code, 413)
                self.assertEqual(response.json()["code"], "request_too_large")
        factory = RequestFactory()
        with override_settings(DEBUG=True, INTERNAL_IPS=["127.0.0.1"]):
            self.assertFalse(show_debug_toolbar(factory.get("/api/v1/points/pools")))
            self.assertTrue(
                show_debug_toolbar(factory.get("/", REMOTE_ADDR="127.0.0.1"))
            )

    def test_three_million_recipient_manifest_is_small_and_admin_is_not_capped(self):
        self.config.update(total_recipients=3_000_000, total_amount=3_000_000)
        with (
            patch("points.api_v1.BATCH_SIZE", 1000),
            patch("points.allocation_batches.BATCH_SIZE", 1000),
        ):
            response = self.create()
        self.assertEqual(response.json()["batch_count"], 3000)
        self.assertLess(len(json.dumps(self.config)), 1000)
        self.assertLess(len(response.content), 1000)

    def test_worker_processes_three_million_recipients_in_bounded_batches(self):
        # Exercise the real allocation/funding loop. Generate each stored batch
        # on demand and replace pending INSERTs so CI does not need gigabytes
        # of database fixtures. Small integration tests above cover actual writes.
        self.config.update(total_recipients=3_000_000, total_amount=3_000_000)
        with patch("points.api_v1.BATCH_SIZE", 1000):
            self.create()
        self.allocation.status = "queued"
        self.allocation.save()
        inserted = 0
        largest_batch = 0

        def load_batch(*, index):
            return SimpleNamespace(
                items=[self.item(index * 1000 + i) for i in range(1000)]
            )

        def insert_pending(instances):
            nonlocal inserted, largest_batch
            inserted += len(instances)
            largest_batch = max(largest_batch, len(instances))

        with (
            patch.object(type(self.allocation.batches), "get", side_effect=load_batch),
            patch(
                "points.allocation_services.AllocationService._bulk_create_pending_grants",
                side_effect=insert_pending,
            ),
        ):
            execute_batched_allocation.func(self.allocation.id)
        self.allocation.refresh_from_db()
        self.assertEqual(self.allocation.status, "completed")
        self.assertEqual(inserted, 3_000_000)
        self.assertEqual(largest_batch, 1000)
        self.assertEqual(self.allocation.unregistered_recipients, 3_000_000)
        self.assertEqual(get_balance(self.operator), 7_000_000)


class AllocationWorkerConcurrencyTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update_skip_locked")
    def test_three_workers_claim_and_transfer_only_once_with_untagged_pool(self):
        """Exercise real worker claims and nullable-tag execution on PostgreSQL."""
        operator = User.objects.create_user(username="concurrent-operator")
        recipient = User.objects.create_user(username="concurrent-recipient")
        source = grant_points(
            owner=operator, amount=100, point_type=PointType.GIFT, reason="Fixture"
        )
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=operator.pk,
            source_pool=source,
            total_amount=3,
            total_recipients=3,
            batch_count=1,
            project_scope={"tags": ["repo:test"]},
            user_scope={"type": "all"},
            start_month=date(2026, 8, 1),
            end_month=date(2026, 9, 1),
            note="Concurrent execution",
        )
        AllocationBatch.objects.create(
            allocation=allocation,
            index=0,
            items=[
                {
                    "actor_id": str(index),
                    "actor_login": f"developer-{index}",
                    "platform": "GitHub",
                    "amount": 1,
                    "is_registered": index == 0,
                    "user_id": recipient.pk if index == 0 else None,
                }
                for index in range(3)
            ],
            digest="fixture",
            total_amount=3,
            recipient_count=3,
            registered_count=1,
        )
        queue_allocation(allocation)
        start = Barrier(3, timeout=10)

        def run_worker(index):
            close_old_connections()
            try:
                start.wait()
                Worker(
                    queue_names=["default"],
                    interval=0,
                    batch=True,
                    backend_name="default",
                    startup_delay=False,
                    max_tasks=1,
                    worker_id=f"allocation-test-{index}",
                ).run()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=3) as workers:
            futures = [workers.submit(run_worker, index) for index in range(3)]
            for future in futures:
                future.result(timeout=30)

        task_result = DBTaskResult.objects.get()
        self.assertEqual(task_result.status, "SUCCEEDED", task_result.traceback)
        self.assertEqual(len(task_result.worker_ids), 1)
        allocation.refresh_from_db()
        self.assertEqual(allocation.status, "completed")
        self.assertEqual(get_balance(operator), 97)
        self.assertEqual(get_balance(recipient), 1)
        self.assertEqual(
            PendingPointGrant.objects.filter(allocation=allocation).count(), 2
        )
        queue_allocation(allocation)
        self.assertEqual(DBTaskResult.objects.count(), 1)
