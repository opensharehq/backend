"""Contract tests for the real ClickHouse -> contributions -> allocation chain."""

from datetime import date
from unittest.mock import MagicMock, patch

from django.test import TestCase
from social_django.models import UserSocialAuth

from accounts.models import User
from accounts.services.jwt_tokens import create_access_token
from points.allocation_services import AllocationService
from points.models import PointAllocation, PointType
from points.services import grant_points


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
        # Create a point pool for the operator to use with new API
        grant_points(
            owner=self.operator,
            amount=10000,
            point_type=PointType.GIFT,
            reason="Contract test fixture",
        )
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.operator)}"
        }

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
        # Preview now returns actor_login (not github_login) and contribution_score only
        self.assertIn("actor_login", preview[0])
        self.assertTrue(preview[0]["is_registered"])
        self.assertEqual(preview[0]["user_id"], self.registered.id)
        self.assertIn("contribution_score", preview[0])
        # Preview no longer returns calculated_points or adjusted_points
        self.assertNotIn("calculated_points", preview[0])
        self.assertNotIn("adjusted_points", preview[0])
        self.assertFalse(preview[1]["is_registered"])
        self.assertNotIn("adjusted_points", preview[1])

    @patch("chdb.services.ClickHouseDB.query")
    def test_preview_api_serializes_real_chain_and_label_metadata(self, mock_query):
        """The preview API should expose contribution rows with contribution_to_points_ratio."""
        mock_query.side_effect = self._mock_clickhouse_query

        response = self.client.post(
            "/api/v1/points/allocations/preview",
            data={
                "source_selector": {
                    "owner_type": "user",
                    "point_type": "gift",
                    "tag_slug": None,
                },
                "project_scope": {"tags": ["repo:github:test"]},
                "start_month": "2024-01-01",
                "end_month": "2024-01-31",
            },
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        # New API returns contribution_to_points_ratio and preview list
        self.assertEqual(
            payload["contribution_to_points_ratio"],
            AllocationService.CONTRIBUTION_TO_POINTS_RATIO,
        )
        self.assertEqual(payload["total_recipients"], 2)
        self.assertEqual(len(payload["preview"]), 2)
        self.assertIsInstance(payload["preview"][0]["contribution_score"], float)
        # No longer returns total_points in preview response
        self.assertNotIn("total_points", payload)
