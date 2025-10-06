"""Tests for accounts forms."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.forms import (
    EducationForm,
    PasswordResetConfirmForm,
    PasswordResetRequestForm,
    ProfileForm,
    SignUpForm,
    WorkExperienceForm,
)
from accounts.models import UserProfile


class SignUpFormTests(TestCase):
    """Test cases for SignUpForm."""

    def test_signup_form_valid_data(self):
        """Test that form is valid with correct data."""
        form = SignUpForm(
            data={
                "username": "testuser",
                "email": "test@example.com",
                "password1": "testpass123",
                "password2": "testpass123",
            },
        )
        assert form.is_valid()

    def test_signup_form_duplicate_email(self):
        """Test that form is invalid with duplicate email."""
        get_user_model().objects.create_user(
            username="existing",
            email="test@example.com",
            password="pass123",
        )
        form = SignUpForm(
            data={
                "username": "newuser",
                "email": "test@example.com",
                "password1": "testpass123",
                "password2": "testpass123",
            },
        )
        assert not form.is_valid()
        assert "email" in form.errors

    def test_signup_form_password_mismatch(self):
        """Test that form is invalid when passwords don't match."""
        form = SignUpForm(
            data={
                "username": "testuser",
                "email": "test@example.com",
                "password1": "testpass123",
                "password2": "wrongpass123",
            },
        )
        assert not form.is_valid()

    def test_signup_form_creates_user(self):
        """Test that form successfully creates a new user."""
        form = SignUpForm(
            data={
                "username": "testuser",
                "email": "test@example.com",
                "password1": "testpass123",
                "password2": "testpass123",
            },
        )
        assert form.is_valid()
        user = form.save()
        assert user.username == "testuser"
        assert user.email == "test@example.com"
        assert user.check_password("testpass123")


class ProfileFormTests(TestCase):
    """Test cases for ProfileForm."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.profile = UserProfile.objects.create(user=self.user)

    def test_profile_form_valid_data(self):
        """Test that profile form is valid with complete data."""
        form = ProfileForm(
            data={
                "bio": "Test bio",
                "birth_date": "1990-01-01",
                "company": "Test Company",
                "location": "Test City",
                "github_url": "https://github.com/testuser",
                "homepage_url": "https://example.com",
                "blog_url": "https://blog.example.com",
                "twitter_url": "https://twitter.com/testuser",
                "linkedin_url": "https://linkedin.com/in/testuser",
            },
            instance=self.profile,
        )
        assert form.is_valid()

    def test_profile_form_empty_data(self):
        """Test that profile form is valid with empty optional fields."""
        form = ProfileForm(
            data={
                "bio": "",
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
        assert form.is_valid()

    def test_profile_form_saves_data(self):
        """Test that profile form saves data correctly."""
        form = ProfileForm(
            data={
                "bio": "Updated bio",
                "birth_date": "1990-01-01",
                "company": "Updated Company",
                "location": "Updated City",
                "github_url": "https://github.com/updated",
                "homepage_url": "",
                "blog_url": "",
                "twitter_url": "",
                "linkedin_url": "",
            },
            instance=self.profile,
        )
        assert form.is_valid()
        profile = form.save()
        assert profile.bio == "Updated bio"
        assert profile.company == "Updated Company"
        assert profile.location == "Updated City"
        assert profile.github_url == "https://github.com/updated"

    def test_profile_form_invalid_url(self):
        """Test that profile form is invalid with malformed URLs."""
        form = ProfileForm(
            data={
                "bio": "",
                "birth_date": "",
                "company": "",
                "location": "",
                "github_url": "not-a-valid-url",
                "homepage_url": "",
                "blog_url": "",
                "twitter_url": "",
                "linkedin_url": "",
            },
            instance=self.profile,
        )
        assert not form.is_valid()
        assert "github_url" in form.errors

    def test_profile_form_widget_classes(self):
        """Test that profile form widgets have correct CSS classes."""
        form = ProfileForm(instance=self.profile)
        assert "form-control" in form.fields["bio"].widget.attrs["class"]
        assert "form-control" in form.fields["company"].widget.attrs["class"]
        assert "form-control" in form.fields["location"].widget.attrs["class"]


class WorkExperienceFormTests(TestCase):
    """Test cases for WorkExperienceForm."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.profile = UserProfile.objects.create(user=self.user)

    def test_work_experience_form_valid_data(self):
        """Test that work experience form is valid with complete data."""
        form = WorkExperienceForm(
            data={
                "company_name": "Test Company",
                "title": "Software Engineer",
                "start_date": "2020-01-01",
                "end_date": "2022-12-31",
                "description": "Test description",
            },
        )
        assert form.is_valid()

    def test_work_experience_form_no_end_date(self):
        """Test that work experience form is valid without end date for current jobs."""
        form = WorkExperienceForm(
            data={
                "company_name": "Current Company",
                "title": "Senior Engineer",
                "start_date": "2023-01-01",
                "end_date": "",
                "description": "",
            },
        )
        assert form.is_valid()

    def test_work_experience_form_saves_data(self):
        """Test that work experience form saves data correctly."""
        form = WorkExperienceForm(
            data={
                "company_name": "Test Company",
                "title": "Engineer",
                "start_date": "2020-01-01",
                "end_date": "",
                "description": "Test",
            },
        )
        assert form.is_valid()
        work = form.save(commit=False)
        work.profile = self.profile
        work.save()
        assert work.company_name == "Test Company"
        assert work.title == "Engineer"

    def test_work_experience_form_invalid_date_range(self):
        """Test that form is invalid when end date is before start date."""
        form = WorkExperienceForm(
            data={
                "company_name": "Test Company",
                "title": "Engineer",
                "start_date": "2022-12-31",
                "end_date": "2020-01-01",
                "description": "",
            },
        )
        assert not form.is_valid()
        assert "开始日期必须早于结束日期" in str(form.errors)

    def test_work_experience_form_same_start_end_date(self):
        """Test that form is invalid when start and end dates are the same."""
        form = WorkExperienceForm(
            data={
                "company_name": "Test Company",
                "title": "Engineer",
                "start_date": "2020-01-01",
                "end_date": "2020-01-01",
                "description": "",
            },
        )
        assert not form.is_valid()
        assert "开始日期必须早于结束日期" in str(form.errors)


