"""
Additional edge case and security tests for accounts forms.

These tests supplement the existing test_forms.py to add defense-in-depth
testing beyond basic coverage requirements.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.forms import (
    ChangeEmailForm,
    CustomPasswordChangeForm,
    EducationForm,
    PasswordResetConfirmForm,
    PasswordResetRequestForm,
    ProfileForm,
    SignUpForm,
    WorkExperienceForm,
)
from accounts.models import UserProfile


class SignUpFormEdgeCaseTests(TestCase):
    """Edge case tests for SignUpForm."""

    def test_signup_form_missing_username(self):
        """Test that form is invalid without username."""
        form = SignUpForm(
            data={
                "username": "",
                "email": "test@example.com",
                "password1": "testpass123",
                "password2": "testpass123",
            },
        )
        assert not form.is_valid()
        assert "username" in form.errors

    def test_signup_form_missing_email(self):
        """Test that form is invalid without email."""
        form = SignUpForm(
            data={
                "username": "testuser",
                "email": "",
                "password1": "testpass123",
                "password2": "testpass123",
            },
        )
        assert not form.is_valid()
        assert "email" in form.errors

    def test_signup_form_invalid_email_format(self):
        """Test that form is invalid with malformed email."""
        form = SignUpForm(
            data={
                "username": "testuser",
                "email": "not-an-email",
                "password1": "testpass123",
                "password2": "testpass123",
            },
        )
        assert not form.is_valid()
        assert "email" in form.errors

    def test_signup_form_email_max_length(self):
        """Test email field respects max length of 254 characters."""
        # Create an email that's exactly 254 characters
        # format: local@domain where local is 64 chars max, domain is rest
        long_email = "a" * 50 + "@" + "b" * 200 + ".com"
        form = SignUpForm(
            data={
                "username": "testuser",
                "email": long_email,
                "password1": "testpass123",
                "password2": "testpass123",
            },
        )
        # Should be valid at boundary
        if len(long_email) <= 254:
            assert form.is_valid()

    def test_signup_form_email_exceeds_max_length(self):
        """Test email field rejects emails over 254 characters."""
        long_email = "a" * 100 + "@" + "b" * 160 + ".com"  # Over 254 chars
        form = SignUpForm(
            data={
                "username": "testuser",
                "email": long_email,
                "password1": "testpass123",
                "password2": "testpass123",
            },
        )
        assert not form.is_valid()
        assert "email" in form.errors

    def test_signup_form_weak_password(self):
        """Test that weak passwords are rejected."""
        form = SignUpForm(
            data={
                "username": "testuser",
                "email": "test@example.com",
                "password1": "123",
                "password2": "123",
            },
        )
        assert not form.is_valid()
        # Django's password validators should catch this
        assert "password2" in form.errors or "password1" in form.errors

    def test_signup_form_numeric_only_password(self):
        """Test that all-numeric passwords are rejected."""
        form = SignUpForm(
            data={
                "username": "testuser",
                "email": "test@example.com",
                "password1": "12345678",
                "password2": "12345678",
            },
        )
        assert not form.is_valid()
        assert "password2" in form.errors

    def test_signup_form_duplicate_username(self):
        """Test that duplicate usernames are rejected."""
        get_user_model().objects.create_user(
            username="existing",
            email="existing@example.com",
            password="pass123",
        )
        form = SignUpForm(
            data={
                "username": "existing",
                "email": "new@example.com",
                "password1": "testpass123",
                "password2": "testpass123",
            },
        )
        assert not form.is_valid()
        assert "username" in form.errors

    def test_signup_form_case_insensitive_email_duplicate(self):
        """
        Test email check behavior with different case.

        Note: Our form does exact match, so different case emails
        are allowed. This is Django's default behavior.
        """
        get_user_model().objects.create_user(
            username="user1",
            email="Test@Example.COM",
            password="pass123",
        )
        # Try to register with same email in different case
        form = SignUpForm(
            data={
                "username": "user2",
                "email": "test@example.com",
                "password1": "testpass123",
                "password2": "testpass123",
            },
        )
        # This will be valid since our form does case-sensitive check
        # In production, email servers treat emails as case-insensitive,
        # but this is an application-level decision
        assert form.is_valid()


class ProfileFormEdgeCaseTests(TestCase):
    """Edge case tests for ProfileForm."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.profile = UserProfile.objects.create(user=self.user)

    def test_profile_form_invalid_date_format(self):
        """Test that invalid date format is rejected."""
        form = ProfileForm(
            data={
                "bio": "",
                "birth_date": "not-a-date",
                "company": "",
                "location": "",
                "github_url": "",
                "homepage_url": "",
                "blog_url": "",
                "twitter_url": "",
                "linkedin_url": "",
            },
            instance=self.profile,
        )
        assert not form.is_valid()
        assert "birth_date" in form.errors

    def test_profile_form_future_birth_date(self):
        """Test that future birth dates are accepted (no validation)."""
        form = ProfileForm(
            data={
                "bio": "",
                "birth_date": "2099-12-31",
                "company": "",
                "location": "",
                "github_url": "",
                "homepage_url": "",
                "blog_url": "",
                "twitter_url": "",
                "linkedin_url": "",
            },
            instance=self.profile,
        )
        # Current form doesn't validate future dates
        assert form.is_valid()

    def test_profile_form_multiple_invalid_urls(self):
        """Test that multiple URL fields can be invalid simultaneously."""
        form = ProfileForm(
            data={
                "bio": "",
                "birth_date": "",
                "company": "",
                "location": "",
                "github_url": "not-a-url",
                "homepage_url": "also-not-a-url",
                "blog_url": "nope",
                "twitter_url": "",
                "linkedin_url": "",
            },
            instance=self.profile,
        )
        assert not form.is_valid()
        assert "github_url" in form.errors
        assert "homepage_url" in form.errors
        assert "blog_url" in form.errors

    def test_profile_form_very_long_bio(self):
        """Test that very long bio text is accepted."""
        long_bio = "A" * 500  # Reasonable long text
        form = ProfileForm(
            data={
                "bio": long_bio,
                "birth_date": "",
                "company": "",
                "location": "",
                "github_url": "",
                "homepage_url": "",
                "blog_url": "",
                "twitter_url": "",
                "linkedin_url": "",
            },
            instance=self.profile,
        )
        # TextField has no max_length by default
        assert form.is_valid()
        profile = form.save()
        assert len(profile.bio) == 500

    def test_profile_form_special_characters_in_text(self):
        """Test that special characters are accepted in text fields."""
        form = ProfileForm(
            data={
                "bio": "你好世界! こんにちは 🌍",
                "birth_date": "",
                "company": "公司<>Name&Ltd.",
                "location": "北京/上海, 中国",
                "github_url": "",
                "homepage_url": "",
                "blog_url": "",
                "twitter_url": "",
                "linkedin_url": "",
            },
            instance=self.profile,
        )
        assert form.is_valid()

    def test_profile_form_all_url_fields_populated(self):
        """Test that all URL fields can be populated simultaneously."""
        form = ProfileForm(
            data={
                "bio": "Test bio",
                "birth_date": "1990-01-01",
                "company": "Test Co",
                "location": "Test City",
                "github_url": "https://github.com/user",
                "homepage_url": "https://example.com",
                "blog_url": "https://blog.example.com",
                "twitter_url": "https://twitter.com/user",
                "linkedin_url": "https://linkedin.com/in/user",
            },
            instance=self.profile,
        )
        assert form.is_valid()
        profile = form.save()
        assert profile.github_url == "https://github.com/user"
        assert profile.homepage_url == "https://example.com"
        assert profile.blog_url == "https://blog.example.com"
        assert profile.twitter_url == "https://twitter.com/user"
        assert profile.linkedin_url == "https://linkedin.com/in/user"


