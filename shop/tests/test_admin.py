"""Tests for shop admin configuration."""

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from accounts.models import ShippingAddress
from points import services as points_services
from points.models import PointType
from shop.admin import RedemptionAdmin, RedemptionInline, ShopItemAdmin
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
        self.factory = RequestFactory()
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

    def test_stock_display_handles_infinite_and_low_stock(self):
        """Test colorized stock display branches."""
        unlimited = ShopItem.objects.create(
            name="Unlimited",
            description="Unlimited item",
            cost=100,
            stock=None,
        )
        low_stock = ShopItem.objects.create(
            name="Low",
            description="Low stock item",
            cost=100,
            stock=3,
        )
        sold_out = ShopItem.objects.create(
            name="Sold out",
            description="Sold out item",
            cost=100,
            stock=0,
        )

        assert "无限" in str(self.admin.stock_display(unlimited))
        assert "orange" in str(self.admin.stock_display(low_stock))
        assert "售罄" in str(self.admin.stock_display(sold_out))

    def test_has_image_and_redemption_count_helpers(self):
        """Test additional ShopItem admin helpers."""
        item = ShopItem.objects.create(
            name="With Image",
            description="Test",
            cost=100,
            stock=5,
        )

        assert self.admin.has_image(item) is False
        assert self.admin.redemption_count(item) == 0


class RedemptionAdminTests(TestCase):
    """Test cases for RedemptionAdmin."""

    def setUp(self):
        """Set up test fixtures."""
        self.site = AdminSite()
        self.factory = RequestFactory()
        self.admin = RedemptionAdmin(Redemption, self.site)
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        # Grant gift points for redemption tests
        points_services.grant_points(self.user, 10000, PointType.GIFT, "Test points")

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

        # Redeem item
        redemption = redeem_item(
            user=self.user,
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

        # Redeem item
        redemption = redeem_item(user=self.user, item_id=item.id)

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

        # Redeem item
        redemption = redeem_item(
            user=self.user,
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

        # Redeem item
        redemption = redeem_item(user=self.user, item_id=item.id)

        # Test display method
        result = self.admin.shipping_address_display(redemption)

        # Should show "无需发货"
        assert "无需发货" in result

    def test_status_display_and_actions(self):
        """Test redemption status formatting and batch actions."""
        request = self.factory.post("/admin/shop/redemption/")
        request.user = get_user_model().objects.create_superuser(
            username="shop-admin",
            email="shop-admin@example.com",
            password="password123",
        )
        self.admin.message_user = MockRequest()
        self.admin.message_user = lambda _request, _message: None

        item = ShopItem.objects.create(
            name="Action Item",
            description="Action",
            cost=100,
            requires_shipping=False,
        )
        pending_redemption = Redemption.objects.create(
            user_profile=self.user,
            item=item,
            points_cost_at_redemption=item.cost,
        )
        redemption = redeem_item(user=self.user, item_id=item.id)

        assert "orange" in str(self.admin.status_display(pending_redemption))

        self.admin.mark_as_completed(
            request, Redemption.objects.filter(pk=redemption.pk)
        )
        redemption.refresh_from_db()
        assert redemption.status == Redemption.StatusChoices.COMPLETED
        assert "green" in str(self.admin.status_display(redemption))

        self.admin.mark_as_cancelled(
            request, Redemption.objects.filter(pk=redemption.pk)
        )
        redemption.refresh_from_db()
        assert redemption.status == Redemption.StatusChoices.CANCELLED
        assert "red" in str(self.admin.status_display(redemption))

    def test_redemption_inline_disables_add_permission(self):
        """Redemptions should remain read-only inside the ShopItem admin."""
        inline = RedemptionInline(ShopItem, self.site)
        request = self.factory.get("/admin/shop/shopitem/")
        request.user = self.user

        assert inline.has_add_permission(request) is False
