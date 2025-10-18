"""Tests for accounts views."""

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from social_django.models import UserSocialAuth

from accounts.models import Education, UserProfile, WorkExperience
from common.test_utils import CacheClearTestCase


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

    def test_profile_view_displays_points_info(self):
        """Test that profile view displays user points information."""
        from points.services import grant_points

        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )

        # Grant some points to the user
        grant_points(
            user_profile=user, points=100, description="Test", tag_names=["tag1"]
        )
        grant_points(
            user_profile=user, points=50, description="Test", tag_names=["tag2"]
        )

        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile"))

        # Check that points section is displayed
        self.assertContains(response, "我的积分")
        self.assertContains(response, "当前积分余额")
        self.assertContains(response, "150")  # Total points
        self.assertContains(response, "查看详情")
        self.assertContains(response, reverse("points:my_points"))

    def test_profile_view_displays_points_by_tag(self):
        """Test that profile view displays points grouped by tags."""
        from points.services import grant_points

        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )

        # Grant points with different tags
        grant_points(
            user_profile=user, points=100, description="Test", tag_names=["reward"]
        )
        grant_points(
            user_profile=user, points=50, description="Test", tag_names=["bonus"]
        )

        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile"))

        # Check that tag breakdown is displayed
        self.assertContains(response, "我的积分")
        self.assertContains(response, "reward")
        self.assertContains(response, "bonus")

    def test_profile_view_with_no_points(self):
        """Test that profile view displays zero points when user has no points."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )

        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile"))

        # Check that points section is displayed with zero
        self.assertContains(response, "我的积分")
        self.assertContains(response, "0")  # Zero points


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
            "work_experiences-TOTAL_FORMS": "0",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            "educations-TOTAL_FORMS": "0",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
            "shipping_addresses-TOTAL_FORMS": "0",
            "shipping_addresses-INITIAL_FORMS": "0",
            "shipping_addresses-MIN_NUM_FORMS": "0",
            "shipping_addresses-MAX_NUM_FORMS": "1000",
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
            "work_experiences-TOTAL_FORMS": "0",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            "educations-TOTAL_FORMS": "0",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
            "shipping_addresses-TOTAL_FORMS": "0",
            "shipping_addresses-INITIAL_FORMS": "0",
            "shipping_addresses-MIN_NUM_FORMS": "0",
            "shipping_addresses-MAX_NUM_FORMS": "1000",
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
            "work_experiences-TOTAL_FORMS": "0",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            "educations-TOTAL_FORMS": "0",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
            "shipping_addresses-TOTAL_FORMS": "0",
            "shipping_addresses-INITIAL_FORMS": "0",
            "shipping_addresses-MIN_NUM_FORMS": "0",
            "shipping_addresses-MAX_NUM_FORMS": "1000",
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
            "educations-TOTAL_FORMS": "0",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
            "shipping_addresses-TOTAL_FORMS": "0",
            "shipping_addresses-INITIAL_FORMS": "0",
            "shipping_addresses-MIN_NUM_FORMS": "0",
            "shipping_addresses-MAX_NUM_FORMS": "1000",
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
            "work_experiences-TOTAL_FORMS": "0",
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
            "shipping_addresses-TOTAL_FORMS": "0",
            "shipping_addresses-INITIAL_FORMS": "0",
            "shipping_addresses-MIN_NUM_FORMS": "0",
            "shipping_addresses-MAX_NUM_FORMS": "1000",
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
            "shipping_addresses-TOTAL_FORMS": "0",
            "shipping_addresses-INITIAL_FORMS": "0",
            "shipping_addresses-MIN_NUM_FORMS": "0",
            "shipping_addresses-MAX_NUM_FORMS": "1000",
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
            "shipping_addresses-TOTAL_FORMS": "0",
            "shipping_addresses-INITIAL_FORMS": "0",
            "shipping_addresses-MIN_NUM_FORMS": "0",
            "shipping_addresses-MAX_NUM_FORMS": "1000",
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
            "shipping_addresses-TOTAL_FORMS": "0",
            "shipping_addresses-INITIAL_FORMS": "0",
            "shipping_addresses-MIN_NUM_FORMS": "0",
            "shipping_addresses-MAX_NUM_FORMS": "1000",
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


class ChangePasswordViewTests(TestCase):
    """Test cases for change password view."""

    def test_change_password_view_requires_login(self):
        """Test that change password view requires user authentication."""
        response = self.client.get(reverse("accounts:change_password"))
        assert response.status_code == 302
        assert response.url.startswith("/accounts/login/")

    def test_change_password_view_get_authenticated(self):
        """Test that authenticated users can access change password page."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:change_password"))
        assert response.status_code == 200
        self.assertTemplateUsed(response, "change_password.html")

    def test_change_password_view_post_valid_data(self):
        """Test that posting valid data changes user password."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="oldpass123",
        )
        self.client.force_login(user)
        data = {
            "old_password": "oldpass123",
            "new_password1": "newpass123",
            "new_password2": "newpass123",
        }
        response = self.client.post(reverse("accounts:change_password"), data)
        self.assertRedirects(response, reverse("accounts:profile"))

        # Verify password was changed
        user.refresh_from_db()
        assert user.check_password("newpass123")

    def test_change_password_view_post_wrong_old_password(self):
        """Test that wrong old password prevents password change."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="oldpass123",
        )
        self.client.force_login(user)
        data = {
            "old_password": "wrongpass",
            "new_password1": "newpass123",
            "new_password2": "newpass123",
        }
        response = self.client.post(reverse("accounts:change_password"), data)
        assert response.status_code == 200
        # Password should not be changed
        user.refresh_from_db()
        assert user.check_password("oldpass123")

    def test_change_password_view_post_password_mismatch(self):
        """Test that password mismatch prevents password change."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="oldpass123",
        )
        self.client.force_login(user)
        data = {
            "old_password": "oldpass123",
            "new_password1": "newpass123",
            "new_password2": "differentpass",
        }
        response = self.client.post(reverse("accounts:change_password"), data)
        assert response.status_code == 200
        # Password should not be changed
        user.refresh_from_db()
        assert user.check_password("oldpass123")


class ChangeEmailViewTests(TestCase):
    """Test cases for change email view."""

    def test_change_email_view_requires_login(self):
        """Test that change email view requires user authentication."""
        response = self.client.get(reverse("accounts:change_email"))
        assert response.status_code == 302
        assert response.url.startswith("/accounts/login/")

    def test_change_email_view_get_authenticated(self):
        """Test that authenticated users can access change email page."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="old@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:change_email"))
        assert response.status_code == 200
        self.assertTemplateUsed(response, "change_email.html")
        self.assertContains(response, "old@example.com")

    def test_change_email_view_post_valid_data(self):
        """Test that posting valid data changes user email."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="old@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        data = {
            "email": "new@example.com",
            "password": "testpass123",
        }
        response = self.client.post(reverse("accounts:change_email"), data)
        self.assertRedirects(response, reverse("accounts:profile"))

        # Verify email was changed
        user.refresh_from_db()
        assert user.email == "new@example.com"

    def test_change_email_view_post_wrong_password(self):
        """Test that wrong password prevents email change."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="old@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        data = {
            "email": "new@example.com",
            "password": "wrongpass",
        }
        response = self.client.post(reverse("accounts:change_email"), data)
        assert response.status_code == 200
        # Email should not be changed
        user.refresh_from_db()
        assert user.email == "old@example.com"

    def test_change_email_view_post_same_email(self):
        """Test that same email is rejected."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        data = {
            "email": "test@example.com",
            "password": "testpass123",
        }
        response = self.client.post(reverse("accounts:change_email"), data)
        assert response.status_code == 200
        self.assertContains(response, "新邮箱不能与当前邮箱相同")

    def test_change_email_view_post_existing_email(self):
        """Test that email already in use is rejected."""
        # Create first user
        get_user_model().objects.create_user(
            username="user1",
            email="existing@example.com",
            password="pass123",
        )
        # Create second user
        user2 = get_user_model().objects.create_user(
            username="user2",
            email="user2@example.com",
            password="pass123",
        )
        self.client.force_login(user2)
        data = {
            "email": "existing@example.com",
            "password": "pass123",
        }
        response = self.client.post(reverse("accounts:change_email"), data)
        assert response.status_code == 200
        self.assertContains(response, "该邮箱已被其他用户使用")


class PasswordResetRequestViewTests(TestCase):
    """Test cases for password reset request view."""

    def test_password_reset_request_view_get_status_code(self):
        """Test that password reset request page returns 200 status code."""
        response = self.client.get(reverse("accounts:password_reset_request"))
        assert response.status_code == 200

    def test_password_reset_request_view_template(self):
        """Test that password reset request view uses correct template."""
        response = self.client.get(reverse("accounts:password_reset_request"))
        self.assertTemplateUsed(response, "password_reset_request.html")

    def test_password_reset_request_view_contains_form(self):
        """Test that password reset request form contains email field."""
        response = self.client.get(reverse("accounts:password_reset_request"))
        self.assertContains(response, "email")

    @patch("accounts.views.send_password_reset_email")
    def test_password_reset_request_with_valid_email(self, mock_task):
        """Test password reset request with valid email sends task."""
        get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )

        response = self.client.post(
            reverse("accounts:password_reset_request"),
            {"email": "test@example.com"},
        )

        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        mock_task.enqueue.assert_called_once()

    @patch("accounts.views.send_password_reset_email")
    def test_password_reset_request_with_nonexistent_email(self, mock_task):
        """Test password reset request with non-existent email."""
        response = self.client.post(
            reverse("accounts:password_reset_request"),
            {"email": "nonexistent@example.com"},
        )

        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        mock_task.enqueue.assert_not_called()

    @patch("accounts.views.send_password_reset_email")
    def test_password_reset_request_user_without_password(self, mock_task):
        """Test password reset for user without usable password."""
        user = get_user_model().objects.create_user(
            username="socialuser",
            email="social@example.com",
        )
        user.set_unusable_password()
        user.save()

        # Create social auth
        UserSocialAuth.objects.create(
            user=user,
            provider="github",
            uid="12345",
        )

        response = self.client.post(
            reverse("accounts:password_reset_request"),
            {"email": "social@example.com"},
        )

        self.assertRedirects(response, reverse("accounts:password_reset_request"))
        messages = list(response.wsgi_request._messages)
        assert len(messages) == 1
        assert "社交账号登录" in str(messages[0])
        mock_task.enqueue.assert_not_called()

    def test_password_reset_request_user_without_password_no_social(self):
        """Test password reset for user without password and no social accounts."""
        user = get_user_model().objects.create_user(
            username="nopassuser",
            email="nopass@example.com",
        )
        user.set_unusable_password()
        user.save()

        response = self.client.post(
            reverse("accounts:password_reset_request"),
            {"email": "nopass@example.com"},
        )

        self.assertRedirects(response, reverse("accounts:password_reset_request"))
        messages = list(response.wsgi_request._messages)
        assert len(messages) == 1
        assert "联系管理员" in str(messages[0])


class PasswordResetDoneViewTests(TestCase):
    """Test cases for password reset done view."""

    def test_password_reset_done_view_status_code(self):
        """Test that password reset done page returns 200 status code."""
        response = self.client.get(reverse("accounts:password_reset_done"))
        assert response.status_code == 200

    def test_password_reset_done_view_template(self):
        """Test that password reset done view uses correct template."""
        response = self.client.get(reverse("accounts:password_reset_done"))
        self.assertTemplateUsed(response, "password_reset_done.html")

    def test_password_reset_done_view_contains_message(self):
        """Test that password reset done page contains confirmation message."""
        response = self.client.get(reverse("accounts:password_reset_done"))
        self.assertContains(response, "邮件已发送")


class PasswordResetConfirmViewTests(TestCase):
    """Test cases for password reset confirm view."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="oldpass123",
        )
        self.token = default_token_generator.make_token(self.user)
        self.uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))

    def test_password_reset_confirm_view_get_with_valid_token(self):
        """Test GET request with valid token shows reset form."""
        url = reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": self.uidb64, "token": self.token},
        )
        response = self.client.get(url)

        assert response.status_code == 200
        self.assertTemplateUsed(response, "password_reset_confirm.html")
        self.assertContains(response, "设置新密码")

    def test_password_reset_confirm_view_get_with_invalid_token(self):
        """Test GET request with invalid token shows error."""
        url = reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": self.uidb64, "token": "invalid-token"},
        )
        response = self.client.get(url)

        assert response.status_code == 200
        self.assertTemplateUsed(response, "password_reset_confirm.html")
        self.assertContains(response, "链接无效或已过期")

    def test_password_reset_confirm_view_get_with_invalid_uidb64(self):
        """Test GET request with invalid uidb64 shows error."""
        url = reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": "invalid", "token": self.token},
        )
        response = self.client.get(url)

        assert response.status_code == 200
        self.assertContains(response, "链接无效或已过期")

    def test_password_reset_confirm_view_post_with_valid_data(self):
        """Test POST request with valid data resets password."""
        url = reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": self.uidb64, "token": self.token},
        )
        response = self.client.post(
            url,
            {
                "new_password1": "newpass123",
                "new_password2": "newpass123",
            },
        )

        self.assertRedirects(response, reverse("accounts:sign_in"))

        # Verify password was changed
        self.user.refresh_from_db()
        assert self.user.check_password("newpass123")

        # Verify success message
        messages = list(response.wsgi_request._messages)
        assert len(messages) == 1
        assert "密码重置成功" in str(messages[0])

    def test_password_reset_confirm_view_post_with_mismatched_passwords(self):
        """Test POST request with mismatched passwords shows error."""
        url = reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": self.uidb64, "token": self.token},
        )
        response = self.client.post(
            url,
            {
                "new_password1": "newpass123",
                "new_password2": "differentpass",
            },
        )

        assert response.status_code == 200
        self.assertTemplateUsed(response, "password_reset_confirm.html")

        # Verify password was not changed
        self.user.refresh_from_db()
        assert self.user.check_password("oldpass123")

    def test_password_reset_confirm_view_post_with_invalid_token(self):
        """Test POST request with invalid token shows error."""
        url = reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": self.uidb64, "token": "invalid-token"},
        )
        response = self.client.post(
            url,
            {
                "new_password1": "newpass123",
                "new_password2": "newpass123",
            },
        )

        assert response.status_code == 200
        self.assertContains(response, "链接无效或已过期")

        # Verify password was not changed
        self.user.refresh_from_db()
        assert self.user.check_password("oldpass123")


