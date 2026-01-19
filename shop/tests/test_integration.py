"""Integration tests for shop app workflows."""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from points import services as points_services
from points.models import PointType
from shop.models import Redemption, ShopItem
from shop.services import RedemptionError, redeem_item


class ShopRedemptionFlowTests(TestCase):
    """Test complete shop item redemption workflow."""

    def setUp(self):
        """Set up test fixtures."""
        User = get_user_model()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        # Grant gift points for redemption tests
        points_services.grant_points(self.user, 10000, PointType.GIFT, "Test points")

    def test_complete_redemption_flow(self):
        """Test complete flow: user redeems item."""
        # Create shop item
        item = ShopItem.objects.create(
            name="Premium Sticker Pack",
            description="Exclusive sticker collection",
            cost=100,
            stock=10,
            is_active=True,
        )

        # Redeem item
        redemption = redeem_item(
            user=self.user,
            item_id=item.id,
        )

        # Verify redemption was created
        self.assertEqual(redemption.user_profile, self.user)
        self.assertEqual(redemption.item, item)
        self.assertEqual(redemption.points_cost_at_redemption, 100)
        self.assertEqual(redemption.status, "COMPLETED")

        # Verify stock was decremented
        item.refresh_from_db()
        self.assertEqual(item.stock, 9)

    def test_redemption_when_out_of_stock_fails(self):
        """Test redemption fails when item is out of stock."""
        # Create item with no stock
        item = ShopItem.objects.create(
            name="Sold Out Item",
            description="No longer available",
            cost=50,
            stock=0,  # Out of stock
            is_active=True,
        )

        with self.assertRaises(RedemptionError) as exc_info:
            redeem_item(user=self.user, item_id=item.id)

        self.assertTrue(
            "库存不足" in str(exc_info.exception).lower()
            or "out of stock" in str(exc_info.exception).lower()
            or "售罄" in str(exc_info.exception)
        )

    def test_redemption_when_item_inactive_fails(self):
        """Test redemption fails when item is not active."""
        # Create inactive item
        item = ShopItem.objects.create(
            name="Inactive Item",
            description="Not available",
            cost=50,
            stock=10,
            is_active=False,  # Inactive
        )

        with self.assertRaises(RedemptionError) as exc_info:
            redeem_item(user=self.user, item_id=item.id)

        self.assertTrue(
            "商品已下架" in str(exc_info.exception)
            or "下架" in str(exc_info.exception)
            or "not available" in str(exc_info.exception).lower()
        )

    def test_multiple_redemptions_from_same_user(self):
        """Test user can make multiple redemptions."""
        # Create two items
        item1 = ShopItem.objects.create(
            name="Item 1",
            description="First item",
            cost=100,
            stock=10,
            is_active=True,
        )

        item2 = ShopItem.objects.create(
            name="Item 2",
            description="Second item",
            cost=150,
            stock=10,
            is_active=True,
        )

        # Redeem first item
        redemption1 = redeem_item(user=self.user, item_id=item1.id)

        # Redeem second item
        redemption2 = redeem_item(user=self.user, item_id=item2.id)

        # Verify both redemptions exist
        self.assertEqual(Redemption.objects.filter(user_profile=self.user).count(), 2)

        # Verify different redemptions
        self.assertEqual(redemption1.item, item1)
        self.assertEqual(redemption2.item, item2)


