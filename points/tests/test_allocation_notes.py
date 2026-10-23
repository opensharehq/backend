"""Allocation notes survive both immediate and deferred point delivery."""

from django.test import TestCase
from social_django.models import UserSocialAuth

from accounts.models import User
from accounts.services.jwt_tokens import create_access_token
from points.allocation_services import AllocationService
from points.models import (
    PendingPointGrant,
    PointAllocation,
    PointTransaction,
    PointType,
)
from points.services import get_balance, grant_points


class AllocationNoteTests(TestCase):
    def setUp(self):
        self.operator = User.objects.create_user(username="note-operator")
        self.recipient = User.objects.create_user(username="note-recipient")
        grant_points(
            owner=self.operator,
            amount=10000,
            point_type=PointType.GIFT,
            reason="Note test fixture",
        )
        self.headers = self.auth_headers(self.operator)
        self.payload = {
            "source_selector": {"owner_type": "user", "point_type": "gift"},
            "project_scope": {"tags": ["repo:test"]},
            "start_month": "2024-01-01",
            "end_month": "2024-02-01",
            "total_amount": 200,
            "allocations": [
                {
                    "actor_id": "123",
                    "actor_login": "note-recipient",
                    "platform": "github",
                    "is_registered": True,
                    "user_id": self.recipient.id,
                    "contribution_score": 1,
                    "amount": 100,
                },
                {
                    "actor_id": "456",
                    "actor_login": "future-recipient",
                    "platform": "github",
                    "is_registered": False,
                    "contribution_score": 1,
                    "amount": 100,
                },
            ],
        }

    @staticmethod
    def auth_headers(user):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_access_token(user)}"}

    def execute(self):
        return self.client.post(
            "/api/v1/points/allocations",
            data=self.payload,
            content_type="application/json",
            **self.headers,
        )

    def assert_recipient_history(self, recipient, allocation, reason):
        response = self.client.get(
            "/api/v1/points/me/transactions", **self.auth_headers(recipient)
        )
        self.assertEqual(response.status_code, 200)
        transactions = [
            item
            for item in response.json()["items"]
            if item["reference_id"] == f"allocation_{allocation.id}"
        ]
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]["description"], reason)
        self.assertEqual(transactions[0]["amount"], 100)
        summary = self.client.get(
            f"/api/v1/points/allocations/{allocation.id}/summary",
            **self.auth_headers(recipient),
        )
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["note"], allocation.note)

    def test_40_character_note_reaches_immediate_and_deferred_recipients(self):
        note = "谢🎉" * 20
        self.payload["note"] = note
        response = self.execute()
        self.assertEqual(response.status_code, 201)
        allocation = PointAllocation.objects.get()
        self.assertEqual(allocation.note, note)
        self.assertEqual(response.json()["allocation"]["note"], note)
        reason = f"贡献度奖励 (2024-01-01 - 2024-02-01)；备注：{note}"
        self.assert_recipient_history(self.recipient, allocation, reason)

        detail = self.client.get(
            f"/api/v1/points/allocations/{allocation.id}", **self.headers
        )
        self.assertEqual(detail.json()["note"], note)
        grant = PendingPointGrant.objects.get(allocation=allocation)
        self.assertEqual(grant.reason, reason)
        future_recipient = User.objects.create_user(username="future-recipient")
        UserSocialAuth.objects.create(
            user=future_recipient, provider="github", uid="456"
        )
        AllocationService.claim_pending_points(future_recipient)
        grant.refresh_from_db()
        self.assertTrue(grant.is_claimed)
        self.assert_recipient_history(future_recipient, allocation, reason)

    def test_omitted_empty_and_whitespace_notes_preserve_existing_description(self):
        for note_fields in ({}, {"note": ""}, {"note": "   "}):
            with self.subTest(note_fields=note_fields):
                self.payload.update(note_fields)
                response = self.execute()
                self.assertEqual(response.status_code, 201)
                allocation = PointAllocation.objects.get(
                    id=response.json()["allocation"]["id"]
                )
                self.assertEqual(allocation.note, "")
                self.assertEqual(
                    allocation.pending_grants.get().reason,
                    "贡献度奖励 (2024-01-01 - 2024-02-01)",
                )
                self.assert_recipient_history(
                    self.recipient,
                    allocation,
                    "贡献度奖励 (2024-01-01 - 2024-02-01)",
                )

    def test_note_is_trimmed_before_storage(self):
        self.payload["note"] = "  感谢本月维护  "
        response = self.execute()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(PointAllocation.objects.get().note, "感谢本月维护")

    def test_invalid_notes_are_rejected_without_moving_points(self):
        initial_balance = get_balance(self.operator)
        initial_transactions = PointTransaction.objects.count()
        for note in ("a" * 41, "奖" * 41, "🎉" * 41, None, 123):
            with self.subTest(note=note):
                self.payload["note"] = note
                response = self.execute()
                self.assertEqual(response.status_code, 422)
                self.assertFalse(PointAllocation.objects.exists())
                self.assertFalse(PendingPointGrant.objects.exists())
                self.assertEqual(get_balance(self.operator), initial_balance)
                self.assertEqual(PointTransaction.objects.count(), initial_transactions)
