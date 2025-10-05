"""Tests for accounts app."""

from datetime import date

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from social_django.models import UserSocialAuth

from accounts.forms import EducationForm, ProfileForm, SignUpForm, WorkExperienceForm
from accounts.models import Education, UserProfile, WorkExperience


class UserModelTests(TestCase):
    """Test cases for User model."""

    def test_user_defaults_active(self):
        """Test that user is active by default."""
        user = get_user_model().objects.create_user(
            username="active-user",
            email="active@example.com",
            password="password123",
        )

        assert user.is_active


class UserProfileModelTests(TestCase):
    """Test cases for UserProfile model."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )

    def test_user_profile_creation(self):
        """Test creating a user profile with all fields."""
        profile = UserProfile.objects.create(
            user=self.user,
            bio="Test bio",
            birth_date=date(1990, 1, 1),
            github_url="https://github.com/testuser",
            homepage_url="https://example.com",
            blog_url="https://blog.example.com",
            twitter_url="https://twitter.com/testuser",
            linkedin_url="https://linkedin.com/in/testuser",
            company="Test Company",
            location="Test City",
        )

        assert profile.user == self.user
        assert profile.bio == "Test bio"
        assert profile.birth_date == date(1990, 1, 1)
        assert profile.github_url == "https://github.com/testuser"
        assert profile.company == "Test Company"
        assert profile.location == "Test City"

    def test_user_profile_str(self):
        """Test string representation of user profile."""
        profile = UserProfile.objects.create(user=self.user)
        assert str(profile) == "testuser"

    def test_user_profile_optional_fields(self):
        """Test that optional profile fields have default values."""
        profile = UserProfile.objects.create(user=self.user)

        assert profile.bio == ""
        assert profile.birth_date is None
        assert profile.github_url == ""

    def test_user_profile_one_to_one_relationship(self):
        """Test one-to-one relationship between User and UserProfile."""
        profile = UserProfile.objects.create(user=self.user)
        assert self.user.profile == profile


class WorkExperienceModelTests(TestCase):
    """Test cases for WorkExperience model."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        self.profile = UserProfile.objects.create(user=self.user)

    def test_work_experience_creation(self):
        """Test creating a work experience with all fields."""
        work_exp = WorkExperience.objects.create(
            profile=self.profile,
            company_name="Test Company",
            title="Software Engineer",
            start_date=date(2020, 1, 1),
            end_date=date(2022, 12, 31),
            description="Test description",
        )

        assert work_exp.profile == self.profile
        assert work_exp.company_name == "Test Company"
        assert work_exp.title == "Software Engineer"
        assert work_exp.start_date == date(2020, 1, 1)
        assert work_exp.end_date == date(2022, 12, 31)
        assert work_exp.description == "Test description"

    def test_work_experience_current_job(self):
        """Test work experience without end date for current jobs."""
        work_exp = WorkExperience.objects.create(
            profile=self.profile,
            company_name="Current Company",
            title="Senior Engineer",
            start_date=date(2023, 1, 1),
        )

        assert work_exp.end_date is None

    def test_work_experience_ordering(self):
        """Test that work experiences are ordered by start date descending."""
        work_exp1 = WorkExperience.objects.create(
            profile=self.profile,
            company_name="Old Company",
            title="Junior Engineer",
            start_date=date(2018, 1, 1),
            end_date=date(2020, 1, 1),
        )
        work_exp2 = WorkExperience.objects.create(
            profile=self.profile,
            company_name="New Company",
            title="Senior Engineer",
            start_date=date(2023, 1, 1),
        )

        work_experiences = self.profile.work_experiences.all()
        assert work_experiences[0] == work_exp2
        assert work_experiences[1] == work_exp1