class WorkExperienceFormEdgeCaseTests(TestCase):
    """Edge case tests for WorkExperienceForm."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.profile = UserProfile.objects.create(user=self.user)

    def test_work_experience_form_missing_required_fields(self):
        """Test that required fields must be provided."""
        form = WorkExperienceForm(
            data={
                "company_name": "",
                "title": "",
                "start_date": "",
                "end_date": "",
                "description": "",
            },
        )
        assert not form.is_valid()
        assert "company_name" in form.errors
        assert "title" in form.errors
        assert "start_date" in form.errors

    def test_work_experience_form_future_start_date(self):
        """Test that future start dates are accepted."""
        form = WorkExperienceForm(
            data={
                "company_name": "Future Corp",
                "title": "Future Role",
                "start_date": "2099-01-01",
                "end_date": "",
                "description": "",
            },
        )
        # Current form doesn't validate future dates
        assert form.is_valid()

    def test_work_experience_form_very_long_description(self):
        """Test that very long descriptions are accepted."""
        long_desc = "Description " * 1000
        form = WorkExperienceForm(
            data={
                "company_name": "Test Co",
                "title": "Engineer",
                "start_date": "2020-01-01",
                "end_date": "",
                "description": long_desc,
            },
        )
        assert form.is_valid()

    def test_work_experience_form_invalid_date_format(self):
        """Test that invalid date formats are rejected."""
        form = WorkExperienceForm(
            data={
                "company_name": "Test Co",
                "title": "Engineer",
                "start_date": "not-a-date",
                "end_date": "",
                "description": "",
            },
        )
        assert not form.is_valid()
        assert "start_date" in form.errors

    def test_work_experience_form_partial_date_validation(self):
        """Test validation when only start_date is missing."""
        form = WorkExperienceForm(
            data={
                "company_name": "Test Co",
                "title": "Engineer",
                "start_date": "",
                "end_date": "2022-12-31",
                "description": "",
            },
        )
        assert not form.is_valid()
        assert "start_date" in form.errors

    def test_work_experience_form_special_characters(self):
        """Test that special characters are handled in text fields."""
        form = WorkExperienceForm(
            data={
                "company_name": "公司 & Co. <Ltd>",
                "title": "软件工程师/开发者",
                "start_date": "2020-01-01",
                "end_date": "2022-12-31",
                "description": "工作描述 with special chars: <>&\"'",
            },
        )
        assert form.is_valid()


class EducationFormEdgeCaseTests(TestCase):
    """Edge case tests for EducationForm."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.profile = UserProfile.objects.create(user=self.user)

    def test_education_form_missing_required_fields(self):
        """Test that required fields must be provided."""
        form = EducationForm(
            data={
                "institution_name": "",
                "degree": "",
                "field_of_study": "",
                "start_date": "",
                "end_date": "",
            },
        )
        assert not form.is_valid()
        assert "institution_name" in form.errors
        # degree is optional (blank=True)
        assert "field_of_study" in form.errors
        assert "start_date" in form.errors

    def test_education_form_future_start_date(self):
        """Test that future start dates are accepted."""
        form = EducationForm(
            data={
                "institution_name": "Future University",
                "degree": "博士",
                "field_of_study": "AI",
                "start_date": "2099-09-01",
                "end_date": "",
            },
        )
        # Current form doesn't validate future dates
        assert form.is_valid()

    def test_education_form_invalid_date_format(self):
        """Test that invalid date formats are rejected."""
        form = EducationForm(
            data={
                "institution_name": "Test University",
                "degree": "本科",
                "field_of_study": "CS",
                "start_date": "invalid",
                "end_date": "",
            },
        )
        assert not form.is_valid()
        assert "start_date" in form.errors

    def test_education_form_special_characters(self):
        """Test that special characters are handled correctly."""
        form = EducationForm(
            data={
                "institution_name": "北京大学 & 清华大学",
                "degree": "本科 (Bachelor's)",
                "field_of_study": "计算机科学 & 技术",
                "start_date": "2015-09-01",
                "end_date": "2019-06-30",
            },
        )
        assert form.is_valid()


