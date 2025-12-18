"""Forms for the points app."""

import re

from django import forms

from .models import WithdrawalRequest


class WithdrawalRequestForm(forms.ModelForm):
    """提现申请表单."""

    class Meta:
        """表单元数据配置."""

        model = WithdrawalRequest
        fields = [
            "points",
            "real_name",
            "id_number",
            "phone_number",
            "bank_name",
            "bank_account",
        ]
        widgets = {
            "points": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "请输入提现积分数量",
                    "min": "1",
                }
            ),
            "real_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "请输入真实姓名",
                    "maxlength": "100",
                }
            ),
            "id_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "请输入身份证号（18位）",
                    "maxlength": "18",
                }
            ),
            "phone_number": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "请输入手机号（11位）",
                    "maxlength": "11",
                }
            ),
            "bank_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "请输入开户银行名称",
                    "maxlength": "100",
                }
            ),
            "bank_account": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "请输入银行账号",
                    "maxlength": "50",
                }
            ),
        }
        labels = {
            "points": "提现积分数量",
            "real_name": "真实姓名",
            "id_number": "身份证号",
            "phone_number": "手机号",
            "bank_name": "开户银行",
            "bank_account": "银行账号",
        }

    def __init__(self, *args, point_source=None, signed_contract=None, **kwargs):
        """初始化表单, 保存积分来源引用."""
        super().__init__(*args, **kwargs)
        self.point_source = point_source
        self.signed_contract = signed_contract

        # 如果有积分来源，设置提现积分的最大值
        if point_source:
            self.fields["points"].widget.attrs["max"] = point_source.remaining_points
            self.fields[
                "points"
            ].help_text = f"可提现积分: {point_source.remaining_points}"

        if signed_contract:
            locked_fields = [
                "real_name",
                "id_number",
                "phone_number",
                "bank_name",
                "bank_account",
            ]
            for field_name in locked_fields:
                field = self.fields[field_name]
                field.required = False
                field.disabled = True
                field.initial = getattr(signed_contract, field_name, "")
                field.widget.attrs["readonly"] = True
            self.fields["points"].help_text = (
                (self.fields["points"].help_text or "") + "（已完成合同签署）"
            ).strip()

    def clean_points(self):
        """验证提现积分数量."""
        points = self.cleaned_data.get("points")

        if points is None:
            msg = "请输入提现积分数量。"
            raise forms.ValidationError(msg)

        if points <= 0:
            msg = "提现积分必须大于0。"
            raise forms.ValidationError(msg)

        # 如果有积分来源，验证是否超过剩余积分
        if self.point_source and points > self.point_source.remaining_points:
            msg = f"提现积分不能超过可用积分。可用积分: {self.point_source.remaining_points}"
            raise forms.ValidationError(msg)

        return points

    def clean_id_number(self):
        """验证身份证号格式."""
        id_number = self.cleaned_data.get("id_number")
        if not id_number:
            return id_number

        # 验证长度
        if len(id_number) != 18:
            msg = "身份证号必须是18位。"
            raise forms.ValidationError(msg)

        # 验证格式：前17位是数字，最后一位是数字或X
        pattern = r"^\d{17}[\dXx]$"
        if not re.match(pattern, id_number):
            msg = "身份证号格式不正确。"
            raise forms.ValidationError(msg)

        return id_number.upper()  # 统一转换为大写

    def clean_phone_number(self):
        """验证手机号格式."""
        phone_number = self.cleaned_data.get("phone_number")
        if not phone_number:
            return phone_number

        # 验证长度
        if len(phone_number) != 11:
            msg = "手机号必须是11位。"
            raise forms.ValidationError(msg)

        # 验证是否全是数字
        if not phone_number.isdigit():
            msg = "手机号只能包含数字。"
            raise forms.ValidationError(msg)

        # 验证是否以1开头
        if not phone_number.startswith("1"):
            msg = "手机号必须以1开头。"
            raise forms.ValidationError(msg)

        return phone_number

    def clean_bank_account(self):
        """验证银行账号格式."""
        bank_account = self.cleaned_data.get("bank_account")
        if not bank_account:
            return bank_account

        # 移除空格和横杠
        bank_account = bank_account.replace(" ", "").replace("-", "")

        # 验证是否全是数字
        if not bank_account.isdigit():
            msg = "银行账号只能包含数字。"
            raise forms.ValidationError(msg)

        # 验证长度（一般银行卡号是16-19位）
        if len(bank_account) < 10 or len(bank_account) > 25:
            msg = "银行账号长度不正确（应为10-25位）。"
            raise forms.ValidationError(msg)

        return bank_account


