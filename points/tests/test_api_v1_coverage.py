"""Additional coverage for points API v1 edge cases."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase
from django.utils import timezone

from accounts.models import Organization, OrganizationMembership, WithdrawalAccount
from accounts.services.jwt_tokens import create_access_token
from config.api_common import ApiError
from points import api_v1
from points.models import (
    PendingPointGrant,
    PointAllocation,
    PointTransaction,
    PointType,
    Tag,
    TransactionType,
    WithdrawalRequest,
    WithdrawalStatus,
)
from points.services import grant_points
from shenbianyun.models import SignedUser


class PointsApiV1CoverageTests(TestCase):
    """Exercise points API branches not covered by end-to-end flows."""

    def setUp(self):
        """Create reusable users, organization, and point pools."""
        User = get_user_model()
        self.user = User.objects.create_user(
            username="points-coverage",
            email="points-coverage@example.com",
            password="StrongPass123!",
        )
        self.other_user = User.objects.create_user(
            username="points-coverage-other",
            email="points-coverage-other@example.com",
            password="StrongPass123!",
        )
        self.member_user = User.objects.create_user(
            username="points-coverage-member",
            email="points-coverage-member@example.com",
            password="StrongPass123!",
        )
        self.org = Organization.objects.create(name="Coverage Org", slug="cov-org")
        OrganizationMembership.objects.create(
            user=self.user,
            organization=self.org,
            role=OrganizationMembership.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            user=self.member_user,
            organization=self.org,
            role=OrganizationMembership.Role.MEMBER,
        )
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.user)}"
        }
        self.member_headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.member_user)}"
        }
        self.other_headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.other_user)}"
        }
        self.cash_source = grant_points(
            owner=self.user,
            amount=1000,
            point_type=PointType.CASH,
            reason="Coverage cash fixture",
            created_by=self.user,
        )
        self.gift_source = grant_points(
            owner=self.user,
            amount=700,
            point_type=PointType.GIFT,
            reason="Coverage gift fixture",
            created_by=self.user,
        )
        self.org_cash_source = grant_points(
            owner=self.org,
            amount=800,
            point_type=PointType.CASH,
            reason="Coverage org cash fixture",
            created_by=self.user,
        )

    def test_parse_request_data_handles_invalid_and_non_object_json(self):
        """JSON parsing should reject invalid and non-object bodies."""
        factory = RequestFactory()
        invalid_request = factory.post(
            "/api/v1/points/me/withdrawals",
            data=b"{",
            content_type="application/json",
        )
        list_request = factory.post(
            "/api/v1/points/me/withdrawals",
            data=b"[]",
            content_type="application/json",
        )
        form_request = factory.post(
            "/api/v1/points/me/withdrawals",
            data={"amount": "200"},
        )

        with self.assertRaises(ApiError) as invalid_cm:
            api_v1._parse_request_data(invalid_request)
        self.assertEqual(invalid_cm.exception.code, "invalid_json")

        with self.assertRaises(ApiError) as list_cm:
            api_v1._parse_request_data(list_request)
        self.assertEqual(list_cm.exception.code, "invalid_json")

        data, invoice = api_v1._parse_request_data(form_request)
        self.assertEqual(data["amount"], "200")
        self.assertIsNone(invoice)

    def test_validation_helpers_cover_source_scope_and_execute_errors(self):
        """Allocation validators should expose stable ApiError branches."""
        invalid_owner = api_v1.SourceSelectorSchema(
            owner_type="team",
            point_type=PointType.GIFT,
        )
        invalid_point_type = api_v1.SourceSelectorSchema(
            owner_type="user",
            point_type="bonus",
        )
        cash_with_tag = api_v1.SourceSelectorSchema(
            owner_type="user",
            point_type=PointType.CASH,
            tag_slug="repo",
        )
        org_without_slug = api_v1.SourceSelectorSchema(
            owner_type="organization",
            point_type=PointType.CASH,
        )

        for selector in (
            invalid_owner,
            invalid_point_type,
            cash_with_tag,
            org_without_slug,
        ):
            with self.assertRaises(ApiError):
                api_v1._validate_source_selector(selector)

        with self.assertRaises(ApiError):
            api_v1._validate_allocation_scope("project_scope", None, required=True)
        with self.assertRaises(ApiError):
            api_v1._validate_allocation_scope(
                "project_scope",
                api_v1.AllocationScopeSchema(tags=[], operation="AND"),
                required=True,
            )
        with self.assertRaises(ApiError):
            api_v1._validate_allocation_scope(
                "project_scope",
                api_v1.AllocationScopeSchema(tags=["repo"], operation="BAD"),
                required=True,
            )
        self.assertIsNone(
            api_v1._validate_allocation_scope("user_scope", None, required=False)
        )

        base_payload = {
            "source_selector": {"owner_type": "user", "point_type": PointType.GIFT},
            "project_scope": {"tags": ["repo"], "operation": "AND"},
            "start_month": date(2025, 1, 1),
            "end_month": date(2025, 1, 1),
            "adjustment_ratio": 1.0,
            "allocations": [
                {
                    "actor_id": "1",
                    "actor_login": "alice",
                    "platform": "GitHub",
                    "is_registered": False,
                    "contribution_score": 1.0,
                    "amount": 100,
                }
            ],
        }
        invalid_execute_payloads = [
            {**base_payload, "total_amount": 0},
            {
                **base_payload,
                "total_amount": 100,
                "start_month": date(2025, 2, 1),
                "end_month": date(2025, 1, 1),
            },
            {**base_payload, "total_amount": 100, "allocations": []},
            {
                **base_payload,
                "total_amount": 100,
                "allocations": [
                    {**base_payload["allocations"][0], "amount": -1},
                ],
            },
        ]
        for raw_payload in invalid_execute_payloads:
            payload = api_v1.AllocationExecuteRequestSchema(**raw_payload)
            with self.assertRaises(ApiError):
                api_v1._validate_execute_request(payload)

    def test_source_pool_resolution_covers_org_and_not_found_paths(self):
        """Source selector resolution should cover organization and empty pools."""
        org_selector = api_v1.SourceSelectorSchema(
            owner_type="organization",
            owner_slug=self.org.slug,
            point_type=PointType.CASH,
        )

        source, balance = api_v1._resolve_source_pool(self.user, org_selector)

        self.assertEqual(source.id, self.org_cash_source.id)
        self.assertEqual(balance, 800)

        with self.assertRaises(ApiError):
            api_v1._resolve_source_pool(
                self.member_user,
                api_v1.SourceSelectorSchema(
                    owner_type="organization",
                    owner_slug=self.org.slug,
                    point_type=PointType.CASH,
                ),
            )

        with self.assertRaises(ApiError):
            api_v1._get_org_member_or_error(self.other_user, self.org.slug)

        with self.assertRaises(ApiError):
            api_v1._resolve_source_pool(
                self.other_user,
                api_v1.SourceSelectorSchema(
                    owner_type="user",
                    point_type=PointType.CASH,
                ),
            )

        with self.assertRaises(ApiError):
            api_v1._resolve_source_pool(
                self.user,
                api_v1.SourceSelectorSchema(
                    owner_type="user",
                    point_type=PointType.GIFT,
                    tag_slug="missing",
                ),
            )

    def test_service_error_mapping_covers_exact_and_fallback_messages(self):
        """Chinese service errors should map to stable API-facing errors."""
        messages = [
            "现金积分不足：需要 300，可用 100",
            "提现申请不存在: 42",
            "只能取消待审核的提现申请，当前状态: 已拒绝",
            "提现申请状态无效: bad",
            "您有待处理的提现申请，请等待处理完成后再申请",
            "您没有权限取消此提现申请",
            "提现金额必须大于 0",
            "unknown failure",
        ]

        for message in messages:
            with self.assertRaises(ApiError):
                api_v1._raise_points_service_error(message)

    def test_withdrawal_account_create_flow_serializes_linked_account(self):
        """The new withdrawal-account flow should serialize masked linked accounts."""
        SignedUser.objects.create(
            offset_id="sign-coverage",
            name="Coverage User",
            mobile="13800138000",
            id_card="11010519491231002X",
            provider_id=1,
            state=1,
        )
        account_response = self.client.post(
            "/api/v1/me/withdrawal-accounts",
            {
                "account_type": "domestic",
                "real_name": "Coverage User",
                "id_card": "11010519491231002X",
                "phone": "13800138000",
                "bank_card": "6222 0212 3456 7890 123",
            },
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(account_response.status_code, 201)
        account_id = account_response.json()["id"]

        withdrawal_response = self.client.post(
            "/api/v1/points/me/withdrawals",
            {"withdrawal_account_id": account_id, "amount": 200},
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(withdrawal_response.status_code, 201)
        payload = withdrawal_response.json()
        self.assertEqual(payload["withdrawal_account_id"], account_id)
        self.assertNotEqual(payload["bank_account"], "6222021234567890123")

    def test_withdrawal_create_new_flow_validation_and_service_errors(self):
        """New withdrawal-account requests should cover validation and service errors."""
        invalid_amount_response = self.client.post(
            "/api/v1/points/me/withdrawals",
            {"withdrawal_account_id": 999, "amount": "bad"},
            content_type="application/json",
            **self.headers,
        )
        low_amount_response = self.client.post(
            "/api/v1/points/me/withdrawals",
            {"withdrawal_account_id": 999, "amount": 100},
            content_type="application/json",
            **self.headers,
        )
        missing_account_response = self.client.post(
            "/api/v1/points/me/withdrawals",
            {"withdrawal_account_id": 999, "amount": 200},
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(invalid_amount_response.status_code, 422)
        self.assertEqual(low_amount_response.status_code, 422)
        self.assertEqual(missing_account_response.status_code, 422)

        account = WithdrawalAccount.objects.create(
            user=self.user,
            account_type="international",
            real_name="Coverage User",
            currency="USD",
            swift_account="US1234567890",
        )
        first_response = self.client.post(
            "/api/v1/points/me/withdrawals",
            {"withdrawal_account_id": account.id, "amount": 200},
            content_type="application/json",
            **self.headers,
        )
        pending_response = self.client.post(
            "/api/v1/points/me/withdrawals",
            {"withdrawal_account_id": account.id, "amount": 200},
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(pending_response.status_code, 409)
        self.assertEqual(pending_response.json()["code"], "pending_withdrawal_exists")

    def test_legacy_withdrawal_form_validation_value_error_and_pending(self):
        """Legacy withdrawal requests should cover form and service error branches."""
        invalid_form_response = self.client.post(
            "/api/v1/points/me/withdrawals",
            {"amount": 200},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(invalid_form_response.status_code, 422)

        with patch(
            "points.api_v1.services.create_withdrawal_request",
            side_effect=ValueError("custom validation"),
        ):
            value_error_response = self.client.post(
                "/api/v1/points/me/withdrawals",
                {
                    "amount": 200,
                    "real_name": "Coverage User",
                    "phone": "13800138000",
                    "id_card": "11010519491231002X",
                    "bank_name": "Bank",
                    "bank_account": "6222021234567890123",
                },
                content_type="application/json",
                **self.headers,
            )
        self.assertEqual(value_error_response.status_code, 422)

        create_response = self.client.post(
            "/api/v1/points/me/withdrawals",
            {
                "amount": 200,
                "real_name": "Coverage User",
                "phone": "13800138000",
                "id_card": "11010519491231002X",
                "bank_name": "Bank",
                "bank_account": "6222021234567890123",
            },
            content_type="application/json",
            **self.headers,
        )
        pending_response = self.client.post(
            "/api/v1/points/me/withdrawals",
            {
                "amount": 200,
                "real_name": "Coverage User",
                "phone": "13800138000",
                "id_card": "11010519491231002X",
                "bank_name": "Bank",
                "bank_account": "6222021234567890123",
            },
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(pending_response.status_code, 409)

    def test_transaction_and_withdrawal_list_filters_cover_empty_and_filtered_paths(
        self,
    ):
        """Transaction endpoints should cover empty wallets and filters."""
        no_wallet_headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.other_user)}"
        }
        empty_response = self.client.get(
            "/api/v1/points/me/transactions",
            **no_wallet_headers,
        )
        filtered_response = self.client.get(
            "/api/v1/points/me/transactions?point_type=cash&transaction_type=earn",
            **self.headers,
        )
        org_transactions_response = self.client.get(
            f"/api/v1/points/organizations/{self.org.slug}/transactions?point_type=cash&transaction_type=earn",
            **self.headers,
        )
        org_withdrawals_response = self.client.get(
            f"/api/v1/points/organizations/{self.org.slug}/withdrawals",
            **self.headers,
        )

        self.assertEqual(empty_response.status_code, 200)
        self.assertEqual(empty_response.json()["items"], [])
        self.assertEqual(filtered_response.status_code, 200)
        self.assertEqual(filtered_response.json()["filters"]["point_type"], "cash")
        self.assertEqual(org_transactions_response.status_code, 200)
        self.assertEqual(
            org_transactions_response.json()["membership"]["role"], "owner"
        )
        for params in (
            {"point_type": PointType.CASH},
            {"transaction_type": TransactionType.EARN},
        ):
            filtered_org = self.client.get(
                f"/api/v1/points/organizations/{self.org.slug}/transactions",
                params,
                **self.headers,
            )
            self.assertEqual(filtered_org.status_code, 200)
        self.assertEqual(org_withdrawals_response.status_code, 200)
        self.assertEqual(org_withdrawals_response.json()["items"], [])

    def test_organization_endpoints_cover_permission_and_error_paths(self):
        """Organization endpoints should reject non-admin writes and map errors."""
        member_create_response = self.client.post(
            f"/api/v1/points/organizations/{self.org.slug}/withdrawals",
            {
                "amount": 200,
                "real_name": "Coverage Org",
                "phone": "13800138000",
                "id_card": "11010519491231002X",
                "bank_name": "Bank",
                "bank_account": "6222021234567890123",
            },
            content_type="application/json",
            **self.member_headers,
        )
        invalid_form_response = self.client.post(
            f"/api/v1/points/organizations/{self.org.slug}/withdrawals",
            {"amount": 200},
            content_type="application/json",
            **self.headers,
        )
        with patch(
            "points.api_v1.services.create_withdrawal_request",
            side_effect=ValueError("bad org withdrawal"),
        ):
            value_error_response = self.client.post(
                f"/api/v1/points/organizations/{self.org.slug}/withdrawals",
                {
                    "amount": 200,
                    "real_name": "Coverage Org",
                    "phone": "13800138000",
                    "id_card": "11010519491231002X",
                    "bank_name": "Bank",
                    "bank_account": "6222021234567890123",
                },
                content_type="application/json",
                **self.headers,
            )
        missing_cancel_response = self.client.post(
            f"/api/v1/points/organizations/{self.org.slug}/withdrawals/999/cancel",
            **self.headers,
        )
        create_response = self.client.post(
            f"/api/v1/points/organizations/{self.org.slug}/withdrawals",
            {
                "amount": 200,
                "real_name": "Coverage Org",
                "phone": "13800138000",
                "id_card": "11010519491231002X",
                "bank_name": "Bank",
                "bank_account": "6222021234567890123",
            },
            content_type="application/json",
            **self.headers,
        )
        withdrawal_id = create_response.json()["id"]
        with patch(
            "points.api_v1.services.cancel_withdrawal",
            side_effect=api_v1.services.WithdrawalError("提现申请状态无效: bad"),
        ):
            cancel_error_response = self.client.post(
                f"/api/v1/points/organizations/{self.org.slug}/withdrawals/{withdrawal_id}/cancel",
                **self.headers,
            )

        self.assertEqual(member_create_response.status_code, 403)
        self.assertEqual(invalid_form_response.status_code, 422)
        self.assertEqual(value_error_response.status_code, 422)
        self.assertEqual(missing_cancel_response.status_code, 404)
        self.assertEqual(cancel_error_response.status_code, 409)

    def test_withdrawal_cancel_and_org_service_branches(self):
        """Withdrawal endpoints should cover mapped service errors and org success."""
        with patch(
            "points.api_v1.services.cancel_withdrawal",
            side_effect=api_v1.services.WithdrawalError("提现申请不存在: 42"),
        ):
            user_cancel_error = self.client.post(
                "/api/v1/points/me/withdrawals/42/cancel",
                **self.headers,
            )

        with patch(
            "points.api_v1.services.create_withdrawal_request",
            side_effect=api_v1.services.WithdrawalError(
                "您有待处理的提现申请，请等待处理完成后再申请"
            ),
        ):
            org_service_error = self.client.post(
                f"/api/v1/points/organizations/{self.org.slug}/withdrawals",
                {
                    "amount": 200,
                    "real_name": "Coverage Org",
                    "phone": "13800138000",
                    "id_card": "11010519491231002X",
                    "bank_name": "Bank",
                    "bank_account": "6222021234567890123",
                },
                content_type="application/json",
                **self.headers,
            )

        org_withdrawal = WithdrawalRequest.objects.create(
            wallet=self.org.point_wallet,
            amount=200,
            status=WithdrawalStatus.PENDING,
            real_name="Coverage Org",
            phone="13800138000",
            id_card="11010519491231002X",
            bank_name="Bank",
            bank_account="6222021234567890123",
        )
        org_cancel_success = self.client.post(
            f"/api/v1/points/organizations/{self.org.slug}/withdrawals/{org_withdrawal.id}/cancel",
            **self.headers,
        )

        self.assertEqual(user_cancel_error.status_code, 409)
        self.assertEqual(org_service_error.status_code, 409)
        self.assertEqual(org_cancel_success.status_code, 200)
        org_withdrawal.refresh_from_db()
        self.assertEqual(org_withdrawal.status, WithdrawalStatus.CANCELLED)

    def test_pool_tag_and_search_endpoints_cover_filters(self):
        """Pool and tag endpoints should cover no-wallet owners and query branches."""
        tag = Tag.objects.create(
            name="Coverage Repo",
            slug="coverage-repo",
            tag_type="repo",
            description="Repository tag",
            entity_identifier="org/repo",
            is_official=False,
        )
        grant_points(
            owner=self.user,
            amount=100,
            point_type=PointType.GIFT,
            reason="Tagged gift",
            tag_slug=tag.slug,
            created_by=self.user,
        )
        empty_pools_response = self.client.get(
            "/api/v1/points/pools",
            **self.other_headers,
        )
        all_tags_response = self.client.get(
            "/api/v1/points/tags",
            **self.headers,
        )
        official_tags_response = self.client.get(
            "/api/v1/points/tags",
            {"official": "false"},
            **self.headers,
        )
        typed_tags_response = self.client.get(
            "/api/v1/points/tags",
            {"tag_type": "repo"},
            **self.headers,
        )
        tags_response = self.client.get(
            "/api/v1/points/tags?tag_type=repo&official=false",
            **self.headers,
        )
        blank_search_response = self.client.get(
            "/api/v1/points/tags/search?q=   ",
            **self.headers,
        )
        with patch("chdb.services.search_tags", return_value=[{"id": "repo"}]):
            search_response = self.client.get(
                "/api/v1/points/tags/search?q=repo",
                **self.headers,
            )

        self.assertEqual(empty_pools_response.status_code, 200)
        self.assertEqual(empty_pools_response.json()["items"], [])
        self.assertEqual(all_tags_response.status_code, 200)
        self.assertEqual(official_tags_response.status_code, 200)
        self.assertEqual(typed_tags_response.status_code, 200)
        self.assertEqual(tags_response.status_code, 200)
        self.assertEqual(tags_response.json()["items"][0]["slug"], tag.slug)
        self.assertEqual(blank_search_response.json()["items"], [])
        self.assertEqual(search_response.json()["items"], [{"id": "repo"}])

    def test_allocation_preview_execute_and_access_error_branches(self):
        """Allocation APIs should cover validation, balance, failure, and access branches."""
        preview_payload = {
            "source_selector": {"owner_type": "user", "point_type": PointType.GIFT},
            "project_scope": {"tags": ["repo"], "operation": "AND"},
            "user_scope": {"tags": ["alice"], "operation": "OR"},
            "start_month": "2025-01-01",
            "end_month": "2025-01-01",
        }
        with patch(
            "points.api_v1.AllocationService.preview_allocation",
            return_value=[
                {"actor_login": "alice", "contribution_score": Decimal("1.5")}
            ],
        ):
            preview_response = self.client.post(
                "/api/v1/points/allocations/preview",
                preview_payload,
                content_type="application/json",
                **self.headers,
            )
        insufficient_payload = {
            **preview_payload,
            "adjustment_ratio": 1.0,
            "total_amount": 999999,
            "allocations": [
                {
                    "actor_id": "1",
                    "actor_login": "alice",
                    "platform": "GitHub",
                    "is_registered": False,
                    "contribution_score": 1.0,
                    "amount": 999999,
                }
            ],
        }
        insufficient_response = self.client.post(
            "/api/v1/points/allocations",
            insufficient_payload,
            content_type="application/json",
            **self.headers,
        )
        failure_payload = {
            **preview_payload,
            "adjustment_ratio": 1.0,
            "total_amount": 100,
            "allocations": [
                {
                    "actor_id": "1",
                    "actor_login": "alice",
                    "platform": "GitHub",
                    "is_registered": False,
                    "contribution_score": 1.0,
                    "amount": 100,
                }
            ],
        }
        with patch(
            "points.api_v1.AllocationService.execute_allocation",
            side_effect=RuntimeError("boom"),
        ):
            failure_response = self.client.post(
                "/api/v1/points/allocations",
                failure_payload,
                content_type="application/json",
                **self.headers,
            )

        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(
            preview_response.json()["preview"][0]["contribution_score"], 1.5
        )
        self.assertEqual(insufficient_response.status_code, 409)
        self.assertEqual(failure_response.status_code, 409)

        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(self.user),
            initiator_id=self.user.id,
            source_pool=self.gift_source,
            total_amount=100,
            project_scope={"tags": ["repo"]},
            user_scope={"tags": ["alice"]},
            start_month=date(2025, 1, 1),
            end_month=date(2025, 1, 1),
            adjustment_ratio=Decimal("1.0"),
            individual_adjustments={},
            status="completed",
            executed_at=timezone.now(),
        )
        grant_points(
            owner=self.other_user,
            amount=50,
            point_type=PointType.GIFT,
            reason="Beneficiary fixture",
            reference_id=f"allocation_{allocation.id}",
            created_by=self.user,
        )
        forbidden_detail = self.client.get(
            f"/api/v1/points/allocations/{allocation.id}",
            **self.other_headers,
        )
        beneficiary_summary = self.client.get(
            f"/api/v1/points/allocations/{allocation.id}/summary",
            **self.other_headers,
        )
        forbidden_summary = self.client.get(
            f"/api/v1/points/allocations/{allocation.id}/summary",
            HTTP_AUTHORIZATION=f"Bearer {create_access_token(self.member_user)}",
        )

        self.assertEqual(forbidden_detail.status_code, 403)
        self.assertEqual(beneficiary_summary.status_code, 200)
        self.assertNotIn("total_amount", beneficiary_summary.json())
        self.assertEqual(forbidden_summary.status_code, 403)

    def test_serializers_cover_optional_allocation_and_withdrawal_fields(self):
        """Direct serializers should cover optional branches hard to hit via routing."""
        tag = Tag.objects.create(name="Serializer Tag", slug="serializer-tag")
        tagged_source = grant_points(
            owner=self.user,
            amount=50,
            point_type=PointType.GIFT,
            reason="Serializer tagged gift",
            tag_slug=tag.slug,
            created_by=self.user,
        )
        allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(self.user),
            initiator_id=self.user.id,
            source_pool=tagged_source,
            total_amount=50,
            project_scope={"tags": ["repo"]},
            user_scope=None,
            start_month=date(2025, 1, 1),
            end_month=date(2025, 1, 1),
            adjustment_ratio=Decimal("1.0"),
            individual_adjustments={},
            executed_at=timezone.now(),
        )
        PendingPointGrant.objects.create(
            allocation=allocation,
            granter_type=ContentType.objects.get_for_model(self.user),
            granter_id=self.user.id,
            platform="GitHub",
            actor_id="pending-1",
            actor_login="pending",
            email="pending@example.com",
            amount=50,
            point_type=PointType.GIFT,
            tag=tag,
            is_claimed=True,
            claimed_by=self.other_user,
            claimed_at=timezone.now(),
            expires_at=timezone.now(),
        )
        withdrawal_account = WithdrawalAccount.objects.create(
            user=self.user,
            account_type="international",
            real_name="Serializer User",
            currency="USD",
            swift_account="SWIFT123456789",
        )
        withdrawal = self.user.point_wallet.withdrawals.create(
            amount=200,
            status=WithdrawalStatus.PENDING,
            real_name="Serializer User",
            phone="13800138000",
            id_card="11010519491231002X",
            bank_name="",
            bank_account="",
            withdrawal_account=withdrawal_account,
            processed_at=timezone.now(),
        )
        transaction = PointTransaction.objects.create(
            wallet=self.user.point_wallet,
            transaction_type=TransactionType.EARN,
            point_type=PointType.GIFT,
            amount=1,
            balance_after=1,
            description="Serializer transaction",
            source=tagged_source,
            tag=tag,
            created_by=self.user,
        )

        allocation_payload = api_v1._serialize_allocation(allocation)
        withdrawal_payload = api_v1._serialize_withdrawal(withdrawal)
        transaction_payload = api_v1._serialize_transaction(transaction)

        self.assertEqual(
            allocation_payload["pending_grants"][0]["tag"]["slug"], tag.slug
        )
        self.assertIsNotNone(allocation_payload["executed_at"])
        self.assertEqual(
            withdrawal_payload["withdrawal_account_id"], withdrawal_account.id
        )
        self.assertIsNotNone(withdrawal_payload["processed_at"])
        self.assertEqual(transaction_payload["tag"]["slug"], tag.slug)
        self.assertEqual(
            transaction_payload["created_by"]["username"], self.user.username
        )

    def test_wallet_response_without_wallet_returns_empty_recent_transactions(self):
        """The wallet helper should avoid creating wallets for empty owners."""
        payload = api_v1._wallet_response(self.other_user)

        self.assertIsNone(payload["wallet_id"])
        self.assertEqual(payload["recent_transactions"], [])

    def test_user_can_access_allocation_owner_and_organization_branches(self):
        """Allocation access helper should cover owner, org, and fallback branches."""
        org_allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(self.other_user),
            initiator_id=self.other_user.id,
            source_pool=self.org_cash_source,
            total_amount=100,
            project_scope={"tags": ["repo"]},
            user_scope=None,
            start_month=date(2025, 1, 1),
            end_month=date(2025, 1, 1),
            adjustment_ratio=Decimal("1.0"),
            individual_adjustments={},
        )
        user_allocation = PointAllocation.objects.create(
            initiator_type=ContentType.objects.get_for_model(self.other_user),
            initiator_id=self.other_user.id,
            source_pool=self.cash_source,
            total_amount=100,
            project_scope={"tags": ["repo"]},
            user_scope=None,
            start_month=date(2025, 1, 1),
            end_month=date(2025, 1, 1),
            adjustment_ratio=Decimal("1.0"),
            individual_adjustments={},
        )

        self.assertTrue(api_v1._user_can_access_allocation(self.user, org_allocation))
        self.assertTrue(api_v1._user_can_access_allocation(self.user, user_allocation))
        self.assertFalse(
            api_v1._user_can_access_allocation(self.member_user, user_allocation)
        )

        orphan_allocation = SimpleNamespace(
            initiator_type=ContentType.objects.get_for_model(self.other_user),
            initiator_id=self.other_user.id,
            source_pool=SimpleNamespace(wallet=SimpleNamespace(owner=object())),
        )
        self.assertFalse(
            api_v1._user_can_access_allocation(self.user, orphan_allocation)
        )

    def test_preview_normalization_and_filter_endpoints_cover_remaining_branches(self):
        """Small API helpers should cover Decimal and filter branches."""
        normalized = api_v1._normalize_preview_items(
            [
                {"actor_login": "decimal", "contribution_score": Decimal("2.5")},
                {"actor_login": "float", "contribution_score": 1.25},
            ]
        )
        self.assertEqual(normalized[0]["contribution_score"], 2.5)
        self.assertEqual(normalized[1]["contribution_score"], 1.25)

        org_without_wallet = Organization.objects.create(
            name="No Wallet Org",
            slug="no-wallet-org",
        )
        OrganizationMembership.objects.create(
            user=self.user,
            organization=org_without_wallet,
            role=OrganizationMembership.Role.MEMBER,
        )
        no_wallet_transactions = self.client.get(
            f"/api/v1/points/organizations/{org_without_wallet.slug}/transactions",
            {"point_type": PointType.CASH, "transaction_type": TransactionType.EARN},
            **self.headers,
        )
        self.assertEqual(no_wallet_transactions.status_code, 200)
        self.assertEqual(no_wallet_transactions.json()["items"], [])

        tag = Tag.objects.create(
            name="Coverage Official Tag",
            slug="coverage-official-tag",
            tag_type="repo",
            is_official=True,
        )
        tags_response = self.client.get(
            "/api/v1/points/tags",
            {"tag_type": "repo", "official": "true"},
            **self.headers,
        )
        self.assertEqual(tags_response.status_code, 200)
        self.assertIn(
            tag.slug, {item["slug"] for item in tags_response.json()["items"]}
        )

    def test_withdrawal_error_branches_cover_value_and_not_found_paths(self):
        """Withdrawal endpoints should map ValueError and not-found branches."""
        account = WithdrawalAccount.objects.create(
            user=self.user,
            account_type="international",
            real_name="Points User",
            currency="USD",
            swift_account="SWIFT123456789",
        )
        with patch(
            "points.api_v1.services.create_withdrawal_request",
            side_effect=ValueError("invalid withdrawal account"),
        ):
            user_value_error = self.client.post(
                "/api/v1/points/me/withdrawals",
                {"withdrawal_account_id": account.id, "amount": 200},
                content_type="application/json",
                **self.headers,
            )

        with patch(
            "points.api_v1.services.create_withdrawal_request",
            side_effect=ValueError("org invalid"),
        ):
            org_value_error = self.client.post(
                f"/api/v1/points/organizations/{self.org.slug}/withdrawals",
                {
                    "amount": "200",
                    "real_name": "Org User",
                    "phone": "13800138000",
                    "id_card": "11010519491231002X",
                    "bank_name": "Bank",
                    "bank_account": "6222021234567890123",
                },
                **self.headers,
            )
        with patch(
            "points.api_v1.services.create_withdrawal_request",
            side_effect=ValueError("legacy invalid"),
        ):
            legacy_value_error = self.client.post(
                "/api/v1/points/me/withdrawals",
                {
                    "amount": "200",
                    "real_name": "Legacy User",
                    "phone": "13800138000",
                    "id_card": "11010519491231002X",
                    "bank_name": "Bank",
                    "bank_account": "6222021234567890123",
                },
                **self.headers,
            )
        missing_cancel = self.client.post(
            f"/api/v1/points/organizations/{self.org.slug}/withdrawals/999999/cancel",
            **self.headers,
        )

        self.assertEqual(user_value_error.status_code, 422)
        self.assertEqual(org_value_error.status_code, 422)
        self.assertEqual(legacy_value_error.status_code, 422)
        self.assertEqual(missing_cancel.status_code, 404)
