"""Tests for shipping address integration in profile edit view."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import ShippingAddress, UserProfile


class ProfileEditWithShippingAddressTests(TestCase):
    """Test cases for shipping address management in profile edit view."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        self.profile, _ = UserProfile.objects.get_or_create(user=self.user)
        self.url = reverse("accounts:profile_edit")

    def test_profile_edit_view_includes_address_formset(self):
        """Test that profile edit view includes address formset in context."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)

        assert response.status_code == 200
        assert "address_formset" in response.context
        assert response.context["address_formset"] is not None

    def test_add_shipping_address_via_profile_edit(self):
        """Test adding a shipping address through profile edit form."""
        self.client.force_login(self.user)

        # Prepare form data for profile and address
        data = {
            # Profile form data
            "bio": "Test bio",
            "birth_date": "",
            "github_url": "",
            "homepage_url": "",
            "blog_url": "",
            "twitter_url": "",
            "linkedin_url": "",
            "company": "",
            "location": "",
            # Work experience formset
            "work_experiences-TOTAL_FORMS": "0",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            # Education formset
            "educations-TOTAL_FORMS": "0",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
            # Shipping address formset - add one address
            "shipping_addresses-TOTAL_FORMS": "1",
            "shipping_addresses-INITIAL_FORMS": "0",
            "shipping_addresses-MIN_NUM_FORMS": "0",
            "shipping_addresses-MAX_NUM_FORMS": "1000",
            "shipping_addresses-0-receiver_name": "张三",
            "shipping_addresses-0-phone": "13800138000",
            "shipping_addresses-0-province": "北京",
            "shipping_addresses-0-city": "北京市",
            "shipping_addresses-0-district": "朝阳区",
            "shipping_addresses-0-address": "某某街道123号",
            "shipping_addresses-0-is_default": "on",
        }

        response = self.client.post(self.url, data)

        # Should redirect to profile
        assert response.status_code == 302
        assert response.url == reverse("accounts:profile")

        # Address should be created
        assert ShippingAddress.objects.filter(user=self.user).count() == 1
        address = ShippingAddress.objects.get(user=self.user)
        assert address.receiver_name == "张三"
        assert address.is_default is True

    def test_edit_existing_shipping_address_via_profile_edit(self):
        """Test editing an existing shipping address through profile edit."""
        self.client.force_login(self.user)

        # Create an existing address
        address = ShippingAddress.objects.create(
            user=self.user,
            receiver_name="李四",
            phone="13900139000",
            province="上海",
            city="上海市",
            district="浦东新区",
            address="旧地址",
            is_default=True,
        )

        data = {
            # Profile form data
            "bio": "",
            "birth_date": "",
            "github_url": "",
            "homepage_url": "",
            "blog_url": "",
            "twitter_url": "",
            "linkedin_url": "",
            "company": "",
            "location": "",
            # Work experience formset
            "work_experiences-TOTAL_FORMS": "0",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            # Education formset
            "educations-TOTAL_FORMS": "0",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
            # Shipping address formset - edit existing
            "shipping_addresses-TOTAL_FORMS": "1",
            "shipping_addresses-INITIAL_FORMS": "1",
            "shipping_addresses-MIN_NUM_FORMS": "0",
            "shipping_addresses-MAX_NUM_FORMS": "1000",
            "shipping_addresses-0-id": str(address.id),
            "shipping_addresses-0-receiver_name": "王五",
            "shipping_addresses-0-phone": "13700137000",
            "shipping_addresses-0-province": "广东",
            "shipping_addresses-0-city": "深圳市",
            "shipping_addresses-0-district": "南山区",
            "shipping_addresses-0-address": "新地址456号",
            "shipping_addresses-0-is_default": "on",
        }

        response = self.client.post(self.url, data)

        assert response.status_code == 302

        # Address should be updated
        address.refresh_from_db()
        assert address.receiver_name == "王五"
        assert address.province == "广东"
        assert address.address == "新地址456号"

    def test_delete_shipping_address_via_profile_edit(self):
        """Test deleting a shipping address through profile edit."""
        self.client.force_login(self.user)

        # Create an address
        address = ShippingAddress.objects.create(
            user=self.user,
            receiver_name="张三",
            phone="13800138000",
            province="北京",
            city="北京市",
            district="朝阳区",
            address="地址1",
            is_default=True,
        )

        data = {
            # Profile form data
            "bio": "",
            "birth_date": "",
            "github_url": "",
            "homepage_url": "",
            "blog_url": "",
            "twitter_url": "",
            "linkedin_url": "",
            "company": "",
            "location": "",
            # Work experience formset
            "work_experiences-TOTAL_FORMS": "0",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            # Education formset
            "educations-TOTAL_FORMS": "0",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
            # Shipping address formset - mark for deletion
            "shipping_addresses-TOTAL_FORMS": "1",
            "shipping_addresses-INITIAL_FORMS": "1",
            "shipping_addresses-MIN_NUM_FORMS": "0",
            "shipping_addresses-MAX_NUM_FORMS": "1000",
            "shipping_addresses-0-id": str(address.id),
            "shipping_addresses-0-receiver_name": "张三",
            "shipping_addresses-0-phone": "13800138000",
            "shipping_addresses-0-province": "北京",
            "shipping_addresses-0-city": "北京市",
            "shipping_addresses-0-district": "朝阳区",
            "shipping_addresses-0-address": "地址1",
            "shipping_addresses-0-is_default": "on",
            "shipping_addresses-0-DELETE": "on",
        }

        response = self.client.post(self.url, data)

        assert response.status_code == 302

        # Address should be deleted
        assert not ShippingAddress.objects.filter(id=address.id).exists()

    def test_add_multiple_addresses_via_profile_edit(self):
        """Test adding multiple shipping addresses at once."""
        self.client.force_login(self.user)

        data = {
            # Profile form data
            "bio": "",
            "birth_date": "",
            "github_url": "",
            "homepage_url": "",
            "blog_url": "",
            "twitter_url": "",
            "linkedin_url": "",
            "company": "",
            "location": "",
            # Work experience formset
            "work_experiences-TOTAL_FORMS": "0",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            # Education formset
            "educations-TOTAL_FORMS": "0",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
            # Shipping address formset - add two addresses
            "shipping_addresses-TOTAL_FORMS": "2",
            "shipping_addresses-INITIAL_FORMS": "0",
            "shipping_addresses-MIN_NUM_FORMS": "0",
            "shipping_addresses-MAX_NUM_FORMS": "1000",
            # First address (default)
            "shipping_addresses-0-receiver_name": "张三",
            "shipping_addresses-0-phone": "13800138000",
            "shipping_addresses-0-province": "北京",
            "shipping_addresses-0-city": "北京市",
            "shipping_addresses-0-district": "朝阳区",
            "shipping_addresses-0-address": "地址1",
            "shipping_addresses-0-is_default": "on",
            # Second address (not default)
            "shipping_addresses-1-receiver_name": "李四",
            "shipping_addresses-1-phone": "13900139000",
            "shipping_addresses-1-province": "上海",
            "shipping_addresses-1-city": "上海市",
            "shipping_addresses-1-district": "浦东新区",
            "shipping_addresses-1-address": "地址2",
            "shipping_addresses-1-is_default": "",
        }

        response = self.client.post(self.url, data)

        assert response.status_code == 302

        # Both addresses should be created
        assert ShippingAddress.objects.filter(user=self.user).count() == 2

        # Check default address
        default_addr = ShippingAddress.objects.get(user=self.user, is_default=True)
        assert default_addr.receiver_name == "张三"

    def test_profile_edit_with_no_address_changes(self):
        """Test that submitting without address changes doesn't trigger update."""
        self.client.force_login(self.user)

        data = {
            # Profile form data
            "bio": "",
            "birth_date": "",
            "github_url": "",
            "homepage_url": "",
            "blog_url": "",
            "twitter_url": "",
            "linkedin_url": "",
            "company": "",
            "location": "",
            # Work experience formset
            "work_experiences-TOTAL_FORMS": "0",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            # Education formset
            "educations-TOTAL_FORMS": "0",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
            # Shipping address formset - no addresses
            "shipping_addresses-TOTAL_FORMS": "0",
            "shipping_addresses-INITIAL_FORMS": "0",
            "shipping_addresses-MIN_NUM_FORMS": "0",
            "shipping_addresses-MAX_NUM_FORMS": "1000",
        }

        response = self.client.post(self.url, data)

        assert response.status_code == 302
        assert ShippingAddress.objects.filter(user=self.user).count() == 0
