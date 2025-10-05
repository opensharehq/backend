from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm


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
