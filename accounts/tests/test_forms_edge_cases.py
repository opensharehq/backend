"""
Additional edge case tests for accounts forms.

These tests supplement the existing test_forms.py to add defense-in-depth
testing beyond basic coverage requirements.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.forms import (
    EducationForm,
    ProfileForm,
    WorkExperienceForm,
)
from accounts.models import UserProfile


class ProfileFormEdgeCaseTests(TestCase):
    """Edge case tests for ProfileForm."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
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
        long_bio = "A" * 500
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
