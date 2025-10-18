"""Tests for accounts models."""

from datetime import date

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from accounts.models import (
    TOTAL_POINTS_CACHE_KEY_TEMPLATE,
    Education,
    ShippingAddress,
    UserProfile,
    WorkExperience,
)
from common.test_utils import CacheClearTestCase


class UserModelTests(CacheClearTestCase):
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

        # Test the property directly to ensure line coverage
        total = user.total_points
        assert total == 110

    def test_total_points_aggregation_with_value(self):
        """Test total_points when aggregate returns a non-None value."""
        from points.models import PointSource, Tag

        user = get_user_model().objects.create_user(
            username="points-user",
            email="points@example.com",
            password="password123",
        )

        tag = Tag.objects.create(name="bonus")

        # Create a point source with remaining points
        source = PointSource.objects.create(
            user_profile=user, initial_points=200, remaining_points=150
        )
        source.tags.add(tag)

        # Access the property to trigger the aggregation
        result = user.total_points

        # Verify the aggregation logic is covered
        assert result == 150

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            }
        }
    )
    def test_total_points_cached_and_invalidated(self):
        """total_points caches values and clears cache when data changes."""
        from points.models import PointSource, Tag

        cache.clear()

        user = get_user_model().objects.create_user(
            username="cached-user",
            email="cached@example.com",
            password="password123",
        )

        tag = Tag.objects.create(name="cache")
        source = PointSource.objects.create(
            user=user,
            initial_points=200,
            remaining_points=200,
        )
        source.tags.add(tag)

        cache_key = TOTAL_POINTS_CACHE_KEY_TEMPLATE.format(user_id=user.pk)
        assert cache.get(cache_key) is None

        assert user.total_points == 200
        # Second access should reuse cached value
        assert user.total_points == 200
        assert cache.get(cache_key) == 200

        # Manual clear should remove cached attribute and cache entry
        user.__dict__["total_points"] = 999
        user.clear_points_cache()
        assert "total_points" not in user.__dict__
        assert cache.get(cache_key) is None

        # Re-cache for signal-driven invalidation check
        assert user.total_points == 200

        source.remaining_points = 150
        source.save()

        assert cache.get(cache_key) is None
        assert user.total_points == 150

    def test_user_queryset_annotate_with_points(self):
        """Custom queryset and manager expose annotate_with_points helper."""
        from points.models import PointSource, Tag

        user = get_user_model().objects.create_user(
            username="annotated",
            email="annotated@example.com",
            password="password123",
        )

        tag = Tag.objects.create(name="annotated-tag")
        source = PointSource.objects.create(
            user=user,
            initial_points=120,
            remaining_points=90,
        )
        source.tags.add(tag)

        annotated = get_user_model().objects.annotate_with_points().get(pk=user.pk)
        assert annotated.total_points_calculated == 90

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

    def test_get_points_by_tag_accumulates_same_tag(self):
        """Test get_points_by_tag accumulates points for the same tag across sources."""
        from points.models import PointSource, Tag

        user = get_user_model().objects.create_user(
            username="accumulate-user",
            email="accumulate@example.com",
            password="password123",
        )

        tag1 = Tag.objects.create(name="reward")
        tag2 = Tag.objects.create(name="bonus")

        # Source 1 with tag1
        source1 = PointSource.objects.create(
            user_profile=user, initial_points=100, remaining_points=60
        )
        source1.tags.add(tag1)

        # Source 2 with tag1 and tag2
        source2 = PointSource.objects.create(
            user_profile=user, initial_points=80, remaining_points=40
        )
        source2.tags.add(tag1)
        source2.tags.add(tag2)

        # Source 3 with only tag2
        source3 = PointSource.objects.create(
            user_profile=user, initial_points=50, remaining_points=25
        )
        source3.tags.add(tag2)

        result = user.get_points_by_tag()

        # Should have 2 tags
        assert len(result) == 2

        # Convert to dict for easier assertion
        tag_dict = {item["tag"]: item["points"] for item in result}

        # tag1 should have 60 + 40 = 100 points
        assert tag_dict["reward"] == 100

        # tag2 should have 40 + 25 = 65 points
        assert tag_dict["bonus"] == 65

    def test_get_points_by_tag_with_source_without_tags(self):
        """Test get_points_by_tag with point source that has no tags."""
        from points.models import PointSource

        user = get_user_model().objects.create_user(
            username="notag-user",
            email="notag@example.com",
            password="password123",
        )

        # Create a source with remaining points but no tags
        PointSource.objects.create(
            user_profile=user, initial_points=100, remaining_points=50
        )

        result = user.get_points_by_tag()

        # Should return empty list because source has no tags
        assert result == []

    def test_get_points_by_tag_comprehensive_coverage(self):
        """Test get_points_by_tag to ensure all code paths are covered."""
        from points.models import PointSource, Tag

        user = get_user_model().objects.create_user(
            username="coverage-user",
            email="coverage@example.com",
            password="password123",
        )

        # Create multiple tags
        tag_a = Tag.objects.create(name="tag-a")
        tag_b = Tag.objects.create(name="tag-b")
        tag_c = Tag.objects.create(name="tag-c")

        # Source 1: has tag_a and tag_b
        source1 = PointSource.objects.create(
            user_profile=user, initial_points=100, remaining_points=30
        )
        source1.tags.add(tag_a, tag_b)

        # Source 2: has tag_a (accumulates with source1)
        source2 = PointSource.objects.create(
            user_profile=user, initial_points=50, remaining_points=20
        )
        source2.tags.add(tag_a)

        # Source 3: has tag_c (new tag)
        source3 = PointSource.objects.create(
            user_profile=user, initial_points=75, remaining_points=15
        )
        source3.tags.add(tag_c)

        # Source 4: has remaining_points=0, should be ignored
        source4 = PointSource.objects.create(
            user_profile=user, initial_points=200, remaining_points=0
        )
        source4.tags.add(tag_a)

        result = user.get_points_by_tag()

        # Convert to dict for assertions
        tag_dict = {item["tag"]: item["points"] for item in result}

        # Verify all branches:
        # - Loop through sources with remaining_points > 0
        # - Loop through tags for each source
        # - Check if tag exists in dict (both True and False paths)
        # - Accumulate points for existing tags
        assert len(tag_dict) == 3
        assert tag_dict["tag-a"] == 50  # 30 + 20
        assert tag_dict["tag-b"] == 30  # Only from source1
        assert tag_dict["tag-c"] == 15  # Only from source3


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
        # Explicitly test __str__ method
        str_representation = str(profile)
        assert str_representation == "testuser"
        assert str_representation == self.user.username

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