class EducationModelTests(TestCase):
    """Test cases for Education model."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        self.profile = UserProfile.objects.create(user=self.user)

    def test_education_creation(self):
        """Test creating an education record with all fields."""
        education = Education.objects.create(
            profile=self.profile,
            institution_name="Test University",
            degree="本科",
            field_of_study="Computer Science",
            start_date=date(2015, 9, 1),
            end_date=date(2019, 6, 30),
        )

        assert education.profile == self.profile
        assert education.institution_name == "Test University"
        assert education.degree == "本科"
        assert education.field_of_study == "Computer Science"
        assert education.start_date == date(2015, 9, 1)
        assert education.end_date == date(2019, 6, 30)

    def test_education_ongoing(self):
        """Test education record without end date for ongoing education."""
        education = Education.objects.create(
            profile=self.profile,
            institution_name="Current University",
            degree="硕士",
            field_of_study="Artificial Intelligence",
            start_date=date(2023, 9, 1),
        )

        assert education.end_date is None

    def test_education_ordering(self):
        """Test that education records are ordered by start date descending."""
        edu1 = Education.objects.create(
            profile=self.profile,
            institution_name="Old School",
            field_of_study="Math",
            start_date=date(2010, 9, 1),
            end_date=date(2015, 6, 30),
        )
        edu2 = Education.objects.create(
            profile=self.profile,
            institution_name="New School",
            field_of_study="CS",
            start_date=date(2020, 9, 1),
        )

        educations = self.profile.educations.all()
        assert educations[0] == edu2
        assert educations[1] == edu1


class UserAdminRegistrationTests(TestCase):
    """Test cases for User model admin registration."""

    databases = {"default"}

    def test_user_registered_with_admin_site(self):
        """Test that User model is registered with Django admin."""
        from accounts import admin as accounts_admin

        user_model = get_user_model()

        assert user_model in admin.site._registry
        assert isinstance(admin.site._registry[user_model], accounts_admin.UserAdmin)


class AccountsIndexViewTests(TestCase):
    """Test cases for accounts index view."""

    def test_accounts_index_redirects_to_signin_when_not_authenticated(self):
        """Test that unauthenticated users are redirected to sign in page."""
        response = self.client.get(reverse("accounts:index"))
        self.assertRedirects(response, reverse("accounts:sign_in"))

    def test_accounts_index_redirects_to_profile_when_authenticated(self):
        """Test that authenticated users are redirected to profile page."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:index"))
        self.assertRedirects(response, reverse("accounts:profile"))


class SignInViewTests(TestCase):
    """Test cases for sign in view."""

    def test_sign_in_view_status_code(self):
        """Test that sign in page returns 200 status code."""
        response = self.client.get(reverse("accounts:sign_in"))
        assert response.status_code == 200

    def test_sign_in_view_template(self):
        """Test that sign in view uses correct template."""
        response = self.client.get(reverse("accounts:sign_in"))
        self.assertTemplateUsed(response, "sign_in.html")

    def test_sign_in_view_contains_email_form(self):
        """Test that sign in form contains email and password fields."""
        response = self.client.get(reverse("accounts:sign_in"))
        self.assertContains(response, "email")
        self.assertContains(response, "password")

    def test_sign_in_view_contains_username_form(self):
        """Test that sign in form contains username field."""
        response = self.client.get(reverse("accounts:sign_in"))
        self.assertContains(response, "username")

    def test_sign_in_view_contains_signup_link(self):
        """Test that sign in page contains link to sign up page."""
        response = self.client.get(reverse("accounts:sign_in"))
        self.assertContains(response, reverse("accounts:sign_up"))