class ShopListViewTests(TestCase):
    """Test cases for shop list view."""

    def setUp(self):
        """Set up test data."""
        from points.models import PointSource, Tag
        from shop.models import ShopItem

        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )

        # Create some points for the user
        tag = Tag.objects.create(name="test-tag")
        source = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=100
        )
        source.tags.add(tag)

        # Create shop items
        self.item1 = ShopItem.objects.create(
            name="Item 1", description="Description 1", cost=50, is_active=True
        )
        self.item2 = ShopItem.objects.create(
            name="Item 2",
            description="Description 2",
            cost=150,
            is_active=True,
            stock=10,
        )
        self.item3 = ShopItem.objects.create(
            name="Item 3", description="Description 3", cost=30, is_active=False
        )

    def test_shop_list_login_required(self):
        """Test that shop list requires login."""
        response = self.client.get(reverse("accounts:shop_list"))
        assert response.status_code == 302

    def test_shop_list_view_shows_active_items(self):
        """Test that shop list shows only active items."""
        self.client.login(username="testuser", password="password123")
        response = self.client.get(reverse("accounts:shop_list"))

        assert response.status_code == 200
        assert self.item1 in response.context["items"]
        assert self.item2 in response.context["items"]
        assert self.item3 not in response.context["items"]

    def test_shop_list_view_shows_user_points(self):
        """Test that shop list displays user's points."""
        self.client.login(username="testuser", password="password123")
        response = self.client.get(reverse("accounts:shop_list"))

        assert response.status_code == 200
        assert response.context["user_points"] == 100

    def test_shop_list_view_with_no_points(self):
        """Test shop list view when user has no points."""
        _user2 = get_user_model().objects.create_user(
            username="user2", email="user2@example.com", password="password123"
        )
        self.client.login(username="user2", password="password123")
        response = self.client.get(reverse("accounts:shop_list"))

        assert response.status_code == 200
        assert response.context["user_points"] == 0


