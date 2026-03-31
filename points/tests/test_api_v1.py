"""Tests for points API endpoints."""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Organization, OrganizationMembership
from accounts.services.jwt_tokens import create_access_token
from points.models import PointAllocation, PointType, WithdrawalStatus
from points.services import grant_points


class PointsApiV1Tests(TestCase):
    """Validate wallet, withdrawal, and allocation APIs."""

    def setUp(self):
        """Create reusable points fixtures."""
        User = get_user_model()
        self.user = User.objects.create_user(
            username="points_user",
            email="points_user@example.com",
            password="StrongPass123!",
        )
        self.other_user = User.objects.create_user(
            username="points_peer",
            email="points_peer@example.com",
            password="StrongPass123!",
        )
        self.organization = Organization.objects.create(
            name="Points Org",
            slug="points-org",
        )
        OrganizationMembership.objects.create(
            user=self.user,
            organization=self.organization,
            role=OrganizationMembership.Role.OWNER,
        )
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.user)}"
        }

        grant_points(
            owner=self.user,
            amount=5000,
            point_type=PointType.CASH,
            reason="Cash fixture",
            created_by=self.user,
        )
        grant_points(
            owner=self.user,
            amount=1200,
            point_type=PointType.GIFT,
            reason="Gift fixture",
            created_by=self.user,
        )
        grant_points(
            owner=self.organization,
            amount=900,
            point_type=PointType.CASH,
            reason="Organization fixture",
            created_by=self.user,
        )

    def test_user_wallet_and_withdrawal_flow(self):
        """Users should be able to read wallet state, create, and cancel withdrawals."""
        wallet_response = self.client.get("/api/v1/points/me/wallet", **self.headers)
        self.assertEqual(wallet_response.status_code, 200)
        self.assertEqual(wallet_response.json()["balance"]["cash"], 5000)

        create_response = self.client.post(
            "/api/v1/points/me/withdrawals",
            {
                "amount": 1000,
                "real_name": "API User",
                "phone": "13800138000",
                "id_card": "11010519491231002X",
                "bank_name": "Bank of Test",
                "bank_account": "6222021234567890123",
            },
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(create_response.status_code, 200)
        withdrawal_id = create_response.json()["id"]
        self.assertEqual(create_response.json()["status"], WithdrawalStatus.PENDING)

        cancel_response = self.client.post(
            f"/api/v1/points/me/withdrawals/{withdrawal_id}/cancel",
            **self.headers,
        )
        self.assertEqual(cancel_response.status_code, 200)
        self.assertEqual(cancel_response.json()["status"], WithdrawalStatus.CANCELLED)
        list_response = self.client.get("/api/v1/points/me/withdrawals", **self.headers)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(
            list_response.json()["items"][0]["status"], WithdrawalStatus.CANCELLED
        )

    def test_pool_listing_and_allocation_execute(self):
        """Allocation APIs should preview and execute against a stable source selector."""
        pools_response = self.client.get("/api/v1/points/pools", **self.headers)
        self.assertEqual(pools_response.status_code, 200)
        self.assertTrue(
            any(
                item["owner_type"] == "organization"
                for item in pools_response.json()["items"]
            )
        )
        user_gift_pool = next(
            item
            for item in pools_response.json()["items"]
            if item["owner_type"] == "user" and item["point_type"] == PointType.GIFT
        )
        self.assertIn("source_selector", user_gift_pool)
        self.assertEqual(user_gift_pool["source_selector"]["owner_type"], "user")

        payload = {
            "source_selector": user_gift_pool["source_selector"],
            "project_scope": {"tags": ["repo:test/example"], "operation": "AND"},
            "start_month": "2025-01-01",
            "end_month": "2025-01-01",
            "total_amount": 300,
            "adjustment_ratio": 1.0,
            "individual_adjustments": {},
        }

        mocked_contributions = [
            {
                "github_id": "123",
                "github_login": self.other_user.username,
                "email": self.other_user.email,
                "contribution_score": Decimal("10.0"),
                "is_registered": True,
                "user_id": self.other_user.id,
            }
        ]

        with patch(
            "contributions.services.ContributionService.get_contributions",
            return_value=mocked_contributions,
        ):
            preview_response = self.client.post(
                "/api/v1/points/allocations/preview",
                payload,
                content_type="application/json",
                **self.headers,
            )
            self.assertEqual(preview_response.status_code, 200)
            self.assertEqual(preview_response.json()["total_points"], 300)
            self.assertEqual(
                preview_response.json()["source_selector"],
                user_gift_pool["source_selector"],
            )

            execute_response = self.client.post(
                "/api/v1/points/allocations",
                payload,
                content_type="application/json",
                **self.headers,
            )
        self.assertEqual(execute_response.status_code, 200)
        allocation_id = execute_response.json()["allocation"]["id"]

        allocation = PointAllocation.objects.get(id=allocation_id)
        self.assertEqual(allocation.status, "completed")
        self.assertEqual(execute_response.json()["result"]["total_points"], 300)
        detail_response = self.client.get(
            f"/api/v1/points/allocations/{allocation_id}", **self.headers
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["id"], allocation_id)
        self.assertEqual(
            detail_response.json()["source_selector"], user_gift_pool["source_selector"]
        )

    def test_organization_wallet_endpoint_is_available_to_members(self):
        """Organization members should be able to view wallet summaries."""
        response = self.client.get(
            f"/api/v1/points/organizations/{self.organization.slug}/wallet",
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["organization"]["slug"], self.organization.slug
        )
        self.assertEqual(response.json()["balance"]["cash"], 900)