class EducationFormTests(TestCase):
    """Test cases for EducationForm."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.profile = UserProfile.objects.create(user=self.user)

    def test_education_form_valid_data(self):
        """Test that education form is valid with complete data."""
        form = EducationForm(
            data={
                "institution_name": "Test University",
                "degree": "本科",
                "field_of_study": "Computer Science",
                "start_date": "2015-09-01",
                "end_date": "2019-06-30",
            },
        )
        assert form.is_valid()

    def test_education_form_no_end_date(self):
        """Test that education form is valid without end date for ongoing education."""
        form = EducationForm(
            data={
                "institution_name": "Current University",
                "degree": "硕士",
                "field_of_study": "AI",
                "start_date": "2023-09-01",
                "end_date": "",
            },
        )
        assert form.is_valid()

    def test_education_form_saves_data(self):
        """Test that education form saves data correctly."""
        form = EducationForm(
            data={
                "institution_name": "Test University",
                "degree": "本科",
                "field_of_study": "CS",
                "start_date": "2015-09-01",
                "end_date": "2019-06-30",
            },
        )
        assert form.is_valid()
        edu = form.save(commit=False)
        edu.profile = self.profile
        edu.save()
        assert edu.institution_name == "Test University"
        assert edu.field_of_study == "CS"

    def test_education_form_invalid_date_range(self):
        """Test that form is invalid when end date is before start date."""
        form = EducationForm(
            data={
                "institution_name": "Test University",
                "degree": "本科",
                "field_of_study": "CS",
                "start_date": "2019-06-30",
                "end_date": "2015-09-01",
            },
        )
        assert not form.is_valid()
        assert "开始日期必须早于结束日期" in str(form.errors)

    def test_education_form_same_start_end_date(self):
        """Test that form is invalid when start and end dates are the same."""
        form = EducationForm(
            data={
                "institution_name": "Test University",
                "degree": "本科",
                "field_of_study": "CS",
                "start_date": "2015-09-01",
                "end_date": "2015-09-01",
            },
        )
        assert not form.is_valid()
        assert "开始日期必须早于结束日期" in str(form.errors)


class CustomPasswordChangeFormTests(TestCase):
    """Test cases for CustomPasswordChangeForm."""

    def test_form_valid_data(self):
        """Test that form is valid with correct data."""
        from accounts.forms import CustomPasswordChangeForm

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
                "new_password2": "newpass123",
            },
        )
        assert form.is_valid()

    def test_form_wrong_old_password(self):
        """Test that form is invalid with wrong old password."""
        from accounts.forms import CustomPasswordChangeForm

        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="oldpass123",
        )
        form = CustomPasswordChangeForm(
            user=user,
            data={
                "old_password": "wrongpass",
                "new_password1": "newpass123",
                "new_password2": "newpass123",
            },
        )
        assert not form.is_valid()


class ChangeEmailFormTests(TestCase):
    """Test cases for ChangeEmailForm."""

    def test_form_valid_data(self):
        """Test that form is valid with correct data."""
        from accounts.forms import ChangeEmailForm

        user = get_user_model().objects.create_user(
            username="testuser",
            email="old@example.com",
            password="testpass123",
        )
        form = ChangeEmailForm(
            user=user,
            data={
                "email": "new@example.com",
                "password": "testpass123",
            },
        )
        assert form.is_valid()

    def test_form_same_email(self):
        """Test that form is invalid with same email."""
        from accounts.forms import ChangeEmailForm

        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        form = ChangeEmailForm(
            user=user,
            data={
                "email": "test@example.com",
                "password": "testpass123",
            },
        )
        assert not form.is_valid()
        assert "email" in form.errors

    def test_form_existing_email(self):
        """Test that form is invalid with email already in use."""
        from accounts.forms import ChangeEmailForm

        get_user_model().objects.create_user(
            username="user1",
            email="existing@example.com",
            password="pass123",
        )
        user2 = get_user_model().objects.create_user(
            username="user2",
            email="user2@example.com",
            password="pass123",
        )
        form = ChangeEmailForm(
            user=user2,
            data={
                "email": "existing@example.com",
                "password": "pass123",
            },
        )
        assert not form.is_valid()
        assert "email" in form.errors

    def test_form_wrong_password(self):
        """Test that form is invalid with wrong password."""
        from accounts.forms import ChangeEmailForm

        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        form = ChangeEmailForm(
            user=user,
            data={
                "email": "new@example.com",
                "password": "wrongpass",
            },
        )
        assert not form.is_valid()
        assert "password" in form.errors


class PasswordResetRequestFormTests(TestCase):
    """Test cases for PasswordResetRequestForm."""

    def test_password_reset_request_form_valid_email(self):
        """Test form with valid email."""
        form = PasswordResetRequestForm(data={"email": "test@example.com"})
        assert form.is_valid()

    def test_password_reset_request_form_invalid_email(self):
        """Test form with invalid email."""
        form = PasswordResetRequestForm(data={"email": "invalid-email"})
        assert not form.is_valid()
        assert "email" in form.errors

    def test_password_reset_request_form_empty_email(self):
        """Test form with empty email."""
        form = PasswordResetRequestForm(data={"email": ""})
        assert not form.is_valid()
        assert "email" in form.errors


class PasswordResetConfirmFormTests(TestCase):
    """Test cases for PasswordResetConfirmForm."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="oldpass123",
        )

    def test_password_reset_confirm_form_valid_data(self):
        """Test form with valid password data."""
        form = PasswordResetConfirmForm(
            user=self.user,
            data={
                "new_password1": "newpass123",
                "new_password2": "newpass123",
            },
        )
        assert form.is_valid()

    def test_password_reset_confirm_form_passwords_dont_match(self):
        """Test form with mismatched passwords."""
        form = PasswordResetConfirmForm(
            user=self.user,
            data={
                "new_password1": "newpass123",
                "new_password2": "differentpass123",
            },
        )
        assert not form.is_valid()
        assert "new_password2" in form.errors

    def test_password_reset_confirm_form_weak_password(self):
        """Test form with weak password."""
        form = PasswordResetConfirmForm(
            user=self.user,
            data={
                "new_password1": "123",
                "new_password2": "123",
            },
        )
        assert not form.is_valid()
