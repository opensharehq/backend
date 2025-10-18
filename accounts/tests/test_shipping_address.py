"""Tests for shipping address views and forms."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.forms import ShippingAddressForm
from accounts.models import ShippingAddress


class ShippingAddressFormTests(TestCase):
    """Test cases for ShippingAddressForm."""

    def test_form_valid_data(self):
        """Test form with valid data."""
        form_data = {
            "receiver_name": "张三",
            "phone": "13800138000",
            "province": "北京",
            "city": "北京市",
            "district": "朝阳区",
            "address": "某某街道123号",
            "is_default": True,
        }
        form = ShippingAddressForm(data=form_data)
        assert form.is_valid()

    def test_form_missing_required_fields(self):
        """Test form with missing required fields."""
        form_data = {
            "receiver_name": "张三",
            # Missing other required fields
        }
        form = ShippingAddressForm(data=form_data)
        assert not form.is_valid()
        assert "phone" in form.errors
        assert "province" in form.errors
        assert "city" in form.errors


class ShippingAddressListViewTests(TestCase):
    """Test cases for shipping address list view."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        self.url = reverse("accounts:shipping_address_list")

    def test_login_required(self):
        """Test that login is required to access address list."""
        response = self.client.get(self.url)
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_list_user_addresses(self):
        """Test that user can see their addresses."""
        self.client.force_login(self.user)

        # Create addresses
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

        response = self.client.get(self.url)
        assert response.status_code == 200
        assert len(response.context["addresses"]) == 1


class ShippingAddressCreateViewTests(TestCase):
    """Test cases for shipping address create view."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        self.url = reverse("accounts:shipping_address_create")

    def test_login_required(self):
        """Test that login is required to create address."""
        response = self.client.get(self.url)
        assert response.status_code == 302

    def test_create_address_get(self):
        """Test GET request shows form."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert "form" in response.context

    def test_create_address_post_valid(self):
        """Test POST request with valid data creates address."""
        self.client.force_login(self.user)

        data = {
            "receiver_name": "张三",
            "phone": "13800138000",
            "province": "北京",
            "city": "北京市",
            "district": "朝阳区",
            "address": "某某街道123号",
            "is_default": True,
        }

        response = self.client.post(self.url, data)

        # Should redirect to address list
        assert response.status_code == 302
        assert response.url == reverse("accounts:shipping_address_list")

        # Address should be created
        assert ShippingAddress.objects.filter(user=self.user).count() == 1
        address = ShippingAddress.objects.get(user=self.user)
        assert address.receiver_name == "张三"


class ShippingAddressEditViewTests(TestCase):
    """Test cases for shipping address edit view."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        self.address = ShippingAddress.objects.create(
            user=self.user,
            receiver_name="张三",
            phone="13800138000",
            province="北京",
            city="北京市",
            district="朝阳区",
            address="旧地址",
            is_default=False,
        )
        self.url = reverse("accounts:shipping_address_edit", args=[self.address.id])

    def test_login_required(self):
        """Test that login is required to edit address."""
        response = self.client.get(self.url)
        assert response.status_code == 302

    def test_edit_own_address(self):
        """Test user can edit their own address."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_cannot_edit_other_users_address(self):
        """Test user cannot edit other user's address."""
        other_user = get_user_model().objects.create_user(
            username="other",
            email="other@example.com",
            password="password123",
        )
        self.client.force_login(other_user)
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_update_address(self):
        """Test updating address data."""
        self.client.force_login(self.user)

        data = {
            "receiver_name": "李四",
            "phone": "13900139000",
            "province": "上海",
            "city": "上海市",
            "district": "浦东新区",
            "address": "新地址",
            "is_default": True,
        }

        response = self.client.post(self.url, data)
        assert response.status_code == 302

        self.address.refresh_from_db()
        assert self.address.receiver_name == "李四"
        assert self.address.address == "新地址"
        assert self.address.is_default is True


