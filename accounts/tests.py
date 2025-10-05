from datetime import date

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.forms import EducationForm, ProfileForm, SignUpForm, WorkExperienceForm
from accounts.models import Education, UserProfile, WorkExperience


class UserModelTests(TestCase):
    def test_user_defaults_active(self):
        user = get_user_model().objects.create_user(
            username="active-user",
            email="active@example.com",
            password="password123",
        )

        self.assertTrue(user.is_active)


class UserProfileModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )

    def test_user_profile_creation(self):
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

        self.assertEqual(profile.user, self.user)
        self.assertEqual(profile.bio, "Test bio")
        self.assertEqual(profile.birth_date, date(1990, 1, 1))
        self.assertEqual(profile.github_url, "https://github.com/testuser")
        self.assertEqual(profile.company, "Test Company")
        self.assertEqual(profile.location, "Test City")

    def test_user_profile_str(self):
        profile = UserProfile.objects.create(user=self.user)
        self.assertEqual(str(profile), "testuser")

    def test_user_profile_optional_fields(self):
        profile = UserProfile.objects.create(user=self.user)

        self.assertEqual(profile.bio, "")
        self.assertIsNone(profile.birth_date)
        self.assertEqual(profile.github_url, "")

    def test_user_profile_one_to_one_relationship(self):
        profile = UserProfile.objects.create(user=self.user)
        self.assertEqual(self.user.profile, profile)


class WorkExperienceModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        self.profile = UserProfile.objects.create(user=self.user)

    def test_work_experience_creation(self):
        work_exp = WorkExperience.objects.create(
            profile=self.profile,
            company_name="Test Company",
            title="Software Engineer",
            start_date=date(2020, 1, 1),
            end_date=date(2022, 12, 31),
            description="Test description",
        )

        self.assertEqual(work_exp.profile, self.profile)
        self.assertEqual(work_exp.company_name, "Test Company")
        self.assertEqual(work_exp.title, "Software Engineer")
        self.assertEqual(work_exp.start_date, date(2020, 1, 1))
        self.assertEqual(work_exp.end_date, date(2022, 12, 31))
        self.assertEqual(work_exp.description, "Test description")

    def test_work_experience_current_job(self):
        work_exp = WorkExperience.objects.create(
            profile=self.profile,
            company_name="Current Company",
            title="Senior Engineer",
            start_date=date(2023, 1, 1),
        )

        self.assertIsNone(work_exp.end_date)

    def test_work_experience_ordering(self):
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
        self.assertEqual(work_experiences[0], work_exp2)
        self.assertEqual(work_experiences[1], work_exp1)


class EducationModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        self.profile = UserProfile.objects.create(user=self.user)

    def test_education_creation(self):
        education = Education.objects.create(
            profile=self.profile,
            institution_name="Test University",
            degree="本科",
            field_of_study="Computer Science",
            start_date=date(2015, 9, 1),
            end_date=date(2019, 6, 30),
        )

        self.assertEqual(education.profile, self.profile)
        self.assertEqual(education.institution_name, "Test University")
        self.assertEqual(education.degree, "本科")
        self.assertEqual(education.field_of_study, "Computer Science")
        self.assertEqual(education.start_date, date(2015, 9, 1))
        self.assertEqual(education.end_date, date(2019, 6, 30))

    def test_education_ongoing(self):
        education = Education.objects.create(
            profile=self.profile,
            institution_name="Current University",
            degree="硕士",
            field_of_study="Artificial Intelligence",
            start_date=date(2023, 9, 1),
        )

        self.assertIsNone(education.end_date)

    def test_education_ordering(self):
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
        self.assertEqual(educations[0], edu2)
        self.assertEqual(educations[1], edu1)


class UserAdminRegistrationTests(TestCase):
    databases = {"default"}

    def test_user_registered_with_admin_site(self):
        from accounts import admin as accounts_admin

        user_model = get_user_model()

        self.assertIn(user_model, admin.site._registry)
        self.assertIsInstance(
            admin.site._registry[user_model],
            accounts_admin.UserAdmin,
        )