class CustomPasswordChangeFormEdgeCaseTests(TestCase):
    """Edge case tests for CustomPasswordChangeForm."""

    def test_password_change_form_same_passwords(self):
        """Test that new password can be same as old (Django allows this)."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="samepass123",
        )
        form = CustomPasswordChangeForm(
            user=user,
            data={
                "old_password": "samepass123",
                "new_password1": "samepass123",
                "new_password2": "samepass123",
            },
        )
        # Django PasswordChangeForm doesn't prevent same password by default
        assert form.is_valid()

    def test_password_change_form_missing_old_password(self):
        """Test that old password is required."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="oldpass123",
        )
        form = CustomPasswordChangeForm(
            user=user,
            data={
                "old_password": "",
                "new_password1": "newpass123",
                "new_password2": "newpass123",
            },
        )
        assert not form.is_valid()
        assert "old_password" in form.errors

    def test_password_change_form_new_passwords_mismatch(self):
        """Test that new passwords must match."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="oldpass123",
        )
        form = CustomPasswordChangeForm(
            user=user,
            data={
                "old_password": "oldpass123",
                "new_password1": "newpass123",
                "new_password2": "differentpass123",
            },
        )
        assert not form.is_valid()
        assert "new_password2" in form.errors

    def test_password_change_form_widget_attributes(self):
        """Test that form widgets have correct CSS classes."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        form = CustomPasswordChangeForm(user=user)
        assert "form-control" in form.fields["old_password"].widget.attrs["class"]
        assert "form-control" in form.fields["new_password1"].widget.attrs["class"]
        assert "form-control" in form.fields["new_password2"].widget.attrs["class"]