class ShippingAddressDeleteViewTests(TestCase):
    """Test cases for shipping address delete view."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        self.address = ShippingAddress.objects.create(
            user=self.user,
            receiver_name="张三",
            phone="13800138000",
            province="北京",
            city="北京市",
            district="朝阳区",
            address="地址1",
            is_default=False,
        )
        self.url = reverse("accounts:shipping_address_delete", args=[self.address.id])

    def test_login_required(self):
        """Test that login is required to delete address."""
        response = self.client.get(self.url)
        assert response.status_code == 302

    def test_delete_confirmation_page(self):
        """Test GET request shows delete confirmation page."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert "address" in response.context

    def test_delete_address_post(self):
        """Test POST request deletes address."""
        self.client.force_login(self.user)
        response = self.client.post(self.url)

        assert response.status_code == 302
        assert not ShippingAddress.objects.filter(id=self.address.id).exists()

    def test_cannot_delete_other_users_address(self):
        """Test user cannot delete other user's address."""
        other_user = get_user_model().objects.create_user(
            username="other",
            email="other@example.com",
            password="password123",
        )
        self.client.force_login(other_user)
        response = self.client.post(self.url)
        assert response.status_code == 404
        # Address should still exist
        assert ShippingAddress.objects.filter(id=self.address.id).exists()


class ShippingAddressSetDefaultViewTests(TestCase):
    """Test cases for shipping address set default view."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        self.address1 = ShippingAddress.objects.create(
            user=self.user,
            receiver_name="张三",
            phone="13800138000",
            province="北京",
            city="北京市",
            district="朝阳区",
            address="地址1",
            is_default=True,
        )
        self.address2 = ShippingAddress.objects.create(
            user=self.user,
            receiver_name="李四",
            phone="13900139000",
            province="上海",
            city="上海市",
            district="浦东新区",
            address="地址2",
            is_default=False,
        )
        self.url = reverse(
            "accounts:shipping_address_set_default",
            args=[self.address2.id],
        )

    def test_login_required(self):
        """Test that login is required to set default address."""
        response = self.client.post(self.url)
        assert response.status_code == 302

    def test_set_default_address(self):
        """Test setting an address as default."""
        self.client.force_login(self.user)
        response = self.client.post(self.url)

        assert response.status_code == 302

        # Refresh from database
        self.address1.refresh_from_db()
        self.address2.refresh_from_db()

        # address2 should now be default
        assert self.address2.is_default is True
        # address1 should no longer be default
        assert self.address1.is_default is False


class ShippingAddressCreateGuideViewTests(TestCase):
    """Test cases for shipping address create guide view."""

    def setUp(self):
        """Set up test fixtures."""
        from shop.models import ShopItem

        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        self.item = ShopItem.objects.create(
            name="测试商品",
            description="测试描述",
            cost=100,
            requires_shipping=True,
        )
        self.url = reverse(
            "accounts:shipping_address_create_guide",
            args=[self.item.id],
        )

    def test_login_required(self):
        """Test that login is required to access guide."""
        response = self.client.get(self.url)
        assert response.status_code == 302

    def test_guide_shows_form_with_item(self):
        """Test guide page shows form and item info."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)

        assert response.status_code == 200
        assert "form" in response.context
        assert "item" in response.context
        assert response.context["item"] == self.item

    def test_create_address_and_redirect_to_redeem(self):
        """Test creating address redirects back to redemption page."""
        self.client.force_login(self.user)

        data = {
            "receiver_name": "张三",
            "phone": "13800138000",
            "province": "北京",
            "city": "北京市",
            "district": "朝阳区",
            "address": "某某街道123号",
            "is_default": True,
        }

        response = self.client.post(self.url, data)

        # Should redirect to redemption confirm page
        assert response.status_code == 302
        assert response.url == reverse("accounts:redeem_confirm", args=[self.item.id])

        # Address should be created
        assert ShippingAddress.objects.filter(user=self.user).count() == 1

    def test_first_address_defaults_to_default(self):
        """Test that form suggests is_default=True for first address."""
        self.client.force_login(self.user)
        response = self.client.get(self.url)

        form = response.context["form"]
        # Initial value for is_default should be True
        assert form.initial.get("is_default") is True
