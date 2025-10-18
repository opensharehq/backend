"""Tests for shop admin configuration."""

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import ShippingAddress
from points.models import Tag
from points.services import grant_points
from shop.admin import RedemptionAdmin, ShopItemAdmin
from shop.models import Redemption, ShopItem
from shop.services import redeem_item


class MockRequest:
    """Mock request object for admin tests."""

    pass


class ShopItemAdminTests(TestCase):
    """Test cases for ShopItemAdmin."""

    def setUp(self):
        """Set up test fixtures."""
        self.site = AdminSite()
        self.admin = ShopItemAdmin(ShopItem, self.site)

    def test_requires_shipping_in_list_display(self):
        """Test that requires_shipping is shown in list display."""
        assert "requires_shipping" in self.admin.list_display

    def test_requires_shipping_in_list_filter(self):
        """Test that requires_shipping is available as a filter."""
        assert "requires_shipping" in self.admin.list_filter

    def test_requires_shipping_in_fieldsets(self):
        """Test that requires_shipping is in fieldsets."""
        # Get all fields from all fieldsets
        all_fields = []
        for _name, options in self.admin.fieldsets:
            all_fields.extend(options["fields"])

        assert "requires_shipping" in all_fields

    def test_stock_display_with_shipping(self):
        """Test stock display method works with requires_shipping field."""
        item = ShopItem.objects.create(
            name="Test Item",
            description="Test",
            cost=100,
            stock=15,
            requires_shipping=True,
        )

        stock_display = self.admin.stock_display(item)
        # Stock >= 10 returns plain number
        assert stock_display == 15


class RedemptionAdminTests(TestCase):
    """Test cases for RedemptionAdmin."""

    def setUp(self):
        """Set up test fixtures."""
        self.site = AdminSite()
        self.admin = RedemptionAdmin(Redemption, self.site)
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        self.default_tag = Tag.objects.create(name="default", is_default=True)

    def test_has_shipping_address_in_list_display(self):
        """Test that has_shipping_address is shown in list display."""
        assert "has_shipping_address" in self.admin.list_display

    def test_shipping_address_in_readonly_fields(self):
        """Test that shipping_address_display is in readonly fields."""
        assert "shipping_address_display" in self.admin.readonly_fields

    def test_shipping_address_in_search_fields(self):
        """Test that shipping address fields are searchable."""
        assert "shipping_address__receiver_name" in self.admin.search_fields
        assert "shipping_address__phone" in self.admin.search_fields

    def test_has_shipping_address_display_true(self):
        """Test has_shipping_address display returns True when address exists."""
        # Create item and address
        item = ShopItem.objects.create(
            name="Physical Item",
            description="Test",
            cost=100,
            requires_shipping=True,
        )
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

        # Grant points and redeem
        grant_points(
            user_profile=self.user,
            points=200,
            description="Test",
            tag_names=["default"],
        )
        redemption = redeem_item(
            user_profile=self.user,
            item_id=item.id,
            shipping_address_id=address.id,
        )

        # Test display method
        result = self.admin.has_shipping_address(redemption)
        assert result is True

    def test_has_shipping_address_display_false(self):
        """Test has_shipping_address display returns False when no address."""
        # Create virtual item (no shipping)
        item = ShopItem.objects.create(
            name="Virtual Item",
            description="Test",
            cost=100,
            requires_shipping=False,
        )

        # Grant points and redeem
        grant_points(
            user_profile=self.user,
            points=200,
            description="Test",
            tag_names=["default"],
        )
        redemption = redeem_item(user_profile=self.user, item_id=item.id)

        # Test display method
        result = self.admin.has_shipping_address(redemption)
        assert result is False

    def test_shipping_address_display_with_address(self):
        """Test shipping_address_display shows address details."""
        # Create item and address
        item = ShopItem.objects.create(
            name="Physical Item",
            description="Test",
            cost=100,
            requires_shipping=True,
        )
        address = ShippingAddress.objects.create(
            user=self.user,
            receiver_name="李四",
            phone="13900139000",
            province="上海",
            city="上海市",
            district="浦东新区",
            address="陆家嘴环路1000号",
            is_default=True,
        )

        # Grant points and redeem
        grant_points(
            user_profile=self.user,
            points=200,
            description="Test",
            tag_names=["default"],
        )
        redemption = redeem_item(
            user_profile=self.user,
            item_id=item.id,
            shipping_address_id=address.id,
        )

        # Test display method
        result = self.admin.shipping_address_display(redemption)

        # Check that result contains address information
        assert "李四" in result
        assert "13900139000" in result
        assert "上海" in result
        assert "浦东新区" in result
        assert "陆家嘴环路1000号" in result

    def test_shipping_address_display_without_address(self):
        """Test shipping_address_display shows message when no address."""
        # Create virtual item
        item = ShopItem.objects.create(
            name="Virtual Item",
            description="Test",
            cost=100,
            requires_shipping=False,
        )

        # Grant points and redeem
        grant_points(
            user_profile=self.user,
            points=200,
            description="Test",
            tag_names=["default"],
        )
        redemption = redeem_item(user_profile=self.user, item_id=item.id)

        # Test display method
        result = self.admin.shipping_address_display(redemption)

        # Should show "无需发货"
        assert "无需发货" in result
