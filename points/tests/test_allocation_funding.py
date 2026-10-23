"""Prepayment, refunds, source restrictions and concurrent wallet spending."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier, Event
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.db import connections
from django.db.models import Sum
from django.db.models.deletion import ProtectedError
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from django_tasks.backends.database.models import DBTaskResult

from accounts.models import Organization, User
from accounts.services.jwt_tokens import create_access_token
from config.api_common import ApiError
from points.allocation_batches import execute_batched_allocation, queue_allocation
from points.allocation_funding import fail_allocation, load_funding, settle_funds
from points.allocation_services import AllocationService
from points.allocation_worker import AllocationWorker
from points.models import (
    AllocationBatch,
    PendingPointGrant,
    PointAllocation,
    PointSource,
    PointTransaction,
    Tag,
    WithdrawalRequest,
)
from points.point_conversion import build_conversion_summary
from points.services import (
    InsufficientPointsError,
    get_balance,
    get_or_create_wallet,
    grant_points,
    spend_points,
)
from talent_reach.models import OutreachRecipient


class AllocationFundingTests(TransactionTestCase):
    def setUp(self):
        self.operator = User.objects.create_user(username="funding-operator")
        self.recipient = User.objects.create_user(username="funding-recipient")
        get_or_create_wallet(self.recipient)
        self.source = grant_points(
            owner=self.operator, amount=100, point_type="gift", reason="Fixture"
        )

    def allocation(self, amounts=(1, 2), *, batch=True, invalid_recipient=False):
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(User),
            initiator_id=self.operator.pk,
            source_pool=self.source,
            total_amount=sum(amounts),
            total_recipients=len(amounts),
            batch_count=len(amounts) if batch else 0,
            project_scope={"tags": ["repo:test"]},
            user_scope={"type": "all"},
            start_month=date(2026, 8, 1),
            end_month=date(2026, 9, 1),
            note="Prepaid allocation",
        )
        items = []
        for index, amount in enumerate(amounts):
            item = {
                "actor_id": str(index),
                "actor_login": f"developer-{index}",
                "platform": "GitHub",
                "amount": amount,
                "is_registered": index == 0,
                "user_id": 0 if invalid_recipient else self.recipient.pk,
            }
            if invalid_recipient:
                item["user_id"] = self.recipient.pk + 10000
            items.append(item)
            if batch:
                AllocationBatch.objects.create(
                    allocation=allocation,
                    index=index,
                    items=[item],
                    digest="fixture",
                    total_amount=amount,
                    recipient_count=1,
                    registered_count=int(index == 0),
                )
        return allocation, items

    def spend(self, amount):
        return spend_points(
            owner=self.operator,
            amount=amount,
            point_type="gift",
            description="Other spending",
        )

    def test_queue_debits_immediately_and_worker_uses_only_prepaid_funds(self):
        allocation, _ = self.allocation()
        queue_allocation(allocation)
        queue_allocation(allocation)
        self.assertEqual(get_balance(self.operator), 97)
        self.assertEqual(DBTaskResult.objects.count(), 1)
        self.assertEqual(
            PointTransaction.objects.filter(transaction_type="spend").count(), 1
        )
        sync_allocation, items = self.allocation((98,), batch=False)
        with self.assertRaises(InsufficientPointsError):
            AllocationService.execute_allocation(sync_allocation, items)
        self.assertEqual(get_balance(self.operator), 97)
        self.spend(97)
        execute_batched_allocation.func(allocation.pk)
        self.assertEqual(get_balance(self.operator), 0)
        self.assertEqual(get_balance(self.recipient), 1)
        self.assertEqual(PendingPointGrant.objects.get().amount, 2)
        self.assertFalse(PointSource.objects.filter(remaining_amount__lt=0).exists())

    def test_failed_enqueue_rolls_back_debit_and_funding_records(self):
        allocation, _ = self.allocation()
        with (
            patch.object(
                type(execute_batched_allocation),
                "enqueue",
                side_effect=RuntimeError("queue unavailable"),
            ),
            self.assertRaisesMessage(RuntimeError, "queue unavailable"),
        ):
            queue_allocation(allocation)
        allocation.refresh_from_db()
        self.assertEqual(allocation.status, "draft")
        self.assertFalse(allocation.funds_reserved)
        self.assertFalse(allocation.funding_lots.exists())
        self.assertFalse(DBTaskResult.objects.exists())
        self.assertEqual(get_balance(self.operator), 100)
        self.assertEqual(PointTransaction.objects.count(), 1)

    def test_fatal_failure_refunds_once_and_retry_prepays_once(self):
        allocation, _ = self.allocation()
        queue_allocation(allocation)
        real_apply = AllocationService._apply_allocation_items

        def apply(current, items, **kwargs):
            result = real_apply(current, items, **kwargs)
            if items[0]["amount"] == 2:
                raise RuntimeError("second batch failed")
            return result

        with (
            patch.object(AllocationService, "_apply_allocation_items", apply),
            self.assertRaises(RuntimeError),
        ):
            execute_batched_allocation.func(allocation.pk)
        self.assertEqual(get_balance(self.operator), 100)
        self.assertEqual(get_balance(self.recipient), 0)
        self.assertFalse(PendingPointGrant.objects.exists())
        allocation.refresh_from_db()
        self.assertEqual(allocation.refunded_amount, 3)
        self.assertEqual(allocation.status, "failed")
        fail_allocation(allocation.pk, RuntimeError("repeated failure"))
        settle_funds(allocation)
        self.assertEqual(
            PointTransaction.objects.filter(transaction_type="refund").count(), 1
        )
        queue_allocation(allocation)
        queue_allocation(allocation)
        self.assertEqual(get_balance(self.operator), 97)
        execute_batched_allocation.func(allocation.pk)
        self.assertEqual(get_balance(self.operator), 97)
        self.assertEqual(get_balance(self.recipient), 1)
        self.assertEqual(PendingPointGrant.objects.get().amount, 2)
        self.assertEqual(
            PointTransaction.objects.filter(transaction_type="spend").aggregate(
                total=Sum("amount")
            )["total"],
            -6,
        )

    def test_failed_recipient_refunds_only_undistributed_portion(self):
        allocation, _ = self.allocation(invalid_recipient=True)
        queue_allocation(allocation)
        execute_batched_allocation.func(allocation.pk)
        allocation.refresh_from_db()
        self.assertEqual(allocation.status, "completed")
        self.assertEqual(allocation.total_amount, 2)
        self.assertEqual(allocation.failed_recipients, 1)
        self.assertEqual(allocation.refunded_amount, 1)
        self.assertEqual(get_balance(self.operator), 98)
        self.assertEqual(
            PointTransaction.objects.get(transaction_type="refund").amount, 1
        )
        execute_batched_allocation.func(allocation.pk)
        self.assertEqual(get_balance(self.operator), 98)

    def test_funding_and_refund_preserve_lot_expiry_and_group_separately(self):
        expiry = timezone.now() + timedelta(days=1)
        self.source.remaining_amount = 2
        self.source.expires_at = expiry
        self.source.save()
        later_expiry = expiry + timedelta(days=1)
        grant_points(
            owner=self.operator,
            amount=98,
            point_type="gift",
            reason="Second lot",
            expires_at=later_expiry,
        )
        allocation, _ = self.allocation((3,))
        queue_allocation(allocation)
        funding = load_funding(PointAllocation.objects.get(pk=allocation.pk))
        self.assertEqual(
            [(source.expires_at, amount) for source, amount in funding],
            [(expiry, 2), (later_expiry, 1)],
        )
        fail_allocation(allocation.pk, RuntimeError("fatal"))
        refunds = PointTransaction.objects.filter(transaction_type="refund").order_by(
            "pk"
        )
        self.assertEqual(
            [(entry.amount, entry.source.expires_at) for entry in refunds],
            [(2, expiry), (1, later_expiry)],
        )
        self.assertEqual(get_balance(self.operator), 100)
        response = self.client.get(
            "/api/v1/points/me/transactions",
            {"group_allocations": "true"},
            HTTP_AUTHORIZATION=f"Bearer {create_access_token(self.operator)}",
        )
        self.assertEqual(response.status_code, 200)
        rows = [
            row
            for row in response.json()["items"]
            if row["reference_id"] == f"allocation_{allocation.pk}"
        ]
        self.assertEqual(
            [
                (row["transaction_type"], row["amount"], row["merged_count"])
                for row in rows
            ],
            [("refund", 3, 2), ("spend", -3, 2)],
        )

    def test_expired_prepaid_lot_is_refunded_without_extending_expiry(self):
        allocation, _ = self.allocation()
        queue_allocation(allocation)
        expired = timezone.now() - timedelta(seconds=1)
        PointSource.objects.filter(pk=self.source.pk).update(expires_at=expired)
        with self.assertRaisesMessage(ValueError, "expired"):
            execute_batched_allocation.func(allocation.pk)
        refund = PointTransaction.objects.get(transaction_type="refund")
        self.assertEqual(refund.amount, 3)
        self.assertEqual(refund.source.expires_at, expired)
        self.assertEqual(get_balance(self.operator), 0)
        self.assertFalse(PendingPointGrant.objects.exists())

    def test_refunds_preserve_organization_owner_cash_type_and_gift_tag(self):
        organization = Organization.objects.create(
            name="Funding Org", slug="funding-org"
        )
        tag = Tag.objects.create(name="Funding tag", slug="funding-tag")
        for point_type in ("cash", "gift"):
            with self.subTest(point_type=point_type):
                self.source = grant_points(
                    owner=organization,
                    amount=10,
                    point_type=point_type,
                    reason="Organization fixture",
                    tag_slug=tag.slug if point_type == "gift" else None,
                )
                allocation, _ = self.allocation()
                queue_allocation(allocation)
                self.assertEqual(get_balance(organization, point_type=point_type), 7)
                fail_allocation(allocation.pk, RuntimeError("fatal"))
                refund = PointTransaction.objects.get(
                    transaction_type="refund",
                    reference_id=f"allocation_{allocation.pk}",
                )
                self.assertEqual(refund.wallet, self.source.wallet)
                self.assertEqual(refund.point_type, point_type)
                self.assertEqual(
                    refund.source.tag_id, tag.pk if point_type == "gift" else None
                )
                self.assertEqual(get_balance(organization, point_type=point_type), 10)
                self.assertEqual(get_balance(self.operator), 100)

    def test_legacy_unfunded_task_failure_does_not_refund_unpaid_points(self):
        allocation, _ = self.allocation()
        allocation.status = "queued"
        allocation.save(update_fields=["status"])
        execute_batched_allocation.enqueue(allocation.pk)
        self.spend(100)
        AllocationWorker(
            queue_names=["default"],
            interval=0,
            batch=True,
            backend_name="default",
            startup_delay=False,
            max_tasks=1,
            worker_id="legacy-funding",
        ).run()
        allocation.refresh_from_db()
        self.assertEqual(allocation.status, "failed")
        self.assertIn("Insufficient", allocation.execution_error)
        self.assertEqual(DBTaskResult.objects.get().status, "FAILED")
        self.assertEqual(get_balance(self.operator), 0)
        self.assertFalse(
            PointTransaction.objects.filter(transaction_type="refund").exists()
        )

    def test_zero_amount_task_and_funded_records_cannot_be_deleted(self):
        zero, _ = self.allocation((0,))
        queue_allocation(zero)
        execute_batched_allocation.func(zero.pk)
        zero.refresh_from_db()
        self.assertEqual(zero.status, "completed")
        self.assertEqual(get_balance(self.operator), 100)
        allocation, _ = self.allocation()
        queue_allocation(allocation)
        with self.assertRaises(ProtectedError):
            allocation.delete()

    def test_queued_prepaid_allocation_blocks_denomination_conversion(self):
        allocation, _ = self.allocation()
        queue_allocation(allocation)
        summary = build_conversion_summary(
            PointSource=PointSource,
            PendingPointGrant=PendingPointGrant,
            PointAllocation=PointAllocation,
            WithdrawalRequest=WithdrawalRequest,
            OutreachRecipient=OutreachRecipient,
        )
        self.assertEqual(summary.blocking_allocations, 1)

    @skipUnlessDBFeature("has_select_for_update_skip_locked")
    def test_sync_spending_and_queueing_compete_for_balance_without_overdraft(self):
        allocation, _ = self.allocation((80,))
        sync_allocation, items = self.allocation((80,), batch=False)
        barrier = Barrier(2, timeout=15)

        def run(asynchronous):
            try:
                barrier.wait()
                if asynchronous:
                    queue_allocation(allocation)
                else:
                    AllocationService.execute_allocation(sync_allocation, items)
                return True
            except (InsufficientPointsError, ApiError):
                return False
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, asynchronous) for asynchronous in (True, False)]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(sum(results), 1)
        self.assertEqual(get_balance(self.operator), 20)
        if results[0]:
            execute_batched_allocation.func(allocation.pk)
        self.assertEqual(get_balance(self.recipient), 80)
        self.assertEqual(get_balance(self.operator), 20)

    @skipUnlessDBFeature("has_select_for_update_skip_locked")
    def test_sync_allocation_can_spend_remaining_balance_while_worker_is_running(self):
        allocation, _ = self.allocation()
        queue_allocation(allocation)
        sync_allocation, items = self.allocation((97,), batch=False)
        started, release = Event(), Event()
        real_apply = AllocationService._apply_allocation_items

        def apply(current, recipients, **kwargs):
            result = real_apply(current, recipients, **kwargs)
            if current.pk == allocation.pk and not started.is_set():
                started.set()
                self.assertTrue(release.wait(15))
            return result

        def worker():
            try:
                AllocationWorker(
                    queue_names=["default"],
                    interval=0,
                    batch=True,
                    backend_name="default",
                    startup_delay=False,
                    max_tasks=1,
                    worker_id="prepaid-worker",
                ).run()
            finally:
                connections.close_all()

        def synchronous():
            try:
                return AllocationService.execute_allocation(sync_allocation, items)
            finally:
                connections.close_all()

        with (
            patch.object(AllocationService, "_apply_allocation_items", apply),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            future = pool.submit(worker)
            try:
                self.assertTrue(started.wait(15))
                self.assertEqual(get_balance(self.operator), 97)
                result = pool.submit(synchronous).result(timeout=5)
                self.assertEqual(result["total_points"], 97)
                self.assertEqual(get_balance(self.operator), 0)
            finally:
                release.set()
            future.result(timeout=15)
        self.assertEqual(DBTaskResult.objects.get().status, "SUCCEEDED")
        self.assertEqual(get_balance(self.operator), 0)
        self.assertEqual(get_balance(self.recipient), 98)
        self.assertEqual(PendingPointGrant.objects.get().amount, 2)
