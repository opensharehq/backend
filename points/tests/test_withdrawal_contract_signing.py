"""Tests for withdrawal contract signing flow."""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse

from points.models import PointSource, Tag, WithdrawalContractSigning, WithdrawalRequest


class WithdrawalContractSigningViewTests(TestCase):
    """Test withdrawal views when contract signing is required."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="sign_user", email="sign_user@example.com", password="pwd12345"
        )
        self.client.login(username="sign_user", password="pwd12345")

        self.withdrawable_tag = Tag.objects.create(name="wd_tag", withdrawable=True)
        self.point_source = PointSource.objects.create(
            user=self.user,
            initial_points=100,
            remaining_points=100,
        )
        self.point_source.tags.add(self.withdrawable_tag)

    @override_settings(
        WITHDRAWAL_CONTRACT_SIGNING_REQUIRED=True,
        FDD_API_HOST="https://example.com/api/v5/",
        FDD_APP_ID="app_id",
        FDD_APP_SECRET="app_secret",
    )
    @patch("points.fadada.FadadaClient.sign_with_template")
    def test_withdrawal_create_starts_signing_when_not_signed(self, sign_mock):
        sign_mock.return_value = {"ok": True}

        url = reverse("points:withdrawal_create", args=[self.point_source.id])
        response = self.client.post(
            url,
            {
                "points": 10,
                "real_name": "测试",
                "id_number": "110101199001011234",
                "phone_number": "13800138000",
                "bank_name": "银行",
                "bank_account": "6222020200012345678",
            },
            follow=True,
        )

        self.assertRedirects(response, reverse("points:withdrawal_list"))
        self.assertEqual(
            WithdrawalRequest.objects.filter(user=self.user).count(),
            0,
        )

        record = WithdrawalContractSigning.objects.get(user=self.user)
        self.assertEqual(record.status, WithdrawalContractSigning.Status.PENDING)
        self.assertEqual(
            record.withdrawal_payload["point_source_id"], self.point_source.id
        )
        self.assertEqual(record.withdrawal_payload["points"], 10)
        self.assertEqual(record.fdd_request_payload["signing_record_id"], record.id)

        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(
            any("已发起提现合同签署" in str(message) for message in messages),
            f"Expected signing message, got: {[str(m) for m in messages]}",
        )
        sign_mock.assert_called_once()


class WithdrawalContractSigningWebhookTests(TestCase):
    """Test webhook callback handling for withdrawal contract signing."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="hook_user", email="hook_user@example.com", password="pwd12345"
        )
        self.withdrawable_tag = Tag.objects.create(name="wd_tag", withdrawable=True)

    def _create_source(self, points: int = 100) -> PointSource:
        source = PointSource.objects.create(
            user=self.user,
            initial_points=points,
            remaining_points=points,
        )
        source.tags.add(self.withdrawable_tag)
        return source

    def test_webhook_marks_signed_and_creates_withdrawal_request(self):
        source = self._create_source(points=100)
        record = WithdrawalContractSigning.objects.create(
            user=self.user,
            status=WithdrawalContractSigning.Status.PENDING,
            real_name="测试",
            id_number="110101199001011234",
            phone_number="13800138000",
            bank_name="银行",
            bank_account="6222020200012345678",
            withdrawal_payload={"point_source_id": source.id, "points": 15},
        )

        url = reverse("points_webhooks:fdd_withdrawal_contract_webhook")
        response = self.client.post(
            url,
            data=json.dumps({"signing_record_id": record.id, "status": "SIGNED"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        record.refresh_from_db()
        self.assertEqual(record.status, WithdrawalContractSigning.Status.SIGNED)
        self.assertIsNotNone(record.signed_at)

        withdrawals = WithdrawalRequest.objects.filter(user=self.user)
        self.assertEqual(withdrawals.count(), 1)
        withdrawal = withdrawals.first()
        assert withdrawal is not None
        self.assertEqual(withdrawal.point_source_id, source.id)
        self.assertEqual(withdrawal.points, 15)
        self.assertEqual(withdrawal.real_name, "测试")

        self.assertEqual(record.created_withdrawal_request_ids, [withdrawal.id])

    def test_webhook_creates_batch_withdrawal_requests(self):
        source1 = self._create_source(points=100)
        source2 = self._create_source(points=200)
        record = WithdrawalContractSigning.objects.create(
            user=self.user,
            status=WithdrawalContractSigning.Status.PENDING,
            real_name="测试",
            id_number="110101199001011234",
            phone_number="13800138000",
            bank_name="银行",
            bank_account="6222020200012345678",
            withdrawal_payload={
                "withdrawal_amounts": {str(source1.id): 10, str(source2.id): 20}
            },
        )

        url = reverse("points_webhooks:fdd_withdrawal_contract_webhook")
        response = self.client.post(
            url,
            data=json.dumps({"signing_record_id": record.id, "status": "SIGNED"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        record.refresh_from_db()
        self.assertEqual(record.status, WithdrawalContractSigning.Status.SIGNED)

        withdrawals = WithdrawalRequest.objects.filter(user=self.user).order_by("id")
        self.assertEqual(withdrawals.count(), 2)
        self.assertEqual(
            {wr.point_source_id for wr in withdrawals}, {source1.id, source2.id}
        )
        self.assertEqual({wr.points for wr in withdrawals}, {10, 20})
        self.assertEqual(
            record.created_withdrawal_request_ids, [wr.id for wr in withdrawals]
        )

    @override_settings(FDD_WEBHOOK_TOKEN="secret-token")
    def test_webhook_token_required_when_configured(self):
        source = self._create_source(points=100)
        record = WithdrawalContractSigning.objects.create(
            user=self.user,
            status=WithdrawalContractSigning.Status.PENDING,
            real_name="测试",
            id_number="110101199001011234",
            phone_number="13800138000",
            bank_name="银行",
            bank_account="6222020200012345678",
            withdrawal_payload={"point_source_id": source.id, "points": 1},
        )

        url = reverse("points_webhooks:fdd_withdrawal_contract_webhook")
        response = self.client.post(
            url,
            data=json.dumps({"signing_record_id": record.id, "status": "SIGNED"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            url,
            data=json.dumps({"signing_record_id": record.id, "status": "SIGNED"}),
            content_type="application/json",
            HTTP_X_FDD_WEBHOOK_TOKEN="secret-token",
        )
        self.assertEqual(response.status_code, 200)