class RedemptionListViewTests(TestCase):
    """Test cases for redemption list view."""

    def setUp(self):
        """Set up test data."""
        from points.models import PointSource, PointTransaction, Tag
        from shop.models import Redemption, ShopItem

        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )

        # Create shop item and redemption
        self.item = ShopItem.objects.create(
            name="Test Item", description="Description", cost=50, is_active=True
        )

        tag = Tag.objects.create(name="test-tag")
        source = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=50
        )
        source.tags.add(tag)

        transaction = PointTransaction.objects.create(
            user_profile=self.user,
            points=-50,
            transaction_type=PointTransaction.TransactionType.SPEND,
            description="Test redemption",
        )

        self.redemption = Redemption.objects.create(
            user_profile=self.user,
            item=self.item,
            points_cost_at_redemption=50,
            transaction=transaction,
            status=Redemption.StatusChoices.COMPLETED,
        )

    def test_redemption_list_login_required(self):
        """Test that redemption list requires login."""
        response = self.client.get(reverse("accounts:redemption_list"))
        assert response.status_code == 302

    def test_redemption_list_shows_user_redemptions(self):
        """Test that redemption list shows user's redemptions."""
        self.client.login(username="testuser", password="password123")
        response = self.client.get(reverse("accounts:redemption_list"))

        assert response.status_code == 200
        assert self.redemption in response.context["redemptions"]

    def test_redemption_list_empty_for_new_user(self):
        """Test redemption list is empty for user with no redemptions."""
        _user2 = get_user_model().objects.create_user(
            username="user2", email="user2@example.com", password="password123"
        )
        self.client.login(username="user2", password="password123")
        response = self.client.get(reverse("accounts:redemption_list"))

        assert response.status_code == 200
        assert len(response.context["redemptions"]) == 0


