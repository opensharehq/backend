"""Direct coverage for optional field branches in WithdrawalRequestForm."""

from django import forms
from django.test import SimpleTestCase

from points.forms import BatchWithdrawalInfoForm, WithdrawalRequestForm


class WithdrawalRequestFormLineHitTests(SimpleTestCase):
    """Explicitly exercise early returns and specific validation errors."""

    def test_optional_fields_return_unchanged(self):
        form = WithdrawalRequestForm()
        form.cleaned_data = {"id_number": None}
        self.assertIsNone(form.clean_id_number())

        form.cleaned_data = {"phone_number": None}
        self.assertIsNone(form.clean_phone_number())

        form.cleaned_data = {"bank_account": None}
        self.assertIsNone(form.clean_bank_account())

    def test_invalid_values_raise_expected_errors(self):
        form = WithdrawalRequestForm()

        form.cleaned_data = {"id_number": "12345678901234567Z"}
        with self.assertRaisesMessage(forms.ValidationError, "身份证号格式不正确。"):
            form.clean_id_number()

        form.cleaned_data = {"phone_number": "29800138000"}
        with self.assertRaisesMessage(forms.ValidationError, "手机号必须以1开头。"):
            form.clean_phone_number()

        form.cleaned_data = {"bank_account": "9" * 30}
        with self.assertRaisesMessage(
            forms.ValidationError, "银行账号长度不正确（应为10-25位）。"
        ):
            form.clean_bank_account()


class BatchWithdrawalInfoFormBranchTests(SimpleTestCase):
    """Cover optional/validation branches on the batch form."""

    def test_optional_fields_return_unchanged(self):
        form = BatchWithdrawalInfoForm()
        form.cleaned_data = {"id_number": ""}
        self.assertEqual(form.clean_id_number(), "")

        form.cleaned_data = {"phone_number": ""}
        self.assertEqual(form.clean_phone_number(), "")

        form.cleaned_data = {"bank_account": ""}
        self.assertEqual(form.clean_bank_account(), "")

    def test_invalid_values_raise_expected_errors(self):
        form = BatchWithdrawalInfoForm()

        form.cleaned_data = {"id_number": "12345678901234567A"}
        with self.assertRaisesMessage(forms.ValidationError, "身份证号格式不正确。"):
            form.clean_id_number()

        form.cleaned_data = {"phone_number": "23800138000"}
        with self.assertRaisesMessage(forms.ValidationError, "手机号必须以1开头。"):
            form.clean_phone_number()

        form.cleaned_data = {"bank_account": "1" * 30}
        with self.assertRaisesMessage(
            forms.ValidationError, "银行账号长度不正确（应为10-25位）。"
        ):
            form.clean_bank_account()