class AccountsIndexViewTests(TestCase):
    def test_accounts_index_redirects_to_signin_when_not_authenticated(self):
        response = self.client.get(reverse("accounts:index"))
        self.assertRedirects(response, reverse("accounts:sign_in"))

    def test_accounts_index_redirects_to_profile_when_authenticated(self):
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:index"))
        self.assertRedirects(response, reverse("accounts:profile"))


class SignInViewTests(TestCase):
    def test_sign_in_view_status_code(self):
        response = self.client.get(reverse("accounts:sign_in"))
        self.assertEqual(response.status_code, 200)

    def test_sign_in_view_template(self):
        response = self.client.get(reverse("accounts:sign_in"))
        self.assertTemplateUsed(response, "sign_in.html")

    def test_sign_in_view_contains_email_form(self):
        response = self.client.get(reverse("accounts:sign_in"))
        self.assertContains(response, "email")
        self.assertContains(response, "password")

    def test_sign_in_view_contains_username_form(self):
        response = self.client.get(reverse("accounts:sign_in"))
        self.assertContains(response, "username")

    def test_sign_in_view_contains_signup_link(self):
        response = self.client.get(reverse("accounts:sign_in"))
        self.assertContains(response, reverse("accounts:sign_up"))


class SignUpViewTests(TestCase):
    def test_sign_up_view_get_status_code(self):
        response = self.client.get(reverse("accounts:sign_up"))
        self.assertEqual(response.status_code, 200)

    def test_sign_up_view_template(self):
        response = self.client.get(reverse("accounts:sign_up"))
        self.assertTemplateUsed(response, "sign_up.html")

    def test_sign_up_view_contains_form_fields(self):
        response = self.client.get(reverse("accounts:sign_up"))
        self.assertContains(response, "username")
        self.assertContains(response, "email")
        self.assertContains(response, "password1")
        self.assertContains(response, "password2")

    def test_sign_up_view_post_valid_data(self):
        data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password1": "testpass123",
            "password2": "testpass123",
        }
        response = self.client.post(reverse("accounts:sign_up"), data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(get_user_model().objects.filter(username="newuser").exists())

    def test_sign_up_view_post_invalid_password_mismatch(self):
        data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password1": "testpass123",
            "password2": "wrongpass123",
        }
        response = self.client.post(reverse("accounts:sign_up"), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username="newuser").exists())

    def test_sign_up_view_contains_signin_link(self):
        response = self.client.get(reverse("accounts:sign_up"))
        self.assertContains(response, reverse("accounts:sign_in"))