class RedeemConfirmViewTests(TestCase):
    """Test cases for redeem confirm view."""

    def setUp(self):
        """Set up test data."""
        from points.models import PointSource, Tag
        from shop.models import ShopItem

        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )

        # Create points for user
        tag = Tag.objects.create(name="test-tag")
        source = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=100
        )
        source.tags.add(tag)

        # Create shop item
        self.item = ShopItem.objects.create(
            name="Test Item", description="Description", cost=50, is_active=True
        )

    def test_redeem_confirm_login_required(self):
        """Test that redeem confirm requires login."""
        response = self.client.get(
            reverse("accounts:redeem_confirm", args=[self.item.id])
        )
        assert response.status_code == 302

    def test_redeem_confirm_get_shows_item_details(self):
        """Test GET request shows item details."""
        self.client.login(username="testuser", password="password123")
        response = self.client.get(
            reverse("accounts:redeem_confirm", args=[self.item.id])
        )

        assert response.status_code == 200
        assert response.context["item"] == self.item
        assert response.context["user_points"] == 100
        assert response.context["can_afford"] is True
        assert response.context["remaining_after_redeem"] == 50
        assert response.context["points_needed"] == 0

    def test_redeem_confirm_cannot_afford(self):
        """Test redeem confirm when user cannot afford item."""
        from shop.models import ShopItem

        expensive_item = ShopItem.objects.create(
            name="Expensive Item", description="Description", cost=200, is_active=True
        )

        self.client.login(username="testuser", password="password123")
        response = self.client.get(
            reverse("accounts:redeem_confirm", args=[expensive_item.id])
        )

        assert response.status_code == 200
        assert response.context["can_afford"] is False
        assert response.context["remaining_after_redeem"] == 0
        assert response.context["points_needed"] == 100

    def test_redeem_confirm_post_successful_redemption(self):
        """Test POST request successfully redeems item."""
        self.client.login(username="testuser", password="password123")
        response = self.client.post(
            reverse("accounts:redeem_confirm", args=[self.item.id])
        )

        assert response.status_code == 302
        assert response.url == reverse("accounts:redemption_list")

        # Verify redemption was created
        from shop.models import Redemption

        redemptions = Redemption.objects.filter(user_profile=self.user)
        assert redemptions.count() == 1
        assert redemptions.first().item == self.item

    def test_redeem_confirm_post_insufficient_points(self):
        """Test POST request fails when user has insufficient points."""
        from shop.models import ShopItem

        expensive_item = ShopItem.objects.create(
            name="Expensive Item", description="Description", cost=200, is_active=True
        )

        self.client.login(username="testuser", password="password123")
        response = self.client.post(
            reverse("accounts:redeem_confirm", args=[expensive_item.id])
        )

        assert response.status_code == 302
        assert response.url == reverse("accounts:shop_list")

        # Verify no redemption was created
        from shop.models import Redemption

        assert Redemption.objects.filter(user_profile=self.user).count() == 0

    def test_redeem_confirm_post_out_of_stock(self):
        """Test POST request fails when item is out of stock."""
        from shop.models import ShopItem

        out_of_stock_item = ShopItem.objects.create(
            name="Out of Stock Item",
            description="Description",
            cost=50,
            is_active=True,
            stock=0,
        )

        self.client.login(username="testuser", password="password123")
        response = self.client.post(
            reverse("accounts:redeem_confirm", args=[out_of_stock_item.id])
        )

        assert response.status_code == 302
        assert response.url == reverse("accounts:shop_list")

        # Verify no redemption was created
        from shop.models import Redemption

        assert Redemption.objects.filter(user_profile=self.user).count() == 0

    def test_redeem_confirm_post_inactive_item(self):
        """Test POST request fails when item is not active."""
        from shop.models import ShopItem

        inactive_item = ShopItem.objects.create(
            name="Inactive Item", description="Description", cost=50, is_active=False
        )

        self.client.login(username="testuser", password="password123")
        response = self.client.post(
            reverse("accounts:redeem_confirm", args=[inactive_item.id])
        )

        assert response.status_code == 302
        assert response.url == reverse("accounts:shop_list")

        # Verify no redemption was created
        from shop.models import Redemption

        assert Redemption.objects.filter(user_profile=self.user).count() == 0

    def test_redeem_confirm_404_for_nonexistent_item(self):
        """Test 404 response for nonexistent item."""
        self.client.login(username="testuser", password="password123")
        response = self.client.get(reverse("accounts:redeem_confirm", args=[99999]))

        assert response.status_code == 404


