"""Tests for withdrawal contract flow."""

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from points.admin import WithdrawalContractAdmin
from points.models import PointSource, Tag, WithdrawalContract
from points.services import get_or_create_withdrawal_contract


class WithdrawalContractServiceTests(TestCase):
    """Service-level tests for contract creation and signing."""

    def setUp(self):
        """Create a user for contract service tests."""
        self.user = get_user_model().objects.create_user(username="contract-user")

    def test_get_or_create_sets_placeholder_link(self):
        """Creates contract with placeholder sign url containing flow id."""
        contract, created = get_or_create_withdrawal_contract(self.user)
        self.assertTrue(created)
        self.assertTrue(contract.sign_url)
        self.assertIn(contract.fadada_flow_id, contract.sign_url)
        self.assertEqual(contract.status, WithdrawalContract.Status.PENDING)

    def test_mark_signed_updates_status_and_source(self):
        """mark_signed stores status, timestamp and source."""
        contract, _ = get_or_create_withdrawal_contract(self.user)
        contract.mark_signed(source=WithdrawalContract.CompletionSource.ADMIN)
        contract.refresh_from_db()
        self.assertTrue(contract.is_signed)
        self.assertEqual(contract.completion_source, "ADMIN")
        self.assertIsNotNone(contract.signed_at)


class WithdrawalContractViewTests(TestCase):
    """View-level tests for contract gating and callbacks."""

    def setUp(self):
        """Prepare client, user, and a withdrawable point source."""
        self.client = Client()
        self.user = get_user_model().objects.create_user(
            username="withdraw-view", password="pass12345"
        )
        self.tag = Tag.objects.create(name="withdrawable", withdrawable=True)
        self.point_source = PointSource.objects.create(
            user=self.user, initial_points=100, remaining_points=100
        )
        self.point_source.tags.add(self.tag)

    def test_withdrawal_create_redirects_when_not_signed(self):
        """Withdrawal form requires signed contract first."""
        self.client.login(username="withdraw-view", password="pass12345")
        url = reverse("points:withdrawal_create", args=[self.point_source.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("points:withdrawal_contract"))

    def test_withdrawal_create_allows_after_signed(self):
        """Once contract signed, form page loads."""
        self.client.login(username="withdraw-view", password="pass12345")
        contract, _ = get_or_create_withdrawal_contract(self.user)
        contract.mark_signed(source=WithdrawalContract.CompletionSource.ADMIN)

        url = reverse("points:withdrawal_create", args=[self.point_source.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "提现积分数量")

    def test_fadada_callback_marks_signed(self):
        """Callback endpoint marks contract signed on success status."""
        contract, _ = get_or_create_withdrawal_contract(self.user)
        url = reverse("points:fadada_withdrawal_callback")
        response = self.client.post(
            url, {"flow_id": contract.fadada_flow_id, "status": "SIGNED"}
        )
        self.assertEqual(response.status_code, 200)
        contract.refresh_from_db()
        self.assertTrue(contract.is_signed)
        self.assertEqual(
            contract.completion_source, WithdrawalContract.CompletionSource.CALLBACK
        )


class WithdrawalContractAdminTests(TestCase):
    """Admin action tests for marking contract signed."""

    def setUp(self):
        """Create admin, contract user, and contract for admin actions."""
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_superuser(
            username="admin", email="admin@example.com", password="adminpass"
        )
        self.contract_user = get_user_model().objects.create_user(
            username="contract-admin"
        )
        self.contract, _ = get_or_create_withdrawal_contract(self.contract_user)
        self.admin = WithdrawalContractAdmin(WithdrawalContract, AdminSite())

    def test_mark_signed_admin_action(self):
        """Admin action marks selected contracts as signed."""
        request = self.factory.get("/")
        request.user = self.user
        queryset = WithdrawalContract.objects.filter(pk=self.contract.pk)
        self.admin.mark_signed_admin(request, queryset)
        self.contract.refresh_from_db()
        self.assertTrue(self.contract.is_signed)
        self.assertEqual(
            self.contract.completion_source, WithdrawalContract.CompletionSource.ADMIN
        )
