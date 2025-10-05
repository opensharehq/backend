from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import Education, UserProfile, WorkExperience


class SignUpForm(UserCreationForm):
    """User registration form."""

    email = forms.EmailField(
        max_length=254,
        required=True,
        help_text="请输入有效的邮箱地址",
    )

    class Meta:
        model = get_user_model()
        fields = ("username", "email", "password1", "password2")

    def clean_email(self):
        """Validate email is unique."""
        email = self.cleaned_data.get("email")
        if get_user_model().objects.filter(email=email).exists():
            raise forms.ValidationError("该邮箱已被注册")
        return email


class ProfileForm(forms.ModelForm):
    """User profile editing form."""

    class Meta:
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
                }
            ),
            "birth_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "github_url": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "https://github.com/username",
                }
            ),
            "homepage_url": forms.URLInput(
                attrs={"class": "form-control", "placeholder": "https://yoursite.com"}
            ),
            "blog_url": forms.URLInput(
                attrs={"class": "form-control", "placeholder": "https://yourblog.com"}
            ),
            "twitter_url": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "https://twitter.com/username",
                }
            ),
            "linkedin_url": forms.URLInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "https://linkedin.com/in/username",
                }
            ),
            "company": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "公司名称"}
            ),
            "location": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "城市, 国家"}
            ),
        }


class WorkExperienceForm(forms.ModelForm):
    """Work experience form."""

    class Meta:
        model = WorkExperience
        fields = ["company_name", "title", "start_date", "end_date", "description"]
        widgets = {
            "company_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "公司名称"}
            ),
            "title": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "职位"}
            ),
            "start_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "end_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "工作描述（可选）",
                }
            ),
        }

    def clean(self):
        """Validate that start_date is before end_date."""
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")

        if start_date and end_date and start_date >= end_date:
            raise forms.ValidationError("开始日期必须早于结束日期")

        return cleaned_data


class EducationForm(forms.ModelForm):
    """Education form."""

    class Meta:
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
                attrs={"class": "form-control", "placeholder": "学校/机构名称"}
            ),
            "degree": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "学位（如：本科、硕士）"}
            ),
            "field_of_study": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "专业领域"}
            ),
            "start_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
            "end_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"}
            ),
        }

    def clean(self):
        """Validate that start_date is before end_date."""
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")

        if start_date and end_date and start_date >= end_date:
            raise forms.ValidationError("开始日期必须早于结束日期")

        return cleaned_data
