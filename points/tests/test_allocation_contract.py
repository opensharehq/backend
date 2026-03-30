"""Contract tests for the real ClickHouse -> contributions -> allocation chain."""

from datetime import date
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse
from social_django.models import UserSocialAuth

from accounts.models import User
from points.allocation_services import AllocationService
from points.models import PointAllocation


class AllocationContractTests(TestCase):
    """Exercise the allocation flow through raw ClickHouse-shaped rows."""

    def setUp(self):
        """Create an authenticated user and a registered GitHub recipient."""
        self.operator = User.objects.create_user(
            username="allocation-contract-operator",
            email="operator@example.com",
            password="password123",
        )
        self.registered = User.objects.create_user(
            username="registered-recipient",
            email="registered@example.com",
            password="password123",
        )
        UserSocialAuth.objects.create(
            user=self.registered,
            provider="github",
            uid="12345",
        )
        self.client.login(username=self.operator.username, password="password123")

    @staticmethod
    def _mock_clickhouse_query(sql, parameters=None):
        """Return realistic raw rows for both contribution and label-user queries."""
        result = MagicMock()
        if "normalized_community_openrank" in sql:
            result.result_rows = [
                (12345, "registered-recipient", 2.0, [("repo-a", 2.0, 202401)]),
                (99999, "guest-recipient", 1.0, [("repo-a", 1.0, 202401)]),
            ]
            return result

        if "platforms.users" in sql:
            result.result_rows = [
                ("repo:github:test", ["github"], [[[12345, 99999]]]),
            ]
            return result

        msg = f"Unexpected SQL in contract test: {sql}"
        raise AssertionError(msg)

    @patch("chdb.services.ClickHouseDB.query")
    def test_preview_allocation_uses_real_chdb_and_registration_contract(
        self,
        mock_query,
    ):
        """Preview should preserve the raw CH row shape through to allocation output."""
        mock_query.side_effect = self._mock_clickhouse_query
        allocation = PointAllocation(
            project_scope={"tags": ["repo:github:test"]},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 1, 31),
            total_amount=900,
            adjustment_ratio=1.0,
            individual_adjustments={},
        )

        preview = AllocationService.preview_allocation(allocation)

        self.assertEqual(len(preview), 2)
        self.assertEqual(preview[0]["github_login"], "registered-recipient")
        self.assertTrue(preview[0]["is_registered"])
        self.assertEqual(preview[0]["user_id"], self.registered.id)
        self.assertEqual(preview[0]["calculated_points"], 600)
        self.assertEqual(preview[0]["adjusted_points"], 600)
        self.assertEqual(preview[1]["github_login"], "guest-recipient")
        self.assertFalse(preview[1]["is_registered"])
        self.assertEqual(preview[1]["adjusted_points"], 300)

    @patch("chdb.services.ClickHouseDB.query")
    def test_preview_api_serializes_real_chain_and_label_metadata(self, mock_query):
        """The preview API should expose both contribution rows and label-user metadata."""
        mock_query.side_effect = self._mock_clickhouse_query

        response = self.client.post(
            reverse("points:api_contribution_preview"),
            data={
                "project_scope": {"tags": ["repo:github:test"]},
                "start_month": "2024-01-01",
                "end_month": "2024-01-31",
                "total_amount": 900,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total_points"], 900)
        self.assertEqual(payload["total_recipients"], 2)
        self.assertEqual(len(payload["contributions"]), 2)
        self.assertIsInstance(payload["contributions"][0]["contribution_score"], float)
        self.assertEqual(
            payload["label_platforms_info"]["repo:github:test"]["platforms"],
            ["github"],
        )
        self.assertEqual(
            payload["label_platforms_info"]["repo:github:test"]["users"]["github"],
            [[12345, 99999]],
        )
