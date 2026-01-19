"""Forms for points application."""

from django import forms

from . import services
from .models import PointType, Tag, WithdrawalRequest


class WithdrawalRequestForm(forms.ModelForm):
    """Form for creating withdrawal requests."""

    class Meta:
        """Form metadata."""

        model = WithdrawalRequest
        fields = ["amount", "real_name", "phone", "bank_name", "bank_account"]
        widgets = {
            "amount": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "请输入提现金额",
                    "min": "1",
                }
            ),
            "real_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "请输入真实姓名",
                }
            ),
            "phone": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "请输入联系电话",
                }
            ),
            "bank_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "请输入银行名称，如：中国银行",
                }
            ),
            "bank_account": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "请输入银行账号",
                }
            ),
        }

    def __init__(self, owner, *args, **kwargs):
        """Initialize form with owner."""
        super().__init__(*args, **kwargs)
        self.owner = owner

    def clean_amount(self):
        """Validate amount against available balance."""
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            msg = "提现金额必须大于 0"
            raise forms.ValidationError(msg)

        balance = services.get_balance(self.owner, PointType.CASH)
        if amount > balance:
            msg = f"现金积分不足，当前可用: {balance}"
            raise forms.ValidationError(msg)

        return amount

    def clean_phone(self):
        """Validate phone number format."""
        phone = self.cleaned_data["phone"]
        # 简单的手机号验证（中国大陆手机号）
        if not phone.isdigit() or len(phone) != 11:
            msg = "请输入有效的手机号码（11位数字）"
            raise forms.ValidationError(msg)
        return phone

    def clean_bank_account(self):
        """Validate bank account format."""
        account = self.cleaned_data["bank_account"]
        # 简单的银行卡号验证（16-19位数字）
        cleaned = account.replace(" ", "").replace("-", "")
        if not cleaned.isdigit() or not (16 <= len(cleaned) <= 19):
            msg = "请输入有效的银行卡号（16-19位数字）"
            raise forms.ValidationError(msg)
        return cleaned


class GrantPointsForm(forms.Form):
    """Form for granting points to users or organizations."""

    POINT_TYPE_CHOICES = [
        (PointType.CASH.value, "现金积分"),
        (PointType.GIFT.value, "礼物积分"),
    ]

    point_type = forms.ChoiceField(
        choices=POINT_TYPE_CHOICES,
        label="积分类型",
        widget=forms.RadioSelect,
    )
    amount = forms.IntegerField(
        min_value=1,
        label="积分数量",
        help_text="请输入正整数",
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )
    reason = forms.CharField(
        max_length=500,
        label="发放描述",
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
    )
    tag = forms.ModelChoiceField(
        queryset=Tag.objects.all(),
        required=False,
        label="标签",
        help_text="仅礼物积分需要选择标签",
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    expires_at = forms.DateField(
        required=False,
        label="过期时间",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    reference_id = forms.CharField(
        max_length=100,
        required=False,
        label="参考ID",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )

    def clean(self):
        """Validate form data."""
        cleaned_data = super().clean()
        point_type = cleaned_data.get("point_type")
        tag = cleaned_data.get("tag")

        if point_type == PointType.GIFT.value and not tag:
            msg = "礼物积分必须选择标签"
            raise forms.ValidationError(msg)

        if point_type == PointType.CASH.value and tag:
            msg = "现金积分不能选择标签"
            raise forms.ValidationError(msg)

        return cleaned_data