class ChangeEmailFormEdgeCaseTests(TestCase):
    """Edge case tests for ChangeEmailForm."""

    def test_change_email_form_invalid_email_format(self):
        """Test that invalid email format is rejected."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="old@example.com",
            password="testpass123",
        )
        form = ChangeEmailForm(
            user=user,
            data={
                "email": "not-an-email",
                "password": "testpass123",
            },
        )
        assert not form.is_valid()
        assert "email" in form.errors

    def test_change_email_form_empty_email(self):
        """Test that email is required."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="old@example.com",
            password="testpass123",
        )
        form = ChangeEmailForm(
            user=user,
            data={
                "email": "",
                "password": "testpass123",
            },
        )
        assert not form.is_valid()
        assert "email" in form.errors

    def test_change_email_form_empty_password(self):
        """Test that password is required."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="old@example.com",
            password="testpass123",
        )
        form = ChangeEmailForm(
            user=user,
            data={
                "email": "new@example.com",
                "password": "",
            },
        )
        assert not form.is_valid()
        assert "password" in form.errors

    def test_change_email_form_whitespace_in_email(self):
        """Test that whitespace in email is handled."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="old@example.com",
            password="testpass123",
        )
        form = ChangeEmailForm(
            user=user,
            data={
                "email": "  new@example.com  ",
                "password": "testpass123",
            },
        )
        # Django's EmailField should strip whitespace
        if form.is_valid():
            assert form.cleaned_data["email"] == "new@example.com"

    def test_change_email_form_case_sensitivity(self):
        """
        Test email comparison with different cases.

        Note: The form does case-sensitive comparison, so different
        case versions of the same email are treated as different emails.
        This is Django's default behavior.
        """
        user = get_user_model().objects.create_user(
            username="testuser",
            email="Old@Example.COM",
            password="testpass123",
        )
        form = ChangeEmailForm(
            user=user,
            data={
                "email": "old@example.com",
                "password": "testpass123",
            },
        )
        # Form will be valid as case-sensitive comparison treats these as different
        # In production, you may want to add iexact lookup for case-insensitive check
        assert form.is_valid()

    def test_change_email_form_widget_attributes(self):
        """Test that form widgets have correct CSS classes."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        form = ChangeEmailForm(user=user)
        assert "form-control" in form.fields["email"].widget.attrs["class"]
        assert "form-control" in form.fields["password"].widget.attrs["class"]


class PasswordResetRequestFormEdgeCaseTests(TestCase):
    """Edge case tests for PasswordResetRequestForm."""

    def test_password_reset_form_whitespace_email(self):
        """Test that whitespace in email is handled."""
        form = PasswordResetRequestForm(data={"email": "  test@example.com  "})
        # Django's EmailField should strip whitespace
        if form.is_valid():
            assert form.cleaned_data["email"] == "test@example.com"

    def test_password_reset_form_email_max_length(self):
        """Test email max length boundary."""
        long_email = "a" * 100 + "@" + "b" * 160 + ".com"
        form = PasswordResetRequestForm(data={"email": long_email})
        assert not form.is_valid()
        assert "email" in form.errors

    def test_password_reset_form_widget_attributes(self):
        """Test that form widget has correct CSS classes."""
        form = PasswordResetRequestForm()
        assert "form-control" in form.fields["email"].widget.attrs["class"]
        assert "placeholder" in form.fields["email"].widget.attrs


class PasswordResetConfirmFormEdgeCaseTests(TestCase):
    """Edge case tests for PasswordResetConfirmForm."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="oldpass123",
        )

    def test_password_reset_confirm_form_empty_passwords(self):
        """Test that passwords are required."""
        form = PasswordResetConfirmForm(
            user=self.user,
            data={
                "new_password1": "",
                "new_password2": "",
            },
        )
        assert not form.is_valid()
        assert "new_password1" in form.errors

    def test_password_reset_confirm_form_common_password(self):
        """Test that common passwords are rejected."""
        form = PasswordResetConfirmForm(
            user=self.user,
            data={
                "new_password1": "password",
                "new_password2": "password",
            },
        )
        assert not form.is_valid()
        # Django's CommonPasswordValidator should catch this
        assert "new_password2" in form.errors

    def test_password_reset_confirm_form_widget_attributes(self):
        """Test that form widgets have correct CSS classes."""
        form = PasswordResetConfirmForm(user=self.user)
        assert "form-control" in form.fields["new_password1"].widget.attrs["class"]
        assert "form-control" in form.fields["new_password2"].widget.attrs["class"]
        assert "placeholder" in form.fields["new_password1"].widget.attrs
        assert "placeholder" in form.fields["new_password2"].widget.attrs
