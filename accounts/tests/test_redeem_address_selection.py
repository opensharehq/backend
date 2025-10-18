"""Tests for shipping address selection in redemption confirmation view."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import ShippingAddress
from points.models import Tag
from points.services import grant_points
from shop.models import ShopItem


class RedeemConfirmAddressSelectionTests(TestCase):
    """Test cases for address selection on redemption confirmation page."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        self.default_tag = Tag.objects.create(name="default", is_default=True)
        self.client.login(username="testuser", password="password123")

    def test_shipping_item_shows_address_selection(self):
        """Test that shipping items show address selection in confirmation page."""
        # Create shipping item
        item = ShopItem.objects.create(
            name="Physical Item",
            description="Test",
            cost=100,
            requires_shipping=True,
        )

        # Create addresses
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
            user=self.user,
            receiver_name="李四",
            phone="13900139000",
            province="上海",
            city="上海市",
            district="浦东新区",
            address="地址2",
            is_default=False,
        )

        # Grant points
        grant_points(
            user_profile=self.user,
            points=200,
            description="Test",
            tag_names=["default"],
        )

        # Get confirmation page
        response = self.client.get(reverse("accounts:redeem_confirm", args=[item.id]))

        # Check response
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "收货地址")
        self.assertContains(response, address1.receiver_name)
        self.assertContains(response, address2.receiver_name)
        self.assertContains(response, address1.phone)
        self.assertContains(response, address2.phone)

    def test_default_address_is_preselected(self):
        """Test that default address is checked by default."""
        # Create shipping item
        item = ShopItem.objects.create(
            name="Physical Item",
            description="Test",
            cost=100,
            requires_shipping=True,
        )

        # Create addresses
        address1 = ShippingAddress.objects.create(  # noqa: F841
            user=self.user,
            receiver_name="张三",
            phone="13800138000",
            province="北京",
            city="北京市",
            district="朝阳区",
            address="地址1",
            is_default=False,
        )
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

        # Grant points
        grant_points(
            user_profile=self.user,
            points=200,
            description="Test",
            tag_names=["default"],
        )

        # Get confirmation page
        response = self.client.get(reverse("accounts:redeem_confirm", args=[item.id]))

        # Check response
        self.assertEqual(response.status_code, 200)

        # Check that default address has checked attribute
        html = response.content.decode()
        self.assertIn(f'id="address_{address2.id}"', html)
        self.assertIn(f'value="{address2.id}"', html)

        # Verify default badge is shown for address2
        self.assertContains(response, "默认")

    def test_virtual_item_hides_address_selection(self):
        """Test that virtual items don't show address selection."""
        # Create virtual item
        item = ShopItem.objects.create(
            name="Virtual Item",
            description="Test",
            cost=100,
            requires_shipping=False,
        )

        # Create address (shouldn't matter for virtual items)
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

        # Grant points
        grant_points(
            user_profile=self.user,
            points=200,
            description="Test",
            tag_names=["default"],
        )

        # Get confirmation page
        response = self.client.get(reverse("accounts:redeem_confirm", args=[item.id]))

        # Check response
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "收货地址")
        self.assertNotContains(response, "张三")

    def test_manage_address_link_shown(self):
        """Test that manage address link is shown for shipping items."""
        # Create shipping item
        item = ShopItem.objects.create(
            name="Physical Item",
            description="Test",
            cost=100,
            requires_shipping=True,
        )

        # Create address
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

        # Grant points
        grant_points(
            user_profile=self.user,
            points=200,
            description="Test",
            tag_names=["default"],
        )

        # Get confirmation page
        response = self.client.get(reverse("accounts:redeem_confirm", args=[item.id]))

        # Check response
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "管理收货地址")
        self.assertContains(
            response, reverse("accounts:shipping_address_list"), html=False
        )

    def test_redemption_with_selected_address(self):
        """Test successful redemption with selected shipping address."""
        # Create shipping item
        item = ShopItem.objects.create(
            name="Physical Item",
            description="Test",
            cost=100,
            requires_shipping=True,
        )

        # Create addresses
        address1 = ShippingAddress.objects.create(  # noqa: F841
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
            user=self.user,
            receiver_name="李四",
            phone="13900139000",
            province="上海",
            city="上海市",
            district="浦东新区",
            address="地址2",
            is_default=False,
        )

        # Grant points
        grant_points(
            user_profile=self.user,
            points=200,
            description="Test",
            tag_names=["default"],
        )

        # Post redemption with non-default address
        response = self.client.post(
            reverse("accounts:redeem_confirm", args=[item.id]),
            {"shipping_address": address2.id},
        )

        # Check redirect to redemption list
        self.assertRedirects(response, reverse("accounts:redemption_list"))

        # Verify redemption was created with correct address
        redemption = self.user.redemptions.first()
        self.assertIsNotNone(redemption)
        self.assertEqual(redemption.shipping_address_id, address2.id)

    def test_redemption_fails_without_address_selection(self):
        """Test that redemption fails if no address is selected."""
        # Create shipping item
        item = ShopItem.objects.create(
            name="Physical Item",
            description="Test",
            cost=100,
            requires_shipping=True,
        )

        # Create address
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

        # Grant points
        grant_points(
            user_profile=self.user,
            points=200,
            description="Test",
            tag_names=["default"],
        )

        # Post redemption without address
        response = self.client.post(
            reverse("accounts:redeem_confirm", args=[item.id]),
            {},  # No shipping_address
        )

        # Check redirect back to confirmation page
        self.assertRedirects(
            response, reverse("accounts:redeem_confirm", args=[item.id])
        )

        # Verify no redemption was created
        self.assertEqual(self.user.redemptions.count(), 0)

    def test_multiple_addresses_all_shown(self):
        """Test that all user addresses are shown in selection."""
        # Create shipping item
        item = ShopItem.objects.create(
            name="Physical Item",
            description="Test",
            cost=100,
            requires_shipping=True,
        )

        # Create 3 addresses
        addresses = []
        for i in range(3):
            address = ShippingAddress.objects.create(
                user=self.user,
                receiver_name=f"收件人{i + 1}",
                phone=f"138{i:08d}",
                province="测试省",
                city="测试市",
                district="测试区",
                address=f"测试地址{i + 1}",
                is_default=(i == 0),
            )
            addresses.append(address)

        # Grant points
        grant_points(
            user_profile=self.user,
            points=200,
            description="Test",
            tag_names=["default"],
        )

        # Get confirmation page
        response = self.client.get(reverse("accounts:redeem_confirm", args=[item.id]))

        # Check all addresses are shown
        self.assertEqual(response.status_code, 200)
        for address in addresses:
            self.assertContains(response, address.receiver_name)
            self.assertContains(response, address.phone)