class ProfileViewTests(TestCase):
    def test_profile_view_requires_login(self):
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/accounts/login/"))

    def test_profile_view_authenticated_user(self):
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "profile.html")

    def test_profile_view_displays_user_info(self):
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "testuser")
        self.assertContains(response, "test@example.com")

    def test_profile_view_creates_profile_if_not_exists(self):
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.client.force_login(user)
        self.assertFalse(UserProfile.objects.filter(user=user).exists())
        response = self.client.get(reverse("accounts:profile"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_profile_view_displays_profile_data(self):
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
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
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
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
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
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
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
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
    def test_logout_view_requires_login(self):
        response = self.client.get(reverse("accounts:logout"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/accounts/login/"))

    def test_logout_view_logs_out_user(self):
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.client.force_login(user)
        self.assertTrue(self.client.session.get("_auth_user_id"))

        response = self.client.get(reverse("accounts:logout"))

        self.assertRedirects(response, reverse("homepage:index"))
        self.assertFalse(self.client.session.get("_auth_user_id"))

    def test_logout_view_displays_success_message(self):
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:logout"), follow=True)
        messages = list(response.context["messages"])
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "您已成功退出登录")


class ProfileEditViewTests(TestCase):
    def test_profile_edit_view_requires_login(self):
        response = self.client.get(reverse("accounts:profile_edit"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/accounts/login/"))

    def test_profile_edit_view_get_authenticated(self):
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile_edit"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "profile_edit.html")

    def test_profile_edit_view_creates_profile_if_not_exists(self):
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.client.force_login(user)
        self.assertFalse(UserProfile.objects.filter(user=user).exists())
        response = self.client.get(reverse("accounts:profile_edit"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_profile_edit_view_post_valid_data(self):
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
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
        self.assertEqual(profile.bio, "Updated bio")
        self.assertEqual(profile.company, "New Company")
        self.assertEqual(profile.location, "New City")

    def test_profile_edit_view_post_no_changes(self):
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        UserProfile.objects.create(
            user=user, bio="Original bio", company="Original Company"
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
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "未检测到任何更改")

    def test_profile_edit_view_post_with_changes(self):
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        profile = UserProfile.objects.create(
            user=user, bio="Original bio", company="Original Company"
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
        self.assertEqual(len(messages), 1)
        self.assertEqual(str(messages[0]), "个人资料已更新")
        profile.refresh_from_db()
        self.assertEqual(profile.bio, "Updated bio")

    def test_profile_edit_view_displays_form(self):
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:profile_edit"))
        self.assertContains(response, "个人简介")
        self.assertContains(response, "保存更改")

    def test_profile_edit_view_add_work_experience(self):
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
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
        self.assertEqual(WorkExperience.objects.count(), 1)
        work = WorkExperience.objects.first()
        self.assertEqual(work.company_name, "Test Company")
        self.assertEqual(work.title, "Software Engineer")

    def test_profile_edit_view_add_education(self):
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
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
        self.assertEqual(Education.objects.count(), 1)
        edu = Education.objects.first()
        self.assertEqual(edu.institution_name, "Test University")
        self.assertEqual(edu.field_of_study, "Computer Science")

    def test_profile_edit_view_delete_work_experience(self):
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
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
        self.assertEqual(WorkExperience.objects.count(), 0)

    def test_profile_edit_view_delete_education(self):
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
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
        self.assertEqual(Education.objects.count(), 0)

    def test_profile_edit_view_displays_date_validation_error(self):
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
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
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "开始日期必须早于结束日期")

    def test_profile_edit_view_displays_existing_experiences(self):
        user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
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
    def test_signup_form_valid_data(self):
        form = SignUpForm(
            data={
                "username": "testuser",
                "email": "test@example.com",
                "password1": "testpass123",
                "password2": "testpass123",
            }
        )
        self.assertTrue(form.is_valid())

    def test_signup_form_duplicate_email(self):
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
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_signup_form_password_mismatch(self):
        form = SignUpForm(
            data={
                "username": "testuser",
                "email": "test@example.com",
                "password1": "testpass123",
                "password2": "wrongpass123",
            }
        )
        self.assertFalse(form.is_valid())

    def test_signup_form_creates_user(self):
        form = SignUpForm(
            data={
                "username": "testuser",
                "email": "test@example.com",
                "password1": "testpass123",
                "password2": "testpass123",
            }
        )
        self.assertTrue(form.is_valid())
        user = form.save()
        self.assertEqual(user.username, "testuser")
        self.assertEqual(user.email, "test@example.com")
        self.assertTrue(user.check_password("testpass123"))


class ProfileFormTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.profile = UserProfile.objects.create(user=self.user)

    def test_profile_form_valid_data(self):
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
        self.assertTrue(form.is_valid())

    def test_profile_form_empty_data(self):
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
        self.assertTrue(form.is_valid())

    def test_profile_form_saves_data(self):
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
        self.assertTrue(form.is_valid())
        profile = form.save()
        self.assertEqual(profile.bio, "Updated bio")
        self.assertEqual(profile.company, "Updated Company")
        self.assertEqual(profile.location, "Updated City")
        self.assertEqual(profile.github_url, "https://github.com/updated")

    def test_profile_form_invalid_url(self):
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
        self.assertFalse(form.is_valid())
        self.assertIn("github_url", form.errors)

    def test_profile_form_widget_classes(self):
        form = ProfileForm(instance=self.profile)
        self.assertIn("form-control", form.fields["bio"].widget.attrs["class"])
        self.assertIn("form-control", form.fields["company"].widget.attrs["class"])
        self.assertIn("form-control", form.fields["location"].widget.attrs["class"])


class WorkExperienceFormTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.profile = UserProfile.objects.create(user=self.user)

    def test_work_experience_form_valid_data(self):
        form = WorkExperienceForm(
            data={
                "company_name": "Test Company",
                "title": "Software Engineer",
                "start_date": "2020-01-01",
                "end_date": "2022-12-31",
                "description": "Test description",
            }
        )
        self.assertTrue(form.is_valid())

    def test_work_experience_form_no_end_date(self):
        form = WorkExperienceForm(
            data={
                "company_name": "Current Company",
                "title": "Senior Engineer",
                "start_date": "2023-01-01",
                "end_date": "",
                "description": "",
            }
        )
        self.assertTrue(form.is_valid())

    def test_work_experience_form_saves_data(self):
        form = WorkExperienceForm(
            data={
                "company_name": "Test Company",
                "title": "Engineer",
                "start_date": "2020-01-01",
                "end_date": "",
                "description": "Test",
            }
        )
        self.assertTrue(form.is_valid())
        work = form.save(commit=False)
        work.profile = self.profile
        work.save()
        self.assertEqual(work.company_name, "Test Company")
        self.assertEqual(work.title, "Engineer")

    def test_work_experience_form_invalid_date_range(self):
        form = WorkExperienceForm(
            data={
                "company_name": "Test Company",
                "title": "Engineer",
                "start_date": "2022-12-31",
                "end_date": "2020-01-01",
                "description": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("开始日期必须早于结束日期", str(form.errors))

    def test_work_experience_form_same_start_end_date(self):
        form = WorkExperienceForm(
            data={
                "company_name": "Test Company",
                "title": "Engineer",
                "start_date": "2020-01-01",
                "end_date": "2020-01-01",
                "description": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("开始日期必须早于结束日期", str(form.errors))


class EducationFormTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.profile = UserProfile.objects.create(user=self.user)

    def test_education_form_valid_data(self):
        form = EducationForm(
            data={
                "institution_name": "Test University",
                "degree": "本科",
                "field_of_study": "Computer Science",
                "start_date": "2015-09-01",
                "end_date": "2019-06-30",
            }
        )
        self.assertTrue(form.is_valid())

    def test_education_form_no_end_date(self):
        form = EducationForm(
            data={
                "institution_name": "Current University",
                "degree": "硕士",
                "field_of_study": "AI",
                "start_date": "2023-09-01",
                "end_date": "",
            }
        )
        self.assertTrue(form.is_valid())

    def test_education_form_saves_data(self):
        form = EducationForm(
            data={
                "institution_name": "Test University",
                "degree": "本科",
                "field_of_study": "CS",
                "start_date": "2015-09-01",
                "end_date": "2019-06-30",
            }
        )
        self.assertTrue(form.is_valid())
        edu = form.save(commit=False)
        edu.profile = self.profile
        edu.save()
        self.assertEqual(edu.institution_name, "Test University")
        self.assertEqual(edu.field_of_study, "CS")

    def test_education_form_invalid_date_range(self):
        form = EducationForm(
            data={
                "institution_name": "Test University",
                "degree": "本科",
                "field_of_study": "CS",
                "start_date": "2019-06-30",
                "end_date": "2015-09-01",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("开始日期必须早于结束日期", str(form.errors))

    def test_education_form_same_start_end_date(self):
        form = EducationForm(
            data={
                "institution_name": "Test University",
                "degree": "本科",
                "field_of_study": "CS",
                "start_date": "2015-09-01",
                "end_date": "2015-09-01",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("开始日期必须早于结束日期", str(form.errors))
