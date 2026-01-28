"""Tests for points forms."""

from django.test import TestCase

from accounts.models import User
from points import services
from points.forms import WithdrawalRequestForm
from points.models import PointType


class WithdrawalRequestFormTests(TestCase):
    """Tests for WithdrawalRequestForm."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        services.grant_points(self.user, 1000, PointType.CASH, "Initial")

    def test_valid_form(self):
        """Test valid form data."""
        form = WithdrawalRequestForm(
            self.user,
            data={
                "amount": 500,
                "real_name": "张三",
                "phone": "13800138000",
                "id_card": "11010519491231002X",
                "bank_name": "中国银行",
                "bank_account": "6222000000000000000",
            },
        )
        self.assertTrue(form.is_valid())

    def test_amount_exceeds_balance(self):
        """Test amount exceeding balance."""
        form = WithdrawalRequestForm(
            self.user,
            data={
                "amount": 2000,
                "real_name": "张三",
                "phone": "13800138000",
                "id_card": "11010519491231002X",
                "bank_name": "中国银行",
                "bank_account": "6222000000000000000",
            },
        )
        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)

    def test_amount_zero(self):
        """Test zero amount."""
        form = WithdrawalRequestForm(
            self.user,
            data={
                "amount": 0,
                "real_name": "张三",
                "phone": "13800138000",
                "id_card": "11010519491231002X",
                "bank_name": "中国银行",
                "bank_account": "6222000000000000000",
            },
        )
        self.assertFalse(form.is_valid())

    def test_invalid_phone(self):
        """Test invalid phone number."""
        form = WithdrawalRequestForm(
            self.user,
            data={
                "amount": 500,
                "real_name": "张三",
                "phone": "123",  # Too short
                "id_card": "11010519491231002X",
                "bank_name": "中国银行",
                "bank_account": "6222000000000000000",
            },
        )
        self.assertFalse(form.is_valid())
        self.assertIn("phone", form.errors)

    def test_invalid_bank_account(self):
        """Test invalid bank account."""
        form = WithdrawalRequestForm(
            self.user,
            data={
                "amount": 500,
                "real_name": "张三",
                "phone": "13800138000",
                "id_card": "11010519491231002X",
                "bank_name": "中国银行",
                "bank_account": "123",  # Too short
            },
        )
        self.assertFalse(form.is_valid())
        self.assertIn("bank_account", form.errors)

    def test_bank_account_with_spaces(self):
        """Test bank account with spaces is accepted."""
        form = WithdrawalRequestForm(
            self.user,
            data={
                "amount": 500,
                "real_name": "张三",
                "phone": "13800138000",
                "id_card": "11010519491231002X",
                "bank_name": "中国银行",
                "bank_account": "6222 0000 0000 0000 000",
            },
        )
        self.assertTrue(form.is_valid())
        # Check spaces are stripped
        self.assertEqual(form.cleaned_data["bank_account"], "6222000000000000000")

    def test_bank_account_with_dashes(self):
        """Test bank account with dashes is accepted."""
        form = WithdrawalRequestForm(
            self.user,
            data={
                "amount": 500,
                "real_name": "张三",
                "phone": "13800138000",
                "id_card": "11010519491231002X",
                "bank_name": "中国银行",
                "bank_account": "6222-0000-0000-0000-000",
            },
        )
        self.assertTrue(form.is_valid())

    def test_invalid_id_card(self):
        """Test invalid ID card."""
        form = WithdrawalRequestForm(
            self.user,
            data={
                "amount": 500,
                "real_name": "张三",
                "phone": "13800138000",
                "id_card": "12345",
                "bank_name": "中国银行",
                "bank_account": "6222000000000000000",
            },
        )
        self.assertFalse(form.is_valid())
        self.assertIn("id_card", form.errors)