class SignUpViewTests(TestCase):
    """Test cases for sign up view."""

    def test_sign_up_view_get_status_code(self):
        """Test that sign up page returns 200 status code."""
        response = self.client.get(reverse("accounts:sign_up"))
        assert response.status_code == 200

    def test_sign_up_view_template(self):
        """Test that sign up view uses correct template."""
        response = self.client.get(reverse("accounts:sign_up"))
        self.assertTemplateUsed(response, "sign_up.html")

    def test_sign_up_view_contains_form_fields(self):
        """Test that sign up form contains all required fields."""
        response = self.client.get(reverse("accounts:sign_up"))
        self.assertContains(response, "username")
        self.assertContains(response, "email")
        self.assertContains(response, "password1")
        self.assertContains(response, "password2")

    def test_sign_up_view_post_valid_data(self):
        """Test that posting valid data creates a new user."""
        data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password1": "testpass123",
            "password2": "testpass123",
        }
        response = self.client.post(reverse("accounts:sign_up"), data)
        assert response.status_code == 302
        assert get_user_model().objects.filter(username="newuser").exists()

    def test_sign_up_view_post_invalid_password_mismatch(self):
        """Test that password mismatch prevents user creation."""
        data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password1": "testpass123",
            "password2": "wrongpass123",
        }
        response = self.client.post(reverse("accounts:sign_up"), data)
        assert response.status_code == 200
        assert not get_user_model().objects.filter(username="newuser").exists()

    def test_sign_up_view_contains_signin_link(self):
        """Test that sign up page contains link to sign in page."""
        response = self.client.get(reverse("accounts:sign_up"))
        self.assertContains(response, reverse("accounts:sign_in"))


