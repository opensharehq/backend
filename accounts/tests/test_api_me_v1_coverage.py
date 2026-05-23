"""Additional coverage for authenticated me API edge cases."""

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from accounts import api_me_v1
from accounts.models import (
    AccountMergeRequest,
    Education,
    ShippingAddress,
    UserProfile,
    WithdrawalAccount,
    WorkExperience,
)
from accounts.services.account_merge import AccountMergeError
from accounts.services.email_deduplication import (
    EmailDedupeAction,
    EmailDedupePlan,
    _blocking_reason,
    _build_group_plan,
    apply_duplicate_email_plans,
)
from accounts.services.jwt_tokens import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    get_user_from_refresh_token,
    revoke_refresh_token,
    rotate_refresh_token,
)
from accounts.services.masking import mask_card, mask_name
from points.models import PointWallet
from shenbianyun.models import SignedUser


def _user_like(**overrides):
    """Create a lightweight user-like object for email-deduplication helpers."""
    values = {
        "pk": 1,
        "username": "user",
        "email": "user@example.com",
        "is_active": True,
        "merged_into_id": None,
        "is_staff": False,
        "is_superuser": False,
        "has_password": True,
    }
    values.update(overrides)
    user = SimpleNamespace(
        pk=values["pk"],
        username=values["username"],
        email=values["email"],
        is_active=values["is_active"],
        merged_into_id=values["merged_into_id"],
        is_staff=values["is_staff"],
        is_superuser=values["is_superuser"],
    )
    user.has_usable_password = lambda: values["has_password"]
    return user


