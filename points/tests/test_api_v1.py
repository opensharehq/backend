"""Tests for points API endpoints."""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from accounts.models import Organization, OrganizationMembership
from accounts.services.jwt_tokens import create_access_token
from contributions.services import ContributionDataUnavailableError
from points.models import PointAllocation, PointType, PointWallet, WithdrawalStatus
from points.services import grant_points


class PointsApiV1Tests(TestCase):
    """Validate wallet, withdrawal, and allocation APIs."""

    @staticmethod
    def _wallet_exists(owner) -> bool:
        content_type = ContentType.objects.get_for_model(owner)
        return PointWallet.objects.filter(
            content_type=content_type,
            object_id=owner.id,
        ).exists()

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
        self.no_wallet_user = User.objects.create_user(
            username="points_nowallet",
            email="points_nowallet@example.com",
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
        self.assertEqual(create_response.status_code, 201)
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

        # Preview request - simplified format without total_amount/adjustment_ratio
        preview_payload = {
            "source_selector": user_gift_pool["source_selector"],
            "project_scope": {"tags": ["repo:test/example"], "operation": "AND"},
            "start_month": "2025-01-01",
            "end_month": "2025-01-01",
        }

        mocked_contributions = [
            {
                "platform": "GitHub",
                "actor_id": "123",
                "actor_login": self.other_user.username,
                "email": self.other_user.email,
                "contribution_score": Decimal("10.0"),
                "is_registered": True,
                "user_id": self.other_user.id,
            }
        ]

        with patch(
            "chdb.services.query_contributions_with_operators",
            return_value=mocked_contributions,
        ):
            preview_response = self.client.post(
                "/api/v1/points/allocations/preview",
                preview_payload,
                content_type="application/json",
                **self.headers,
            )
            self.assertEqual(preview_response.status_code, 200)
            # New response format
            self.assertIn("contribution_to_points_ratio", preview_response.json())
            self.assertEqual(preview_response.json()["total_recipients"], 1)
            self.assertIn("preview", preview_response.json())
            self.assertEqual(
                preview_response.json()["source_selector"],
                user_gift_pool["source_selector"],
            )

            # Execute request - new format with allocations array
            execute_payload = {
                "source_selector": user_gift_pool["source_selector"],
                "project_scope": {"tags": ["repo:test/example"], "operation": "AND"},
                "start_month": "2025-01-01",
                "end_month": "2025-01-01",
                "adjustment_ratio": 1.0,
                "total_amount": 300,
                "allocations": [
                    {
                        "actor_id": "123",
                        "actor_login": self.other_user.username,
                        "platform": "GitHub",
                        "email": self.other_user.email,
                        "is_registered": True,
                        "user_id": self.other_user.id,
                        "contribution_score": 10.0,
                        "amount": 300,
                    }
                ],
            }

            execute_response = self.client.post(
                "/api/v1/points/allocations",
                execute_payload,
                content_type="application/json",
                **self.headers,
            )
        self.assertEqual(execute_response.status_code, 201)
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

    def test_wallet_read_does_not_create_wallet_for_zero_balance_user(self):
        """Wallet reads should stay side-effect free when no wallet exists yet."""
        headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.no_wallet_user)}"
        }
        self.assertFalse(self._wallet_exists(self.no_wallet_user))

        response = self.client.get("/api/v1/points/me/wallet", **headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["wallet_id"], None)
        self.assertEqual(response.json()["balance"]["total"], 0)
        self.assertFalse(self._wallet_exists(self.no_wallet_user))

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

    def test_organization_wallet_read_does_not_create_wallet_for_zero_balance_org(self):
        """Organization wallet reads should stay side-effect free for empty orgs."""
        empty_org = Organization.objects.create(name="Empty Org", slug="empty-org")
        OrganizationMembership.objects.create(
            user=self.user,
            organization=empty_org,
            role=OrganizationMembership.Role.OWNER,
        )
        self.assertFalse(self._wallet_exists(empty_org))

        response = self.client.get(
            f"/api/v1/points/organizations/{empty_org.slug}/wallet",
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["wallet_id"], None)
        self.assertEqual(response.json()["balance"]["total"], 0)
        self.assertFalse(self._wallet_exists(empty_org))

    @patch(
        "chdb.services.query_contributions_with_operators",
        side_effect=ContributionDataUnavailableError(
            "Contribution data is currently unavailable."
        ),
    )
    def test_allocation_preview_rejects_unavailable_contribution_data(self, _mocked):
        """Allocation preview should return a stable 503 when contribution data is unavailable."""
        payload = {
            "source_selector": {
                "owner_type": "user",
                "point_type": PointType.GIFT,
                "tag_slug": None,
            },
            "project_scope": {"tags": ["repo:test/example"], "operation": "AND"},
            "start_month": "2025-01-01",
            "end_month": "2025-01-01",
        }

        response = self.client.post(
            "/api/v1/points/allocations/preview",
            payload,
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "contribution_data_unavailable")
        self.assertEqual(
            response.json()["message"],
            "Contribution data is currently unavailable.",
        )
        self.assertIsNone(response.json()["detail"])

    def test_allocation_execute_rejects_mismatched_total_amount(self):
        """Allocation execution should reject when sum of amounts != total_amount."""
        payload = {
            "source_selector": {
                "owner_type": "user",
                "point_type": PointType.GIFT,
                "tag_slug": None,
            },
            "project_scope": {"tags": ["repo:test/example"], "operation": "AND"},
            "start_month": "2025-01-01",
            "end_month": "2025-01-01",
            "total_amount": 300,
            "adjustment_ratio": 1.0,
            "allocations": [
                {
                    "actor_id": "123",
                    "actor_login": "someone",
                    "platform": "GitHub",
                    "email": "someone@example.com",
                    "is_registered": False,
                    "contribution_score": 10.0,
                    "amount": 200,
                }
            ],
        }

        response = self.client.post(
            "/api/v1/points/allocations",
            payload,
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "validation_error")
        self.assertEqual(PointAllocation.objects.count(), 0)

    def test_allocation_rejects_invalid_date_range(self):
        """Allocation date ranges must be chronological."""
        payload = {
            "source_selector": {
                "owner_type": "user",
                "point_type": PointType.GIFT,
                "tag_slug": None,
            },
            "project_scope": {"tags": ["repo:test/example"], "operation": "AND"},
            "start_month": "2025-02-01",
            "end_month": "2025-01-01",
        }

        response = self.client.post(
            "/api/v1/points/allocations/preview",
            payload,
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "validation_error")

    def test_preview_operators_length_mismatch(self):
        """operators 长度与 tags 不匹配时返回 422."""
        payload = {
            "source_selector": {
                "owner_type": "user",
                "point_type": PointType.GIFT,
                "tag_slug": None,
            },
            "project_scope": {
                "tags": ["A", "B", "C"],
                "operators": ["OR"],  # 应为2个，只给了1个
                "operation": "OR",
            },
            "start_month": "2024-01-01",
            "end_month": "2024-02-01",
        }

        response = self.client.post(
            "/api/v1/points/allocations/preview",
            payload,
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(response.status_code, 422)

    def test_preview_operators_invalid_value(self):
        """operators 中包含无效值时返回 422."""
        payload = {
            "source_selector": {
                "owner_type": "user",
                "point_type": PointType.GIFT,
                "tag_slug": None,
            },
            "project_scope": {
                "tags": ["A", "B"],
                "operators": ["INVALID"],
                "operation": "OR",
            },
            "start_month": "2024-01-01",
            "end_month": "2024-02-01",
        }

        response = self.client.post(
            "/api/v1/points/allocations/preview",
            payload,
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(response.status_code, 422)

    @patch(
        "chdb.services.query_contributions_with_operators",
        return_value=[],
    )
    def test_preview_without_operators_backward_compatible(self, _mocked):
        """不传 operators 字段时统一走 query_contributions_with_operators."""
        payload = {
            "source_selector": {
                "owner_type": "user",
                "point_type": PointType.GIFT,
                "tag_slug": None,
            },
            "project_scope": {
                "tags": ["repo:test/example"],
                "operation": "AND",
            },
            "start_month": "2025-01-01",
            "end_month": "2025-01-01",
        }

        response = self.client.post(
            "/api/v1/points/allocations/preview",
            payload,
            content_type="application/json",
            **self.headers,
        )

        self.assertNotEqual(response.status_code, 422)

    def test_organization_cancel_requires_withdrawal_to_match_slug(self):
        """Organization withdrawal cancellation should enforce the slug-resource binding."""
        create_response = self.client.post(
            f"/api/v1/points/organizations/{self.organization.slug}/withdrawals",
            {
                "amount": 200,
                "real_name": "Org Owner",
                "phone": "13800138000",
                "id_card": "11010519491231002X",
                "bank_name": "Bank of Test",
                "bank_account": "6222021234567890123",
            },
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(create_response.status_code, 201)
        withdrawal_id = create_response.json()["id"]

        other_org = Organization.objects.create(name="Other Org", slug="other-org")
        OrganizationMembership.objects.create(
            user=self.user,
            organization=other_org,
            role=OrganizationMembership.Role.OWNER,
        )

        mismatch_response = self.client.post(
            f"/api/v1/points/organizations/{other_org.slug}/withdrawals/{withdrawal_id}/cancel",
            **self.headers,
        )
        self.assertEqual(mismatch_response.status_code, 404)
