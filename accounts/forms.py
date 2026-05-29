"""Forms for user profile management and account merging."""

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from .email_addresses import normalize_email_address
from .models import (
    AccountMergeRequest,
    Education,
    ShippingAddress,
    UserProfile,
    WorkExperience,
)


class ProfileForm(forms.ModelForm):
    """User profile editing form."""

    class Meta:
        """Meta configuration for ProfileForm."""

        model = UserProfile
        fields = [
            "bio",
            "birth_date",
            "github_url",
            "homepage_url",
            "blog_url",
            "twitter_url",
            "linkedin_url",
            "company",
            "location",
        ]
        widgets = {
            "bio": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "介绍一下你自己...",
                },
            ),
            "birth_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"},
            ),
            "github_url": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "https://github.com/username",
                },
            ),
            "homepage_url": forms.URLInput(
                attrs={"class": "form-control", "placeholder": "https://yoursite.com"},
            ),
            "blog_url": forms.URLInput(
                attrs={"class": "form-control", "placeholder": "https://yourblog.com"},
            ),
            "twitter_url": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "https://twitter.com/username",
                },
            ),
            "linkedin_url": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "https://linkedin.com/in/username",
                },
            ),
            "company": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "公司名称"},
            ),
            "location": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "城市, 国家"},
            ),
        }


class WorkExperienceForm(forms.ModelForm):
    """Work experience form."""

    class Meta:
        """Meta configuration for WorkExperienceForm."""

        model = WorkExperience
        fields = ["company_name", "title", "start_date", "end_date", "description"]
        widgets = {
            "company_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "公司名称"},
            ),
            "title": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "职位"},
            ),
            "start_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"},
            ),
            "end_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"},
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "工作描述（可选）",
                },
            ),
        }

    def clean(self):
        """Validate that start_date is before end_date."""
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")

        if start_date and end_date and start_date >= end_date:
            msg = "开始日期必须早于结束日期"
            raise forms.ValidationError(msg)

        return cleaned_data


class EducationForm(forms.ModelForm):
    """Education form."""

    class Meta:
        """Meta configuration for EducationForm."""

        model = Education
        fields = [
            "institution_name",
            "degree",
            "field_of_study",
            "start_date",
            "end_date",
        ]
        widgets = {
            "institution_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "学校/机构名称"},
            ),
            "degree": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "学位（如：本科、硕士）",
                },
            ),
            "field_of_study": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "专业领域"},
            ),
            "start_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"},
            ),
            "end_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"},
            ),
        }

    def clean(self):
        """Validate that start_date is before end_date."""
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")

        if start_date and end_date and start_date >= end_date:
            msg = "开始日期必须早于结束日期"
            raise forms.ValidationError(msg)

        return cleaned_data


class ShippingAddressForm(forms.ModelForm):
    """Shipping address form."""

    class Meta:
        """Meta configuration for ShippingAddressForm."""

        model = ShippingAddress
        fields = [
            "receiver_name",
            "phone",
            "province",
            "city",
            "district",
            "address",
            "is_default",
        ]
        widgets = {
            "receiver_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "收件人姓名"},
            ),
            "phone": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "联系电话"},
            ),
            "province": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "省份"},
            ),
            "city": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "城市"},
            ),
            "district": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "区/县"},
            ),
            "address": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "详细地址"},
            ),
            "is_default": forms.CheckboxInput(
                attrs={"class": "form-check-input"},
            ),
        }


class AccountMergeRequestForm(forms.Form):
    """Form for initiating an account merge request."""

    target_username = forms.CharField(
        label="目标用户名",
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "请输入目标账号的用户名",
            },
        ),
    )
    target_email = forms.EmailField(
        label="目标邮箱",
        required=False,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "placeholder": "请输入目标账号绑定的邮箱",
            },
        ),
    )

    def __init__(self, user, *args, **kwargs):
        """Store source user for validation rules."""
        self.user = user
        self.target_user = None
        super().__init__(*args, **kwargs)

    def clean(self):
        """Validate target user existence and business constraints."""
        cleaned = super().clean()
        username = cleaned.get("target_username")
        email = normalize_email_address(cleaned.get("target_email"))
        cleaned["target_email"] = email

        now = timezone.now()
        # expire stale pending requests globally to avoid blocking new submissions
        AccountMergeRequest.objects.filter(
            status=AccountMergeRequest.Status.PENDING, expires_at__lte=now
        ).update(
            status=AccountMergeRequest.Status.EXPIRED,
            processed_at=now,
            processed_by=None,
        )

        if not username and not email:
            msg = "请输入目标账号的邮箱或用户名（至少一项）"
            raise forms.ValidationError(msg, code="merge_target_required")

        UserModel = get_user_model()
        qs = UserModel.objects.filter(is_active=True)
        if username and email:
            qs = qs.filter(username=username, email__iexact=email)
        elif username:
            qs = qs.filter(username=username)
        else:
            qs = qs.filter(email__iexact=email)

        try:
            target = qs.get()
        except UserModel.DoesNotExist:
            msg = "未找到匹配的目标账号，请检查用户名或邮箱是否正确"
            raise forms.ValidationError(msg, code="merge_target_not_found") from None
        except UserModel.MultipleObjectsReturned:
            msg = "匹配到多个账号，请同时提供用户名和邮箱以精确匹配"
            raise forms.ValidationError(msg, code="merge_target_ambiguous") from None

        if self.user.is_staff or self.user.is_superuser:
            msg = "管理员账号不支持发起合并"
            raise forms.ValidationError(msg, code="merge_source_is_staff")
        if not self.user.is_active:
            msg = "当前账号已被停用，无法发起合并"
            raise forms.ValidationError(msg, code="merge_source_inactive")

        if target == self.user:
            msg = "不能合并到自己的账号"
            raise forms.ValidationError(msg, code="merge_target_is_self")
        if target.is_staff or target.is_superuser:
            msg = "目标账号为管理员，无法合并"
            raise forms.ValidationError(msg, code="merge_target_is_staff")

        # Only one pending request per source
        if AccountMergeRequest.objects.filter(
            source_user=self.user,
            status=AccountMergeRequest.Status.PENDING,
        ).exists():
            msg = "您已有待处理的合并申请，请等待处理后再尝试"
            raise forms.ValidationError(msg, code="merge_source_has_pending")

        # Cap pending requests per target
        pending_for_target = AccountMergeRequest.objects.filter(
            target_user=target,
            status=AccountMergeRequest.Status.PENDING,
        ).count()
        if pending_for_target >= 3:
            msg = "该目标账号待处理申请过多，请稍后再试"
            raise forms.ValidationError(msg, code="merge_target_pending_limit")

        self.target_user = target
        return cleaned
