from datetime import date

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase

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