class ProfileViewTests(TestCase):
    """Test cases for profile view."""

    def test_profile_view_requires_login(self):
        """Test that profile view requires user authentication."""
        response = self.client.get(reverse("accounts:profile"))
        assert response.status_code == 302
        assert response.url.startswith("/accounts/login/")

    def test_profile_view_authenticated_user(self):
        """Test that authenticated users can access profile page."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile"))
        assert response.status_code == 200
        self.assertTemplateUsed(response, "profile.html")

    def test_profile_view_displays_user_info(self):
        """Test that profile view displays user information."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "testuser")
        self.assertContains(response, "test@example.com")

    def test_profile_view_creates_profile_if_not_exists(self):
        """Test that profile view creates UserProfile if it doesn't exist."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        assert not UserProfile.objects.filter(user=user).exists()
        response = self.client.get(reverse("accounts:profile"))
        assert response.status_code == 200
        assert UserProfile.objects.filter(user=user).exists()

    def test_profile_view_displays_profile_data(self):
        """Test that profile view displays user profile data."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        UserProfile.objects.create(
            user=user,
            bio="Test bio",
            company="Test Company",
            location="Test City",
            github_url="https://github.com/testuser",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "Test bio")
        self.assertContains(response, "Test Company")
        self.assertContains(response, "Test City")
        self.assertContains(response, "https://github.com/testuser")

    def test_profile_view_displays_work_experience(self):
        """Test that profile view displays work experience data."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        profile = UserProfile.objects.create(user=user)
        WorkExperience.objects.create(
            profile=profile,
            company_name="Test Company",
            title="Software Engineer",
            start_date=date(2020, 1, 1),
            end_date=date(2022, 12, 31),
            description="Test work description",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "工作经历")
        self.assertContains(response, "Test Company")
        self.assertContains(response, "Software Engineer")
        self.assertContains(response, "Test work description")

    def test_profile_view_displays_education(self):
        """Test that profile view displays education data."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        profile = UserProfile.objects.create(user=user)
        Education.objects.create(
            profile=profile,
            institution_name="Test University",
            degree="本科",
            field_of_study="Computer Science",
            start_date=date(2015, 9, 1),
            end_date=date(2019, 6, 30),
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "学习经历")
        self.assertContains(response, "Test University")
        self.assertContains(response, "本科")
        self.assertContains(response, "Computer Science")

    def test_profile_view_current_work_and_education(self):
        """Test that profile view displays current work and education with '至今'."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        profile = UserProfile.objects.create(user=user)
        WorkExperience.objects.create(
            profile=profile,
            company_name="Current Company",
            title="Senior Engineer",
            start_date=date(2023, 1, 1),
        )
        Education.objects.create(
            profile=profile,
            institution_name="Current University",
            degree="硕士",
            field_of_study="AI",
            start_date=date(2023, 9, 1),
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "至今")


class LogoutViewTests(TestCase):
    """Test cases for logout view."""

    def test_logout_view_requires_login(self):
        """Test that logout view requires user authentication."""
        response = self.client.get(reverse("accounts:logout"))
        assert response.status_code == 302
        assert response.url.startswith("/accounts/login/")

    def test_logout_view_logs_out_user(self):
        """Test that logout view successfully logs out the user."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        assert self.client.session.get("_auth_user_id")

        response = self.client.get(reverse("accounts:logout"))

        self.assertRedirects(response, reverse("homepage:index"))
        assert not self.client.session.get("_auth_user_id")

    def test_logout_view_displays_success_message(self):
        """Test that logout view displays success message."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:logout"), follow=True)
        messages = list(response.context["messages"])
        assert len(messages) == 1
        assert str(messages[0]) == "您已成功退出登录"


class ProfileEditViewTests(TestCase):
    """Test cases for profile edit view."""

    def test_profile_edit_view_requires_login(self):
        """Test that profile edit view requires user authentication."""
        response = self.client.get(reverse("accounts:profile_edit"))
        assert response.status_code == 302
        assert response.url.startswith("/accounts/login/")

    def test_profile_edit_view_get_authenticated(self):
        """Test that authenticated users can access profile edit page."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile_edit"))
        assert response.status_code == 200
        self.assertTemplateUsed(response, "profile_edit.html")

    def test_profile_edit_view_creates_profile_if_not_exists(self):
        """Test that profile edit view creates UserProfile if it doesn't exist."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        assert not UserProfile.objects.filter(user=user).exists()
        response = self.client.get(reverse("accounts:profile_edit"))
        assert response.status_code == 200
        assert UserProfile.objects.filter(user=user).exists()

    def test_profile_edit_view_post_valid_data(self):
        """Test that posting valid data updates user profile."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        data = {
            "bio": "Updated bio",
            "birth_date": "1990-01-01",
            "company": "New Company",
            "location": "New City",
            "github_url": "https://github.com/newuser",
            "homepage_url": "",
            "blog_url": "",
            "twitter_url": "",
            "linkedin_url": "",
            "work_experiences-TOTAL_FORMS": "1",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            "educations-TOTAL_FORMS": "1",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
        }
        response = self.client.post(reverse("accounts:profile_edit"), data)
        self.assertRedirects(response, reverse("accounts:profile"))
        profile = UserProfile.objects.get(user=user)
        assert profile.bio == "Updated bio"
        assert profile.company == "New Company"
        assert profile.location == "New City"

    def test_profile_edit_view_post_no_changes(self):
        """Test that posting data with no changes displays appropriate message."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        UserProfile.objects.create(
            user=user,
            bio="Original bio",
            company="Original Company",
        )
        self.client.force_login(user)
        data = {
            "bio": "Original bio",
            "birth_date": "",
            "company": "Original Company",
            "location": "",
            "github_url": "",
            "homepage_url": "",
            "blog_url": "",
            "twitter_url": "",
            "linkedin_url": "",
            "work_experiences-TOTAL_FORMS": "1",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            "educations-TOTAL_FORMS": "1",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
        }
        response = self.client.post(reverse("accounts:profile_edit"), data, follow=True)
        messages = list(response.context["messages"])
        assert len(messages) == 1
        assert str(messages[0]) == "未检测到任何更改"

    def test_profile_edit_view_post_with_changes(self):
        """Test that posting data with changes updates profile and shows success message."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        profile = UserProfile.objects.create(
            user=user,
            bio="Original bio",
            company="Original Company",
        )
        self.client.force_login(user)
        data = {
            "bio": "Updated bio",
            "birth_date": "",
            "company": "Original Company",
            "location": "",
            "github_url": "",
            "homepage_url": "",
            "blog_url": "",
            "twitter_url": "",
            "linkedin_url": "",
            "work_experiences-TOTAL_FORMS": "1",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            "educations-TOTAL_FORMS": "1",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
        }
        response = self.client.post(reverse("accounts:profile_edit"), data, follow=True)
        messages = list(response.context["messages"])
        assert len(messages) == 1
        assert str(messages[0]) == "个人资料已更新"
        profile.refresh_from_db()
        assert profile.bio == "Updated bio"

    def test_profile_edit_view_displays_form(self):
        """Test that profile edit view displays the form correctly."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile_edit"))
        self.assertContains(response, "个人简介")
        self.assertContains(response, "保存更改")

    def test_profile_edit_view_add_work_experience(self):
        """Test that adding work experience through profile edit works correctly."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        data = {
            "bio": "",
            "birth_date": "",
            "company": "",
            "location": "",
            "github_url": "",
            "homepage_url": "",
            "blog_url": "",
            "twitter_url": "",
            "linkedin_url": "",
            "work_experiences-TOTAL_FORMS": "1",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            "work_experiences-0-company_name": "Test Company",
            "work_experiences-0-title": "Software Engineer",
            "work_experiences-0-start_date": "2020-01-01",
            "work_experiences-0-end_date": "2022-12-31",
            "work_experiences-0-description": "Test description",
            "educations-TOTAL_FORMS": "1",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
        }
        self.client.post(reverse("accounts:profile_edit"), data, follow=True)
        assert WorkExperience.objects.count() == 1
        work = WorkExperience.objects.first()
        assert work.company_name == "Test Company"
        assert work.title == "Software Engineer"

    def test_profile_edit_view_add_education(self):
        """Test that adding education through profile edit works correctly."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        data = {
            "bio": "",
            "birth_date": "",
            "company": "",
            "location": "",
            "github_url": "",
            "homepage_url": "",
            "blog_url": "",
            "twitter_url": "",
            "linkedin_url": "",
            "work_experiences-TOTAL_FORMS": "1",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            "educations-TOTAL_FORMS": "1",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
            "educations-0-institution_name": "Test University",
            "educations-0-degree": "本科",
            "educations-0-field_of_study": "Computer Science",
            "educations-0-start_date": "2015-09-01",
            "educations-0-end_date": "2019-06-30",
        }
        self.client.post(reverse("accounts:profile_edit"), data, follow=True)
        assert Education.objects.count() == 1
        edu = Education.objects.first()
        assert edu.institution_name == "Test University"
        assert edu.field_of_study == "Computer Science"

    def test_profile_edit_view_delete_work_experience(self):
        """Test that deleting work experience through profile edit works correctly."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        profile = UserProfile.objects.create(user=user)
        work = WorkExperience.objects.create(
            profile=profile,
            company_name="Old Company",
            title="Old Title",
            start_date=date(2020, 1, 1),
        )
        self.client.force_login(user)
        data = {
            "bio": "",
            "birth_date": "",
            "company": "",
            "location": "",
            "github_url": "",
            "homepage_url": "",
            "blog_url": "",
            "twitter_url": "",
            "linkedin_url": "",
            "work_experiences-TOTAL_FORMS": "2",
            "work_experiences-INITIAL_FORMS": "1",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            "work_experiences-0-id": str(work.id),
            "work_experiences-0-profile": str(profile.user_id),
            "work_experiences-0-company_name": "Old Company",
            "work_experiences-0-title": "Old Title",
            "work_experiences-0-start_date": "2020-01-01",
            "work_experiences-0-end_date": "",
            "work_experiences-0-description": "",
            "work_experiences-0-DELETE": "on",
            "educations-TOTAL_FORMS": "1",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
        }
        self.client.post(reverse("accounts:profile_edit"), data, follow=True)
        assert WorkExperience.objects.count() == 0

    def test_profile_edit_view_delete_education(self):
        """Test that deleting education through profile edit works correctly."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        profile = UserProfile.objects.create(user=user)
        edu = Education.objects.create(
            profile=profile,
            institution_name="Old University",
            field_of_study="Old Field",
            start_date=date(2015, 9, 1),
        )
        self.client.force_login(user)
        data = {
            "bio": "",
            "birth_date": "",
            "company": "",
            "location": "",
            "github_url": "",
            "homepage_url": "",
            "blog_url": "",
            "twitter_url": "",
            "linkedin_url": "",
            "work_experiences-TOTAL_FORMS": "1",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            "educations-TOTAL_FORMS": "2",
            "educations-INITIAL_FORMS": "1",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
            "educations-0-id": str(edu.id),
            "educations-0-profile": str(profile.user_id),
            "educations-0-institution_name": "Old University",
            "educations-0-field_of_study": "Old Field",
            "educations-0-start_date": "2015-09-01",
            "educations-0-end_date": "",
            "educations-0-degree": "",
            "educations-0-DELETE": "on",
        }
        self.client.post(reverse("accounts:profile_edit"), data, follow=True)
        assert Education.objects.count() == 0

    def test_profile_edit_view_displays_date_validation_error(self):
        """Test that invalid date ranges display validation errors."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        data = {
            "bio": "",
            "birth_date": "",
            "company": "",
            "location": "",
            "github_url": "",
            "homepage_url": "",
            "blog_url": "",
            "twitter_url": "",
            "linkedin_url": "",
            "work_experiences-TOTAL_FORMS": "1",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            "work_experiences-0-company_name": "Test Company",
            "work_experiences-0-title": "Engineer",
            "work_experiences-0-start_date": "2022-01-01",
            "work_experiences-0-end_date": "2020-01-01",
            "work_experiences-0-description": "",
            "educations-TOTAL_FORMS": "1",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
        }
        response = self.client.post(reverse("accounts:profile_edit"), data)
        assert response.status_code == 200
        self.assertContains(response, "开始日期必须早于结束日期")

    def test_profile_edit_view_displays_existing_experiences(self):
        """Test that profile edit view displays existing work and education data."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        profile = UserProfile.objects.create(user=user)
        WorkExperience.objects.create(
            profile=profile,
            company_name="Test Company",
            title="Engineer",
            start_date=date(2020, 1, 1),
        )
        Education.objects.create(
            profile=profile,
            institution_name="Test University",
            field_of_study="CS",
            start_date=date(2015, 9, 1),
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile_edit"))
        self.assertContains(response, "Test Company")
        self.assertContains(response, "Engineer")
        self.assertContains(response, "Test University")
        self.assertContains(response, "CS")


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


class SocialConnectionsViewTests(TestCase):
    """Test cases for social connections view."""

    def test_social_connections_view_requires_login(self):
        """Test that social connections view requires user authentication."""
        response = self.client.get(reverse("accounts:social_connections"))
        assert response.status_code == 302
        assert response.url.startswith("/accounts/login/")

    def test_social_connections_view_authenticated(self):
        """Test that authenticated users can access social connections page."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:social_connections"))
        assert response.status_code == 200
        self.assertTemplateUsed(response, "social_connections.html")

    def test_social_connections_view_displays_configured_providers(self):
        """Test that social connections view only displays configured providers."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)

        # 设置 GitHub 配置（默认在测试环境已配置）
        with self.settings(
            SOCIAL_AUTH_GITHUB_KEY="test_key",
            SOCIAL_AUTH_GITHUB_SECRET="test_secret",
        ):
            response = self.client.get(reverse("accounts:social_connections"))
            self.assertContains(response, "GitHub")

    def test_social_connections_view_hides_unconfigured_providers(self):
        """Test that unconfigured providers are not displayed."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)

        # 清空所有社交认证配置
        with self.settings(
            SOCIAL_AUTH_GITHUB_KEY="",
            SOCIAL_AUTH_GITHUB_SECRET="",
            SOCIAL_AUTH_GOOGLE_OAUTH2_KEY="",
            SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET="",
            SOCIAL_AUTH_FACEBOOK_KEY="",
            SOCIAL_AUTH_FACEBOOK_SECRET="",
            SOCIAL_AUTH_TWITTER_OAUTH2_KEY="",
            SOCIAL_AUTH_TWITTER_OAUTH2_SECRET="",
            SOCIAL_AUTH_LINKEDIN_OAUTH2_KEY="",
            SOCIAL_AUTH_LINKEDIN_OAUTH2_SECRET="",
            SOCIAL_AUTH_BITBUCKET_OAUTH2_KEY="",
            SOCIAL_AUTH_BITBUCKET_OAUTH2_SECRET="",
            SOCIAL_AUTH_DOCKER_KEY="",
            SOCIAL_AUTH_DOCKER_SECRET="",
            SOCIAL_AUTH_GITLAB_KEY="",
            SOCIAL_AUTH_GITLAB_SECRET="",
            SOCIAL_AUTH_GITEA_KEY="",
            SOCIAL_AUTH_GITEA_SECRET="",
        ):
            response = self.client.get(reverse("accounts:social_connections"))
            # 不应该显示任何社交平台
            self.assertNotContains(response, "GitHub")
            self.assertNotContains(response, "Google")
            self.assertNotContains(response, "Facebook")

    def test_social_connections_view_shows_connected_accounts(self):
        """Test that connected social accounts are displayed correctly."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        UserSocialAuth.objects.create(
            user=user,
            provider="github",
            uid="github123",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:social_connections"))
        self.assertContains(response, "已绑定")
        self.assertContains(response, "github123")

    def test_social_connections_view_shows_unconnected_accounts(self):
        """Test that unconnected social accounts are displayed correctly."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:social_connections"))
        self.assertContains(response, "未绑定")
        self.assertContains(response, "绑定")

    def test_social_connections_view_hides_disconnect_for_only_auth_method(self):
        """Test that disconnect button is hidden when user has only one auth method."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
        )
        user.set_unusable_password()
        user.save()
        UserSocialAuth.objects.create(
            user=user,
            provider="github",
            uid="github123",
        )
        self.client.force_login(user)

        with self.settings(
            SOCIAL_AUTH_GITHUB_KEY="test_key",
            SOCIAL_AUTH_GITHUB_SECRET="test_secret",
        ):
            response = self.client.get(reverse("accounts:social_connections"))
            # 应该显示"无法解绑"而不是"解绑"
            self.assertContains(response, "无法解绑")
            self.assertNotContains(response, "解绑</button>")

    def test_social_connections_view_shows_disconnect_with_password(self):
        """Test that disconnect button is shown when user has password."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        UserSocialAuth.objects.create(
            user=user,
            provider="github",
            uid="github123",
        )
        self.client.force_login(user)

        with self.settings(
            SOCIAL_AUTH_GITHUB_KEY="test_key",
            SOCIAL_AUTH_GITHUB_SECRET="test_secret",
        ):
            response = self.client.get(reverse("accounts:social_connections"))
            # 有密码，应该可以解绑
            self.assertContains(response, "btn-outline-danger")
            self.assertContains(response, "解绑")
            self.assertNotContains(response, "无法解绑")

    def test_social_connections_view_shows_disconnect_with_multiple_social(self):
        """Test that disconnect button is shown when user has multiple social accounts."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
        )
        user.set_unusable_password()
        user.save()
        UserSocialAuth.objects.create(
            user=user,
            provider="github",
            uid="github123",
        )
        UserSocialAuth.objects.create(
            user=user,
            provider="google-oauth2",
            uid="google123",
        )
        self.client.force_login(user)

        with self.settings(
            SOCIAL_AUTH_GITHUB_KEY="test_key",
            SOCIAL_AUTH_GITHUB_SECRET="test_secret",
            SOCIAL_AUTH_GOOGLE_OAUTH2_KEY="test_key",
            SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET="test_secret",
        ):
            response = self.client.get(reverse("accounts:social_connections"))
            # 有多个社交账号，应该可以解绑
            self.assertContains(response, "btn-outline-danger")
            self.assertContains(response, "解绑")
            self.assertNotContains(response, "无法解绑")


class DisconnectSocialAccountViewTests(TestCase):
    """Test cases for disconnect social account view."""

    def test_disconnect_social_account_requires_login(self):
        """Test that disconnect view requires user authentication."""
        response = self.client.post(
            reverse("accounts:disconnect_social", args=["github", 1]),
        )
        assert response.status_code == 302
        assert response.url.startswith("/accounts/login/")

    def test_disconnect_social_account_success(self):
        """Test that disconnecting social account works correctly."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        user.set_password("testpass123")
        user.save()
        social_auth = UserSocialAuth.objects.create(
            user=user,
            provider="github",
            uid="github123",
        )
        self.client.force_login(user)
        response = self.client.post(
            reverse(
                "accounts:disconnect_social",
                args=["github", social_auth.id],
            ),
        )
        self.assertRedirects(response, reverse("accounts:social_connections"))
        assert not UserSocialAuth.objects.filter(id=social_auth.id).exists()

    def test_disconnect_social_account_with_password(self):
        """Test that user can disconnect social account if they have a password."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        social_auth = UserSocialAuth.objects.create(
            user=user,
            provider="github",
            uid="github123",
        )
        self.client.force_login(user)
        response = self.client.post(
            reverse(
                "accounts:disconnect_social",
                args=["github", social_auth.id],
            ),
            follow=True,
        )
        messages = list(response.context["messages"])
        assert len(messages) == 1
        assert "已成功解绑" in str(messages[0])

    def test_disconnect_social_account_prevents_last_auth_method(self):
        """Test that user cannot disconnect their only authentication method."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
        )
        user.set_unusable_password()
        user.save()
        social_auth = UserSocialAuth.objects.create(
            user=user,
            provider="github",
            uid="github123",
        )
        self.client.force_login(user)
        response = self.client.post(
            reverse(
                "accounts:disconnect_social",
                args=["github", social_auth.id],
            ),
            follow=True,
        )
        messages = list(response.context["messages"])
        assert len(messages) == 1
        assert "无法解绑该账号" in str(messages[0])
        assert UserSocialAuth.objects.filter(id=social_auth.id).exists()

    def test_disconnect_social_account_with_other_social_accounts(self):
        """Test that user can disconnect social account if they have other social accounts."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
        )
        user.set_unusable_password()
        user.save()
        github_auth = UserSocialAuth.objects.create(
            user=user,
            provider="github",
            uid="github123",
        )
        UserSocialAuth.objects.create(
            user=user,
            provider="google-oauth2",
            uid="google123",
        )
        self.client.force_login(user)
        response = self.client.post(
            reverse(
                "accounts:disconnect_social",
                args=["github", github_auth.id],
            ),
            follow=True,
        )
        messages = list(response.context["messages"])
        assert len(messages) == 1
        assert "已成功解绑" in str(messages[0])
        assert not UserSocialAuth.objects.filter(id=github_auth.id).exists()

    def test_disconnect_social_account_not_found(self):
        """Test that disconnecting non-existent social account shows error."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        response = self.client.post(
            reverse("accounts:disconnect_social", args=["github", 99999]),
            follow=True,
        )
        messages = list(response.context["messages"])
        assert len(messages) == 1
        assert "未找到该社交账号绑定" in str(messages[0])

    def test_disconnect_social_account_wrong_user(self):
        """Test that user cannot disconnect another user's social account."""
        user1 = get_user_model().objects.create_user(
            username="testuser1",
            email="test1@example.com",
            password="testpass123",
        )
        user2 = get_user_model().objects.create_user(
            username="testuser2",
            email="test2@example.com",
            password="testpass123",
        )
        social_auth = UserSocialAuth.objects.create(
            user=user2,
            provider="github",
            uid="github123",
        )
        self.client.force_login(user1)
        response = self.client.post(
            reverse(
                "accounts:disconnect_social",
                args=["github", social_auth.id],
            ),
            follow=True,
        )
        messages = list(response.context["messages"])
        assert len(messages) == 1
        assert "未找到该社交账号绑定" in str(messages[0])
        assert UserSocialAuth.objects.filter(id=social_auth.id).exists()