class ApiMeV1CoverageTests(TestCase):
    """Cover me API and account service branches not hit by happy paths."""

    def setUp(self):
        """Create a user fixture."""
        self.User = get_user_model()
        self.password = "MeCoveragePass123!"  # noqa: S105
        self.user = self.User.objects.create_user(
            username="me-coverage",
            email="me-coverage@example.com",
            password=self.password,
        )
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.user)}"
        }

    def _json_headers(self):
        """Return auth headers for JSON requests."""
        return {"content_type": "application/json", **self.headers}

    def test_profile_payload_and_form_value_helpers_cover_non_empty_values(self):
        """Helper functions should normalize existing model values."""
        profile = UserProfile.objects.create(
            user=self.user,
            bio="Hello",
            birth_date=date(1990, 1, 2),
        )

        payload = api_me_v1._profile_payload(profile)
        merged = api_me_v1._merged_form_data(
            profile,
            ["bio", "birth_date"],
            {"bio": None},
        )

        self.assertEqual(payload["bio"], "Hello")
        self.assertEqual(merged, {"bio": "", "birth_date": "1990-01-02"})
        self.assertIs(api_me_v1._normalize_form_value(True), True)

    def test_profile_work_education_and_address_validation_errors(self):
        """CRUD endpoints should return validation errors for invalid forms."""
        profile_response = self.client.patch(
            "/api/v1/me/profile",
            {"github_url": "not-a-url"},
            **self._json_headers(),
        )
        work_create = self.client.post(
            "/api/v1/me/work-experiences",
            {
                "company_name": "",
                "title": "",
                "start_date": "2025-02-01",
                "end_date": "2025-01-01",
            },
            **self._json_headers(),
        )
        work = WorkExperience.objects.create(
            profile=UserProfile.objects.get(user=self.user),
            company_name="OpenShare",
            title="Engineer",
            start_date=date(2025, 1, 1),
        )
        work_update = self.client.patch(
            f"/api/v1/me/work-experiences/{work.id}",
            {"start_date": "2025-02-01", "end_date": "2025-01-01"},
            **self._json_headers(),
        )
        education_create = self.client.post(
            "/api/v1/me/educations",
            {
                "institution_name": "",
                "field_of_study": "",
                "start_date": "2025-02-01",
                "end_date": "2025-01-01",
            },
            **self._json_headers(),
        )
        education = Education.objects.create(
            profile=UserProfile.objects.get(user=self.user),
            institution_name="School",
            field_of_study="CS",
            start_date=date(2025, 1, 1),
        )
        education_update = self.client.patch(
            f"/api/v1/me/educations/{education.id}",
            {"start_date": "2025-02-01", "end_date": "2025-01-01"},
            **self._json_headers(),
        )
        address_create = self.client.post(
            "/api/v1/me/shipping-addresses",
            {"receiver_name": "", "phone": ""},
            **self._json_headers(),
        )
        address = ShippingAddress.objects.create(
            user=self.user,
            receiver_name="Receiver",
            phone="13800138000",
            province="Shanghai",
            city="Shanghai",
            district="Pudong",
            address="Road",
        )
        address_update = self.client.patch(
            f"/api/v1/me/shipping-addresses/{address.id}",
            {"phone": ""},
            **self._json_headers(),
        )

        for response in (
            profile_response,
            work_create,
            work_update,
            education_create,
            education_update,
            address_create,
            address_update,
        ):
            self.assertEqual(response.status_code, 422)

    def test_shipping_address_create_validation_error_after_schema_validation(self):
        """Address creation should surface form validation after schema parsing."""
        response = self.client.post(
            "/api/v1/me/shipping-addresses",
            {
                "receiver_name": "",
                "phone": "bad-phone",
                "province": "",
                "city": "",
                "district": "",
                "address": "",
                "is_default": False,
            },
            **self._json_headers(),
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "validation_error")

    def test_empty_list_endpoints_do_not_create_profile(self):
        """List endpoints should return empty lists when no profile exists."""
        user = self.User.objects.create_user(
            username="me-empty-lists",
            email="me-empty-lists@example.com",
            password=self.password,
        )
        headers = {"HTTP_AUTHORIZATION": f"Bearer {create_access_token(user)}"}

        work_response = self.client.get("/api/v1/me/work-experiences", **headers)
        education_response = self.client.get("/api/v1/me/educations", **headers)

        self.assertEqual(work_response.json()["items"], [])
        self.assertEqual(education_response.json()["items"], [])
        self.assertFalse(UserProfile.objects.filter(user=user).exists())

    def test_withdrawal_account_validation_and_international_flow(self):
        """Withdrawal account endpoint should cover all validation branches."""
        invalid_type = self.client.post(
            "/api/v1/me/withdrawal-accounts",
            {"account_type": "bad", "real_name": "User"},
            **self._json_headers(),
        )
        domestic_missing = self.client.post(
            "/api/v1/me/withdrawal-accounts",
            {"account_type": "domestic", "real_name": "User"},
            **self._json_headers(),
        )
        domestic_bad_card = self.client.post(
            "/api/v1/me/withdrawal-accounts",
            {
                "account_type": "domestic",
                "real_name": "User",
                "id_card": "11010519491231002X",
                "phone": "13800138000",
                "bank_card": "abc",
            },
            **self._json_headers(),
        )
        domestic_not_signed = self.client.post(
            "/api/v1/me/withdrawal-accounts",
            {
                "account_type": "domestic",
                "real_name": "User",
                "id_card": "11010519491231002X",
                "phone": "13800138000",
                "bank_card": "6222021234567890123",
            },
            **self._json_headers(),
        )
        international_missing = self.client.post(
            "/api/v1/me/withdrawal-accounts",
            {"account_type": "international", "real_name": "User"},
            **self._json_headers(),
        )
        international_bad_currency = self.client.post(
            "/api/v1/me/withdrawal-accounts",
            {
                "account_type": "international",
                "real_name": "User",
                "currency": "EUR",
                "swift_account": "EU123",
            },
            **self._json_headers(),
        )
        international_ok = self.client.post(
            "/api/v1/me/withdrawal-accounts",
            {
                "account_type": "international",
                "real_name": "User",
                "currency": "USD",
                "swift_account": "US123456",
            },
            **self._json_headers(),
        )
        list_response = self.client.get(
            "/api/v1/me/withdrawal-accounts", **self.headers
        )

        for response in (
            invalid_type,
            domestic_missing,
            domestic_bad_card,
            domestic_not_signed,
            international_missing,
            international_bad_currency,
        ):
            self.assertEqual(response.status_code, 422)
        self.assertEqual(international_ok.status_code, 201)
        self.assertEqual(
            list_response.json()["items"][0]["account_type"], "international"
        )

    def test_withdrawal_account_domestic_success_and_delete(self):
        """Signed domestic accounts should be creatable and deletable."""
        SignedUser.objects.create(
            offset_id="me-sign-coverage",
            name="Domestic User",
            mobile="13800138000",
            id_card="11010519491231002X",
            provider_id=1,
            state=1,
        )
        create_response = self.client.post(
            "/api/v1/me/withdrawal-accounts",
            {
                "account_type": "domestic",
                "real_name": "Domestic User",
                "id_card": "11010519491231002X",
                "phone": "13800138000",
                "bank_card": "6222 0212 3456 7890 123",
            },
            **self._json_headers(),
        )
        account_id = create_response.json()["id"]
        delete_response = self.client.delete(
            f"/api/v1/me/withdrawal-accounts/{account_id}",
            **self.headers,
        )

        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(delete_response.status_code, 204)
        self.assertFalse(WithdrawalAccount.objects.filter(id=account_id).exists())

    def test_account_merge_validation_conflict_and_error_paths(self):
        """Merge endpoints should cover validation, conflict, expired, and failure paths."""
        target = self.User.objects.create_user(
            username="me-merge-target",
            email="me-merge-target@example.com",
            password=self.password,
        )
        target_headers = {"HTTP_AUTHORIZATION": f"Bearer {create_access_token(target)}"}
        invalid_create = self.client.post(
            "/api/v1/me/account-merges",
            {},
            **self._json_headers(),
        )
        with patch(
            "accounts.api_me_v1.AccountMergeRequest.objects.create",
            side_effect=IntegrityError("duplicate"),
        ):
            conflict_create = self.client.post(
                "/api/v1/me/account-merges",
                {"target_username": target.username},
                **self._json_headers(),
            )

        merge_request = AccountMergeRequest.objects.create(
            source_user=self.user,
            target_user=target,
            target_username_input=target.username,
            status=AccountMergeRequest.Status.PENDING,
            approve_token="coverage-token",
            expires_at=timezone.now() + timedelta(days=1),
            asset_snapshot={},
        )
        with patch(
            "accounts.api_me_v1.perform_merge",
            side_effect=AccountMergeError("merge failed"),
        ):
            accept_failed = self.client.post(
                f"/api/v1/me/account-merges/review/{merge_request.approve_token}/accept",
                **target_headers,
            )
        merge_request.status = AccountMergeRequest.Status.REJECTED
        merge_request.save(update_fields=["status"])
        reject_not_pending = self.client.post(
            f"/api/v1/me/account-merges/review/{merge_request.approve_token}/reject",
            **target_headers,
        )
        expired_for_accept = AccountMergeRequest.objects.create(
            source_user=self.user,
            target_user=target,
            target_username_input=target.username,
            status=AccountMergeRequest.Status.PENDING,
            approve_token="expired-accept-token",
            expires_at=timezone.now() - timedelta(days=1),
            asset_snapshot={},
        )
        expired_accept = self.client.post(
            f"/api/v1/me/account-merges/review/{expired_for_accept.approve_token}/accept",
            **target_headers,
        )
        expired_for_reject = AccountMergeRequest.objects.create(
            source_user=self.user,
            target_user=target,
            target_username_input=target.username,
            status=AccountMergeRequest.Status.PENDING,
            approve_token="expired-reject-token",
            expires_at=timezone.now() - timedelta(days=1),
            asset_snapshot={},
        )
        expired_reject = self.client.post(
            f"/api/v1/me/account-merges/review/{expired_for_reject.approve_token}/reject",
            **target_headers,
        )

        self.assertEqual(invalid_create.status_code, 422)
        self.assertEqual(conflict_create.status_code, 409)
        self.assertEqual(accept_failed.status_code, 409)
        self.assertEqual(reject_not_pending.status_code, 409)
        self.assertEqual(expired_accept.status_code, 409)
        self.assertEqual(expired_reject.status_code, 409)

    def test_account_merge_list_returns_sent_and_incoming_requests(self):
        """Merge list endpoint should serialize both outgoing and incoming requests."""
        target = self.User.objects.create_user(
            username="me-list-target",
            email="me-list-target@example.com",
            password=self.password,
        )
        source = self.User.objects.create_user(
            username="me-list-source",
            email="me-list-source@example.com",
            password=self.password,
        )
        AccountMergeRequest.objects.create(
            source_user=self.user,
            target_user=target,
            target_username_input=target.username,
            status=AccountMergeRequest.Status.PENDING,
            approve_token="sent-token",
            expires_at=timezone.now() + timedelta(days=1),
            asset_snapshot={},
        )
        AccountMergeRequest.objects.create(
            source_user=source,
            target_user=self.user,
            target_username_input=self.user.username,
            status=AccountMergeRequest.Status.PENDING,
            approve_token="incoming-token",
            expires_at=timezone.now() + timedelta(days=1),
            asset_snapshot={},
        )

        response = self.client.get(
            "/api/v1/me/account-merges",
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["sent"]), 1)
        self.assertEqual(len(response.json()["incoming"]), 1)

    def test_masking_helpers_cover_short_and_empty_inputs(self):
        """Masking helpers should cover all length branches."""
        self.assertEqual(mask_name(""), "")
        self.assertEqual(mask_name("A"), "A")
        self.assertEqual(mask_name("AB"), "A*")
        self.assertEqual(mask_name("ABC"), "A*C")
        self.assertEqual(mask_card(""), "")
        self.assertEqual(mask_card("123456"), "123456")
        self.assertEqual(mask_card("1234567"), "123*567")

    def test_email_deduplication_helpers_cover_blocking_and_apply_paths(self):
        """Email dedupe helpers should cover blocked, archive-only, and merge branches."""
        merged_external = _user_like(pk=1, merged_into_id=999)
        merged_primary = _user_like(pk=2, merged_into_id=999)
        self.assertEqual(
            _blocking_reason([merged_external, merged_primary]),
            "group has no unmerged primary candidate",
        )
        outside_chain = [_user_like(pk=1), _user_like(pk=2, merged_into_id=999)]
        self.assertEqual(
            _blocking_reason(outside_chain),
            "group contains a merge chain pointing outside the duplicate set",
        )

        primary = self.User.objects.create_user(
            username="dedupe-primary",
            email="dedupe-primary@example.com",
            password=self.password,
        )
        archive_source = self.User.objects.create_user(
            username="dedupe-archive",
            email="dedupe-archive@example.com",
            password=self.password,
            is_active=False,
            merged_into=primary,
        )
        merge_source = self.User.objects.create_user(
            username="dedupe-merge",
            email="dedupe-merge@example.com",
            password=self.password,
        )
        plan = EmailDedupePlan(
            normalized_email="shared@example.com",
            primary=primary,
            actions=[
                EmailDedupeAction(archive_source, primary, archive_only=True),
                EmailDedupeAction(merge_source, primary, archive_only=False),
            ],
        )
        with patch("accounts.services.email_deduplication.merge_users") as merge_mock:
            apply_duplicate_email_plans([plan])
        archive_source.refresh_from_db()
        merge_source.refresh_from_db()

        self.assertTrue(archive_source.email.endswith("@users.invalid"))
        self.assertTrue(merge_source.email.endswith("@users.invalid"))
        merge_mock.assert_called_once()

        blocked_plan = _build_group_plan(
            "blocked@example.com",
            [_user_like(pk=1, is_staff=True), _user_like(pk=2)],
        )
        with self.assertRaises(AccountMergeError):
            apply_duplicate_email_plans([blocked_plan])

    def test_jwt_refresh_helpers_cover_remaining_invalid_payloads(self):
        """Refresh helpers should cover malformed jti and inactive-user branches."""
        self.assertIsNone(
            get_user_from_refresh_token(
                jwt.encode(
                    {
                        "sub": str(self.user.id),
                        "type": REFRESH_TOKEN_TYPE,
                        "jti": "not-a-uuid",
                        "iat": timezone.now(),
                        "exp": timezone.now() + timedelta(minutes=5),
                    },
                    settings.JWT_SECRET_KEY,
                    algorithm=settings.JWT_ALGORITHM,
                )
            )
        )
        token = create_refresh_token(self.user)
        payload = decode_refresh_token(token)
        self.assertIsNotNone(payload)

        inactive = self.User.objects.create_user(
            username="refresh-inactive",
            email="refresh-inactive@example.com",
            password=self.password,
            is_active=False,
        )
        inactive_token = create_refresh_token(inactive)
        self.assertIsNone(get_user_from_refresh_token(inactive_token))
        self.assertFalse(revoke_refresh_token(inactive_token))
        self.assertIsNone(rotate_refresh_token(inactive_token))

        payload["jti"] = "00000000-0000-0000-0000-000000000000"
        missing_record = jwt.encode(
            payload,
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )
        self.assertIsNone(get_user_from_refresh_token(missing_record))

    def test_profile_wallet_property_creates_wallet(self):
        """User.point_wallet should create and return a wallet."""
        self.assertFalse(
            PointWallet.objects.filter(
                content_type=ContentType.objects.get_for_model(self.user),
                object_id=self.user.id,
            ).exists()
        )

        wallet = self.user.point_wallet

        self.assertEqual(wallet.owner, self.user)
