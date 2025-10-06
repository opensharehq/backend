"""Tests for accounts models."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

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

    def test_total_points_with_no_sources(self):
        """Test total_points returns 0 when user has no point sources."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )

        assert user.total_points == 0

    def test_total_points_with_sources(self):
        """Test total_points returns sum of remaining points."""
        from points.models import PointSource, Tag

        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )

        tag = Tag.objects.create(name="test-tag")

        source1 = PointSource.objects.create(
            user_profile=user, initial_points=100, remaining_points=80
        )
        source1.tags.add(tag)

        source2 = PointSource.objects.create(
            user_profile=user, initial_points=50, remaining_points=30
        )
        source2.tags.add(tag)

        assert user.total_points == 110

    def test_get_points_by_tag_empty(self):
        """Test get_points_by_tag returns empty list when no sources."""
        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )

        result = user.get_points_by_tag()

        assert result == []

    def test_get_points_by_tag_multiple_tags(self):
        """Test get_points_by_tag groups points correctly."""
        from points.models import PointSource, Tag

        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )

        tag1 = Tag.objects.create(name="tag1")
        tag2 = Tag.objects.create(name="tag2")

        source1 = PointSource.objects.create(
            user_profile=user, initial_points=100, remaining_points=80
        )
        source1.tags.add(tag1)

        source2 = PointSource.objects.create(
            user_profile=user, initial_points=50, remaining_points=30
        )
        source2.tags.add(tag1)
        source2.tags.add(tag2)

        result = user.get_points_by_tag()

        assert len(result) == 2
        tag_dict = {item["tag"]: item["points"] for item in result}
        assert tag_dict["tag1"] == 110
        assert tag_dict["tag2"] == 30

    def test_get_points_by_tag_ignores_empty_sources(self):
        """Test get_points_by_tag ignores sources with 0 remaining points."""
        from points.models import PointSource, Tag

        user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )

        tag = Tag.objects.create(name="test-tag")

        source1 = PointSource.objects.create(
            user_profile=user, initial_points=100, remaining_points=50
        )
        source1.tags.add(tag)

        source2 = PointSource.objects.create(
            user_profile=user, initial_points=50, remaining_points=0
        )
        source2.tags.add(tag)

        result = user.get_points_by_tag()

        assert len(result) == 1
        assert result[0]["tag"] == "test-tag"
        assert result[0]["points"] == 50


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