class BatchWithdrawalInfoForm(forms.Form):
    """批量提现基础信息表单."""

    real_name = forms.CharField(
        max_length=100,
        label="真实姓名",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "请输入真实姓名",
                "maxlength": "100",
            }
        ),
    )
    id_number = forms.CharField(
        max_length=18,
        label="身份证号",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "请输入身份证号（18位）",
                "maxlength": "18",
            }
        ),
    )
    phone_number = forms.CharField(
        max_length=11,
        label="手机号",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "请输入手机号（11位）",
                "maxlength": "11",
            }
        ),
    )
    bank_name = forms.CharField(
        max_length=100,
        label="开户银行",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "请输入开户银行名称",
                "maxlength": "100",
            }
        ),
    )
    bank_account = forms.CharField(
        max_length=50,
        label="银行账号",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "请输入银行账号",
                "maxlength": "50",
            }
        ),
    )

    def clean_id_number(self):
        """验证身份证号格式."""
        id_number = self.cleaned_data.get("id_number")
        if not id_number:
            return id_number

        # 验证长度
        if len(id_number) != 18:
            msg = "身份证号必须是18位。"
            raise forms.ValidationError(msg)

        # 验证格式：前17位是数字，最后一位是数字或X
        pattern = r"^\d{17}[\dXx]$"
        if not re.match(pattern, id_number):
            msg = "身份证号格式不正确。"
            raise forms.ValidationError(msg)

        return id_number.upper()  # 统一转换为大写

    def clean_phone_number(self):
        """验证手机号格式."""
        phone_number = self.cleaned_data.get("phone_number")
        if not phone_number:
            return phone_number

        # 验证长度
        if len(phone_number) != 11:
            msg = "手机号必须是11位。"
            raise forms.ValidationError(msg)

        # 验证是否全是数字
        if not phone_number.isdigit():
            msg = "手机号只能包含数字。"
            raise forms.ValidationError(msg)

        # 验证是否以1开头
        if not phone_number.startswith("1"):
            msg = "手机号必须以1开头。"
            raise forms.ValidationError(msg)

        return phone_number

    def clean_bank_account(self):
        """验证银行账号格式."""
        bank_account = self.cleaned_data.get("bank_account")
        if not bank_account:
            return bank_account

        # 移除空格和横杠
        bank_account = bank_account.replace(" ", "").replace("-", "")

        # 验证是否全是数字
        if not bank_account.isdigit():
            msg = "银行账号只能包含数字。"
            raise forms.ValidationError(msg)

        # 验证长度（一般银行卡号是16-19位）
        if len(bank_account) < 10 or len(bank_account) > 25:
            msg = "银行账号长度不正确（应为10-25位）。"
            raise forms.ValidationError(msg)

        return bank_account

    def __init__(self, *args, point_source=None, **kwargs):
        """初始化表单, 保存积分来源引用."""
        signed_contract = kwargs.pop("signed_contract", None)
        super().__init__(*args, **kwargs)
        self.point_source = point_source

        if signed_contract:
            locked_fields = [
                "real_name",
                "id_number",
                "phone_number",
                "bank_name",
                "bank_account",
            ]
            for field_name in locked_fields:
                field = self.fields[field_name]
                field.required = False
                field.disabled = True
                field.initial = getattr(signed_contract, field_name, "")
                field.widget.attrs["readonly"] = True

        # 如果有积分来源，设置提现积分的最大值
        if point_source:
            self.fields["points"].widget.attrs["max"] = point_source.remaining_points
            self.fields[
                "points"
            ].help_text = f"可提现积分: {point_source.remaining_points}"

    def clean_points(self):
        """验证提现积分数量."""
        points = self.cleaned_data.get("points")

        if points is None:
            msg = "请输入提现积分数量。"
            raise forms.ValidationError(msg)

        if points <= 0:
            msg = "提现积分必须大于0。"
            raise forms.ValidationError(msg)

        # 如果有积分来源，验证是否超过剩余积分
        if self.point_source and points > self.point_source.remaining_points:
            msg = f"提现积分不能超过可用积分。可用积分: {self.point_source.remaining_points}"
            raise forms.ValidationError(msg)

        return points