class ShippingAddressModelTests(TestCase):
    """Test cases for ShippingAddress model."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )

    def test_create_shipping_address(self):
        """Test creating a shipping address."""
        address = ShippingAddress.objects.create(
            user=self.user,
            receiver_name="张三",
            phone="13800138000",
            province="北京",
            city="北京市",
            district="朝阳区",
            address="某某街道123号",
            is_default=True,
        )

        assert address.receiver_name == "张三"
        assert address.phone == "13800138000"
        assert address.province == "北京"
        assert address.is_default is True

    def test_shipping_address_str(self):
        """Test shipping address string representation."""
        address = ShippingAddress.objects.create(
            user=self.user,
            receiver_name="李四",
            phone="13900139000",
            province="上海",
            city="上海市",
            district="浦东新区",
            address="陆家嘴环路1000号",
            is_default=False,
        )

        expected = "李四 - 上海上海市浦东新区陆家嘴环路1000号"
        assert str(address) == expected

    def test_only_one_default_address_per_user(self):
        """Test that only one address can be default per user."""
        # Create first default address
        address1 = ShippingAddress.objects.create(
            user=self.user,
            receiver_name="张三",
            phone="13800138000",
            province="北京",
            city="北京市",
            district="朝阳区",
            address="地址1",
            is_default=True,
        )

        # Create second default address
        address2 = ShippingAddress.objects.create(
            user=self.user,
            receiver_name="李四",
            phone="13900139000",
            province="上海",
            city="上海市",
            district="浦东新区",
            address="地址2",
            is_default=True,
        )

        # Refresh address1 from database
        address1.refresh_from_db()

        # First address should no longer be default
        assert address1.is_default is False
        assert address2.is_default is True

    def test_multiple_users_can_have_default_addresses(self):
        """Test that different users can each have a default address."""
        user2 = get_user_model().objects.create_user(
            username="user2",
            email="user2@example.com",
            password="password123",
        )

        address1 = ShippingAddress.objects.create(
            user=self.user,
            receiver_name="张三",
            phone="13800138000",
            province="北京",
            city="北京市",
            district="朝阳区",
            address="地址1",
            is_default=True,
        )

        address2 = ShippingAddress.objects.create(
            user=user2,
            receiver_name="李四",
            phone="13900139000",
            province="上海",
            city="上海市",
            district="浦东新区",
            address="地址2",
            is_default=True,
        )

        # Both addresses should remain default
        assert address1.is_default is True
        assert address2.is_default is True

    def test_updating_existing_default_address(self):
        """Test updating an existing default address to remain default."""
        address = ShippingAddress.objects.create(
            user=self.user,
            receiver_name="张三",
            phone="13800138000",
            province="北京",
            city="北京市",
            district="朝阳区",
            address="旧地址",
            is_default=True,
        )

        # Update the address
        address.address = "新地址"
        address.save()

        # Should still be default
        address.refresh_from_db()
        assert address.is_default is True
        assert address.address == "新地址"

    def test_shipping_address_ordering(self):
        """Test that addresses are ordered by is_default desc, then updated_at desc."""
        # Create non-default address first
        addr1 = ShippingAddress.objects.create(
            user=self.user,
            receiver_name="张三",
            phone="13800138000",
            province="北京",
            city="北京市",
            district="朝阳区",
            address="地址1",
            is_default=False,
        )

        # Create default address
        addr2 = ShippingAddress.objects.create(
            user=self.user,
            receiver_name="李四",
            phone="13900139000",
            province="上海",
            city="上海市",
            district="浦东新区",
            address="地址2",
            is_default=True,
        )

        addresses = ShippingAddress.objects.filter(user=self.user)
        # Default address should come first
        assert addresses[0] == addr2
        assert addresses[1] == addr1

    def test_cascade_delete_on_user_deletion(self):
        """Test that addresses are deleted when user is deleted."""
        ShippingAddress.objects.create(
            user=self.user,
            receiver_name="张三",
            phone="13800138000",
            province="北京",
            city="北京市",
            district="朝阳区",
            address="地址1",
            is_default=True,
        )

        user_id = self.user.id
        assert ShippingAddress.objects.filter(user_id=user_id).count() == 1

        # Delete user
        self.user.delete()

        # Addresses should be cascade deleted
        assert ShippingAddress.objects.filter(user_id=user_id).count() == 0