class PublicProfileViewTests(CacheClearTestCase):
    """Test cases for public profile view."""

    def setUp(self):
        """Set up test user with profile."""
        User = get_user_model()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.profile = UserProfile.objects.create(
            user=self.user,
            bio="Test bio for public profile",
            company="Test Company",
            location="Test City",
            github_url="https://github.com/testuser",
            blog_url="https://blog.testuser.com",
        )

    def test_public_profile_view_accessible_by_anyone(self):
        """Test that public profile is accessible without login."""
        response = self.client.get(reverse("public_profile", args=["testuser"]))
        assert response.status_code == 200

    def test_public_profile_view_accessible_by_logged_in_user(self):
        """Test that public profile is accessible by logged in users."""
        other_user = get_user_model().objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="otherpass123",
        )
        self.client.force_login(other_user)
        response = self.client.get(reverse("public_profile", args=["testuser"]))
        assert response.status_code == 200

    def test_public_profile_view_uses_correct_template(self):
        """Test that public profile view uses correct template."""
        response = self.client.get(reverse("public_profile", args=["testuser"]))
        self.assertTemplateUsed(response, "public_profile.html")

    def test_public_profile_view_contains_user_info(self):
        """Test that public profile displays user information."""
        response = self.client.get(reverse("public_profile", args=["testuser"]))
        assert response.status_code == 200
        self.assertContains(response, "testuser")
        self.assertContains(response, "Test bio for public profile")
        self.assertContains(response, "Test Company")
        self.assertContains(response, "Test City")

    def test_public_profile_view_contains_social_links(self):
        """Test that public profile displays social links."""
        response = self.client.get(reverse("public_profile", args=["testuser"]))
        assert response.status_code == 200
        self.assertContains(response, "https://github.com/testuser")
        self.assertContains(response, "https://blog.testuser.com")

    def test_public_profile_view_displays_total_points(self):
        """Test that public profile displays total points."""
        from points.models import PointSource, Tag

        tag = Tag.objects.create(name="test-tag")
        source = PointSource.objects.create(
            user_profile=self.user,
            initial_points=100,
            remaining_points=100,
            notes="Test points",
        )
        source.tags.add(tag)

        response = self.client.get(reverse("public_profile", args=["testuser"]))
        assert response.status_code == 200
        self.assertContains(response, "100")

    def test_public_profile_view_displays_work_experience(self):
        """Test that public profile displays work experience."""
        WorkExperience.objects.create(
            profile=self.profile,
            company_name="Test Corp",
            title="Software Engineer",
            start_date=date(2020, 1, 1),
            end_date=date(2022, 12, 31),
            description="Worked on test projects",
        )

        response = self.client.get(reverse("public_profile", args=["testuser"]))
        assert response.status_code == 200
        self.assertContains(response, "Test Corp")
        self.assertContains(response, "Software Engineer")
        self.assertContains(response, "Worked on test projects")

    def test_public_profile_view_displays_education(self):
        """Test that public profile displays education."""
        Education.objects.create(
            profile=self.profile,
            institution_name="Test University",
            degree="Bachelor",
            field_of_study="Computer Science",
            start_date=date(2016, 9, 1),
            end_date=date(2020, 6, 30),
        )

        response = self.client.get(reverse("public_profile", args=["testuser"]))
        assert response.status_code == 200
        self.assertContains(response, "Test University")
        self.assertContains(response, "Computer Science")
        self.assertContains(response, "Bachelor")

    def test_public_profile_view_handles_current_work(self):
        """Test that public profile handles work experience without end date."""
        WorkExperience.objects.create(
            profile=self.profile,
            company_name="Current Corp",
            title="Senior Engineer",
            start_date=date(2023, 1, 1),
            end_date=None,
            description="Current position",
        )

        response = self.client.get(reverse("public_profile", args=["testuser"]))
        assert response.status_code == 200
        self.assertContains(response, "Current Corp")
        self.assertContains(response, "至今")

    def test_public_profile_view_handles_current_education(self):
        """Test that public profile handles education without end date."""
        Education.objects.create(
            profile=self.profile,
            institution_name="Current University",
            degree="PhD",
            field_of_study="Machine Learning",
            start_date=date(2022, 9, 1),
            end_date=None,
        )

        response = self.client.get(reverse("public_profile", args=["testuser"]))
        assert response.status_code == 200
        self.assertContains(response, "Current University")
        self.assertContains(response, "至今")

    def test_public_profile_view_creates_profile_if_not_exists(self):
        """Test that view creates profile if it doesn't exist."""
        user_without_profile = get_user_model().objects.create_user(
            username="noprofile",
            email="noprofile@example.com",
            password="testpass123",
        )

        response = self.client.get(reverse("public_profile", args=["noprofile"]))
        assert response.status_code == 200

        # Verify profile was created
        profile = UserProfile.objects.get(user=user_without_profile)
        assert profile is not None

    def test_public_profile_view_404_for_nonexistent_user(self):
        """Test 404 response for nonexistent username."""
        response = self.client.get(reverse("public_profile", args=["nonexistentuser"]))
        assert response.status_code == 404

    def test_public_profile_view_context_data(self):
        """Test that view provides correct context data."""
        response = self.client.get(reverse("public_profile", args=["testuser"]))
        assert response.status_code == 200

        assert "profile_user" in response.context
        assert "profile" in response.context
        assert "work_experiences" in response.context
        assert "educations" in response.context
        assert "total_points" in response.context

        assert response.context["profile_user"] == self.user
        assert response.context["profile"] == self.profile
        assert response.context["total_points"] == 0

    def test_public_profile_view_without_bio(self):
        """Test public profile displays correctly without bio."""
        user_no_bio = get_user_model().objects.create_user(
            username="nobio",
            email="nobio@example.com",
            password="testpass123",
        )
        UserProfile.objects.create(user=user_no_bio, bio="")

        response = self.client.get(reverse("public_profile", args=["nobio"]))
        assert response.status_code == 200
        self.assertContains(response, "开源贡献者")

    def test_public_profile_view_without_social_links(self):
        """Test public profile handles absence of social links."""
        user_no_social = get_user_model().objects.create_user(
            username="nosocial",
            email="nosocial@example.com",
            password="testpass123",
        )
        UserProfile.objects.create(
            user=user_no_social,
            github_url="",
            blog_url="",
            homepage_url="",
            twitter_url="",
            linkedin_url="",
        )

        response = self.client.get(reverse("public_profile", args=["nosocial"]))
        assert response.status_code == 200
        # Should not show social links section if no links are present
