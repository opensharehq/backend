"""Forms for user authentication and profile management."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    PasswordChangeForm,
    SetPasswordForm,
    UserCreationForm,
)

from .models import Education, ShippingAddress, UserProfile, WorkExperience


class SignUpForm(UserCreationForm):
    """User registration form."""

    email = forms.EmailField(
        max_length=254,
        required=True,
        help_text="请输入有效的邮箱地址",
    )

    class Meta:
        """Meta configuration for SignUpForm."""

        model = get_user_model()
        fields = ("username", "email", "password1", "password2")

    def clean_email(self):
        """Validate email is unique."""
        email = self.cleaned_data.get("email")
        if get_user_model().objects.filter(email=email).exists():
            msg = "该邮箱已被注册"
            raise forms.ValidationError(msg)
        return email


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


class CustomPasswordChangeForm(PasswordChangeForm):
    """Custom password change form with Bootstrap styling."""

    old_password = forms.CharField(
        label="当前密码",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "请输入当前密码",
            },
        ),
    )
    new_password1 = forms.CharField(
        label="新密码",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "请输入新密码",
            },
        ),
        help_text="密码至少8位，不能全是数字",
    )
    new_password2 = forms.CharField(
        label="确认新密码",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "请再次输入新密码",
            },
        ),
    )


class ChangeEmailForm(forms.Form):
    """Email change form."""

    email = forms.EmailField(
        label="新邮箱",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "placeholder": "请输入新邮箱地址",
            },
        ),
    )
    password = forms.CharField(
        label="当前密码",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "请输入当前密码以确认",
            },
        ),
        help_text="为了安全，需要验证您的当前密码",
    )

    def __init__(self, user, *args, **kwargs):
        """Initialize form with user instance."""
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_email(self):
        """Validate email is unique and different from current."""
        email = self.cleaned_data.get("email")

        if email == self.user.email:
            msg = "新邮箱不能与当前邮箱相同"
            raise forms.ValidationError(msg)

        if get_user_model().objects.filter(email=email).exists():
            msg = "该邮箱已被其他用户使用"
            raise forms.ValidationError(msg)

        return email

    def clean_password(self):
        """Validate password is correct."""
        password = self.cleaned_data.get("password")

        if not self.user.check_password(password):
            msg = "密码不正确"
            raise forms.ValidationError(msg)

        return password


class PasswordResetRequestForm(forms.Form):
    """Password reset request form."""

    email = forms.EmailField(
        label="邮箱地址",
        max_length=254,
        widget=forms.EmailInput(
            attrs={
                "class": "form-control",
                "placeholder": "请输入注册时使用的邮箱",
            },
        ),
        help_text="我们将向此邮箱发送密码重置链接",
    )


class PasswordResetConfirmForm(SetPasswordForm):
    """Password reset confirmation form."""

    new_password1 = forms.CharField(
        label="新密码",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "请输入新密码",
            },
        ),
        help_text="密码至少8位，不能全是数字",
    )
    new_password2 = forms.CharField(
        label="确认新密码",
        widget=forms.PasswordInput(
            attrs={
                "class": "form-control",
                "placeholder": "请再次输入新密码",
            },
        ),
    )


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