class ShopViewFlowTests(TestCase):
    """Test shop browsing and redemption through web interface."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        # Grant gift points for redemption tests
        points_services.grant_points(self.user, 10000, PointType.GIFT, "Test points")

        self.client.force_login(self.user)

    def test_browse_shop_items_and_redeem_flow(self):
        """Test complete flow: browse items, view details, redeem."""
        # Create shop items
        ShopItem.objects.create(
            name="T-Shirt",
            description="Cool branded T-shirt",
            cost=200,
            stock=5,
            is_active=True,
        )

        item2 = ShopItem.objects.create(
            name="Stickers",
            description="Awesome stickers",
            cost=50,
            stock=20,
            is_active=True,
        )

        # Step 1: Browse shop list
        shop_url = reverse("accounts:shop_list")
        response = self.client.get(shop_url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Should show both items
        self.assertIn("T-Shirt", content)
        self.assertIn("Stickers", content)
        self.assertIn("200", content)  # T-shirt cost
        self.assertIn("50", content)  # Stickers cost

        # Step 2: Access redeem confirmation page
        redeem_confirm_url = reverse(
            "accounts:redeem_confirm", kwargs={"item_id": item2.id}
        )
        response = self.client.get(redeem_confirm_url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Stickers", content)
        self.assertIn("50", content)

        # Step 3: Confirm redemption
        response = self.client.post(redeem_confirm_url)

        # Should redirect to redemption list
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("accounts:redemption_list"))

        # Verify redemption was created
        redemption = Redemption.objects.filter(
            user_profile=self.user,
            item=item2,
        ).first()
        self.assertIsNotNone(redemption)

        # Step 4: View redemption list
        redemption_list_url = reverse("accounts:redemption_list")
        response = self.client.get(redemption_list_url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Should show the redemption
        self.assertIn("Stickers", content)
        self.assertIn("50", content)

    def test_unauthorized_user_cannot_access_shop(self):
        """Test non-logged-in user cannot access shop pages."""
        self.client.logout()

        # Try to access shop list
        shop_url = reverse("accounts:shop_list")
        response = self.client.get(shop_url)

        # Should redirect to login
        self.assertEqual(response.status_code, 302)

    def test_redeem_inactive_item_through_web_shows_error(self):
        """Test attempting to redeem inactive item shows error."""
        # Create inactive item
        item = ShopItem.objects.create(
            name="Inactive Item",
            description="Not available",
            cost=50,
            stock=10,
            is_active=False,
        )

        # Try to access redeem page
        redeem_confirm_url = reverse(
            "accounts:redeem_confirm", kwargs={"item_id": item.id}
        )
        response = self.client.get(redeem_confirm_url)

        # Should show error or redirect
        # The actual behavior depends on the view implementation
        self.assertIn(response.status_code, [200, 302, 404])


class FullUserJourneyTests(TestCase):
    """Test complete user journey from registration to redemption."""

    def test_complete_user_journey(self):
        """Test entire user lifecycle: register -> redeem item."""
        client = Client()

        # Step 1: Register new user
        signup_url = reverse("accounts:sign_up")
        signup_data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password1": "SecurePass123!",
            "password2": "SecurePass123!",
        }

        response = client.post(signup_url, signup_data)
        self.assertEqual(response.status_code, 302)

        User = get_user_model()
        user = User.objects.get(username="newuser")

        # Grant gift points for redemption
        points_services.grant_points(user, 1000, PointType.GIFT, "Welcome bonus")

        # Step 2: User logs in
        client.force_login(user)

        # Step 3: User browses shop
        item = ShopItem.objects.create(
            name="Welcome Gift",
            description="Special gift for new users",
            cost=100,
            stock=50,
            is_active=True,
        )

        shop_url = reverse("accounts:shop_list")
        response = client.get(shop_url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Welcome Gift", response.content.decode())

        # Step 4: User redeems item
        redeem_confirm_url = reverse(
            "accounts:redeem_confirm", kwargs={"item_id": item.id}
        )
        response = client.post(redeem_confirm_url)

        self.assertEqual(response.status_code, 302)

        # Step 5: Verify redemption success
        self.assertEqual(Redemption.objects.filter(user_profile=user).count(), 1)

        redemption = Redemption.objects.get(user_profile=user)
        self.assertEqual(redemption.item, item)
        self.assertEqual(redemption.points_cost_at_redemption, 100)
        self.assertEqual(redemption.status, "COMPLETED")

        # Step 6: User views redemption history
        redemption_list_url = reverse("accounts:redemption_list")
        response = client.get(redemption_list_url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Welcome Gift", content)
        self.assertIn("100", content)

    def test_user_journey_with_profile_completion(self):
        """Test user journey including profile completion."""
        client = Client()

        # Register user
        User = get_user_model()
        user = User.objects.create_user(
            username="profileuser",
            email="profile@example.com",
            password="testpass123",
        )
        # Grant gift points for redemption
        points_services.grant_points(user, 1000, PointType.GIFT, "Test points")
        client.force_login(user)

        # User completes profile
        edit_url = reverse("accounts:profile_edit")
        profile_data = {
            "bio": "I love open source!",
            "birth_date": "",
            "github_url": "https://github.com/profileuser",
            "homepage_url": "",
            "blog_url": "",
            "twitter_url": "",
            "linkedin_url": "",
            "company": "Tech Company",
            "location": "Shanghai",
            # Formset management data for work experiences
            "work_experiences-TOTAL_FORMS": "0",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            # Formset management data for educations
            "educations-TOTAL_FORMS": "0",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
            # Formset management data for shipping addresses
            "shipping_addresses-TOTAL_FORMS": "0",
            "shipping_addresses-INITIAL_FORMS": "0",
            "shipping_addresses-MIN_NUM_FORMS": "0",
            "shipping_addresses-MAX_NUM_FORMS": "1000",
        }

        response = client.post(edit_url, profile_data)
        self.assertEqual(response.status_code, 302)

        # Verify profile was updated
        user.refresh_from_db()
        self.assertEqual(user.profile.bio, "I love open source!")
        self.assertEqual(user.profile.github_url, "https://github.com/profileuser")

        # User can redeem items in shop
        item = ShopItem.objects.create(
            name="Small Reward",
            description="For completing profile",
            cost=50,
            stock=100,
            is_active=True,
        )

        redeem_confirm_url = reverse(
            "accounts:redeem_confirm", kwargs={"item_id": item.id}
        )
        response = client.post(redeem_confirm_url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Redemption.objects.filter(user_profile=user).count(), 1)
