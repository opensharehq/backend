"""Tests for points forms."""

from django import forms
from django.contrib.auth import get_user_model
from django.test import TestCase

from points.forms import BatchWithdrawalInfoForm, WithdrawalRequestForm
from points.models import PointSource, Tag


def build_withdrawal_data(**overrides):
    """Return a baseline valid payload for withdrawal-related forms."""
    base = {
        "points": 50,
        "real_name": "张三",
        "id_number": "110101199001011234",
        "phone_number": "13800138000",
        "bank_name": "中国银行",
        "bank_account": "6222020200012345678",
    }
    base.update(overrides)
    return base


class WithdrawalRequestFormTests(TestCase):
    """Validate WithdrawalRequestForm cleaning logic."""

    def setUp(self):
        """Create user, withdrawable tag and point source."""
        self.user = get_user_model().objects.create_user(username="form-user")
        self.withdrawable_tag = Tag.objects.create(
            name="withdrawable", withdrawable=True
        )
        self.point_source = PointSource.objects.create(
            user=self.user,
            initial_points=120,
            remaining_points=120,
        )
        self.point_source.tags.add(self.withdrawable_tag)

    def test_init_sets_max_and_help_text(self):
        """Widget reflects available points when point_source is provided."""
        form = WithdrawalRequestForm(point_source=self.point_source)

        self.assertEqual(
            form.fields["points"].widget.attrs["max"],
            self.point_source.remaining_points,
        )
        self.assertIn(
            str(self.point_source.remaining_points),
            form.fields["points"].help_text,
        )

    def test_clean_points_validations(self):
        """Points must be present, positive and within remaining balance."""
        form = WithdrawalRequestForm(
            data=build_withdrawal_data(points=""),
            point_source=self.point_source,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("必填", form.errors["points"][0])

        form.cleaned_data = {"points": None}
        with self.assertRaisesMessage(forms.ValidationError, "请输入提现积分数量。"):
            form.clean_points()

        for value, message in [
            (0, "提现积分必须大于0。"),
            (999, "提现积分不能超过可用积分"),
        ]:
            form = WithdrawalRequestForm(
                data=build_withdrawal_data(points=value),
                point_source=self.point_source,
            )
            self.assertFalse(form.is_valid())
            self.assertIn(message, form.errors["points"][0])

        valid_form = WithdrawalRequestForm(
            data=build_withdrawal_data(points=80),
            point_source=self.point_source,
        )
        self.assertTrue(valid_form.is_valid())
        self.assertEqual(valid_form.cleaned_data["points"], 80)

    def test_clean_id_number_enforces_length_and_pattern(self):
        """ID number must be 18 chars and match expected pattern."""
        form = WithdrawalRequestForm(
            data=build_withdrawal_data(id_number="123"), point_source=self.point_source
        )
        self.assertFalse(form.is_valid())
        self.assertIn("身份证号必须是18位。", form.errors["id_number"][0])

        form = WithdrawalRequestForm(
            data=build_withdrawal_data(id_number="12345678901234567Z"),
            point_source=self.point_source,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("身份证号格式不正确。", form.errors["id_number"][0])

        form = WithdrawalRequestForm(
            data=build_withdrawal_data(id_number="11010119900101123x"),
            point_source=self.point_source,
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["id_number"], "11010119900101123X")

    def test_clean_phone_number_rules(self):
        """Phone number must be 11 digits and start with 1."""
        for phone, message in [
            ("1380013800", "手机号必须是11位。"),
            ("1380013800a", "手机号只能包含数字。"),
            ("23800138000", "手机号必须以1开头。"),
        ]:
            form = WithdrawalRequestForm(
                data=build_withdrawal_data(phone_number=phone),
                point_source=self.point_source,
            )
            self.assertFalse(form.is_valid())
            self.assertIn(message, form.errors["phone_number"][0])

        form = WithdrawalRequestForm(
            data=build_withdrawal_data(phone_number="19912345678"),
            point_source=self.point_source,
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["phone_number"], "19912345678")

    def test_clean_bank_account_rules(self):
        """Bank account strips spaces/dashes and checks length and digits."""
        form = WithdrawalRequestForm(
            data=build_withdrawal_data(bank_account="12345"),
            point_source=self.point_source,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("银行账号长度不正确", form.errors["bank_account"][0])

        form = WithdrawalRequestForm(
            data=build_withdrawal_data(bank_account="1234abc567"),
            point_source=self.point_source,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("银行账号只能包含数字。", form.errors["bank_account"][0])

        form = WithdrawalRequestForm(
            data=build_withdrawal_data(bank_account="6222 0202-0001 2345 6789"),
            point_source=self.point_source,
        )
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["bank_account"], "62220202000123456789")


class BatchWithdrawalInfoFormTests(TestCase):
    """Validate shared identity fields used in batch withdrawals."""

    def test_identity_and_account_validation(self):
        """Batch form mirrors the single withdrawal validators."""
        base = build_withdrawal_data()
        base.pop("points")

        form = BatchWithdrawalInfoForm(
            data={**base, "id_number": "123"},  # invalid length
        )
        self.assertFalse(form.is_valid())
        self.assertIn("身份证号必须是18位。", form.errors["id_number"][0])

        form = BatchWithdrawalInfoForm(
            data={**base, "phone_number": "1234567890a"},
        )
        self.assertFalse(form.is_valid())
        self.assertIn("手机号只能包含数字。", form.errors["phone_number"][0])

        form = BatchWithdrawalInfoForm(
            data={**base, "bank_account": "1234-ABC-567"},
        )
        self.assertFalse(form.is_valid())
        self.assertIn("银行账号只能包含数字。", form.errors["bank_account"][0])

        valid_form = BatchWithdrawalInfoForm(
            data={
                **base,
                "bank_account": "6222 0202-0001 2345",
                "phone_number": "13800138000",
            }
        )
        self.assertTrue(valid_form.is_valid())
        self.assertEqual(valid_form.cleaned_data["bank_account"], "6222020200012345")
