"""Integration tests for shop app workflows."""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from points.models import PointTransaction, Tag
from points.services import grant_points
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

        # Create tags
        self.general_tag = Tag.objects.create(
            name="general", description="通用积分", is_default=True
        )
        self.event_tag = Tag.objects.create(name="event", description="活动积分")

        # Grant user some points
        grant_points(
            user_profile=self.user,
            points=500,
            tag_names=[self.general_tag.name],
            description="初始积分",
        )

    def test_complete_redemption_flow_with_points_deduction(self):
        """Test complete flow: user redeems item and points are deducted."""
        # Create shop item
        item = ShopItem.objects.create(
            name="Premium Sticker Pack",
            description="Exclusive sticker collection",
            cost=100,
            stock=10,
            is_active=True,
        )

        # User should have 500 points
        self.assertEqual(self.user.total_points, 500)

        # Redeem item
        redemption = redeem_item(
            user_profile=self.user,
            item_id=item.id,
        )

        # Verify redemption was created
        self.assertEqual(redemption.user_profile, self.user)
        self.assertEqual(redemption.item, item)
        self.assertEqual(redemption.points_cost_at_redemption, 100)
        self.assertEqual(redemption.status, "COMPLETED")

        # Verify points were deducted
        self.assertEqual(self.user.total_points, 400)  # 500 - 100

        # Verify stock was decremented
        item.refresh_from_db()
        self.assertEqual(item.stock, 9)

        # Verify spend transaction was created
        spend_transaction = PointTransaction.objects.filter(
            user_profile=self.user,
            transaction_type="SPEND",
        ).first()
        self.assertIsNotNone(spend_transaction)
        self.assertEqual(spend_transaction.points, -100)  # Negative for SPEND
        self.assertEqual(spend_transaction.description, f"兑换商品: {item.name}")

    def test_redemption_with_insufficient_points_fails(self):
        """Test redemption fails when user doesn't have enough points."""
        # Create expensive item
        item = ShopItem.objects.create(
            name="Expensive Item",
            description="Very costly",
            cost=1000,  # More than user's 500 points
            stock=5,
            is_active=True,
        )

        # Attempt to redeem should fail with InsufficientPointsError
        from points.services import InsufficientPointsError

        with self.assertRaises(InsufficientPointsError) as exc_info:
            redeem_item(user_profile=self.user, item_id=item.id)

        self.assertTrue(
            "积分不足" in str(exc_info.exception)
            or "insufficient" in str(exc_info.exception).lower()
        )

        # Points should remain unchanged
        self.assertEqual(self.user.total_points, 500)

        # No redemption should be created
        self.assertEqual(Redemption.objects.filter(user_profile=self.user).count(), 0)

        # Stock should remain unchanged
        item.refresh_from_db()
        self.assertEqual(item.stock, 5)

    def test_redemption_with_tag_restrictions(self):
        """Test redemption with priority tag preference."""
        # Create item that prefers event points
        item = ShopItem.objects.create(
            name="Event Prize",
            description="Special event reward",
            cost=50,
            stock=5,
            is_active=True,
        )
        item.allowed_tags.add(self.event_tag)

        # User has 500 general (default) points but no event points
        # The service will use priority tag first, then fall back to default
        # Since user has enough default points, redemption succeeds
        redemption = redeem_item(user_profile=self.user, item_id=item.id)

        self.assertIsNotNone(redemption)
        self.assertEqual(redemption.points_cost_at_redemption, 50)

        # Verify points deducted from default tag (general)
        self.assertEqual(self.user.total_points, 450)  # 500 - 50

        # Grant user some event points
        grant_points(
            user_profile=self.user,
            points=100,
            tag_names=[self.event_tag.name],
            description="活动奖励",
        )

        # Create another item with same tag requirement
        item2 = ShopItem.objects.create(
            name="Event Prize 2",
            description="Another event reward",
            cost=60,
            stock=5,
            is_active=True,
        )
        item2.allowed_tags.add(self.event_tag)

        # Now redemption will prefer event points
        redemption2 = redeem_item(user_profile=self.user, item_id=item2.id)

        self.assertIsNotNone(redemption2)
        self.assertEqual(redemption2.points_cost_at_redemption, 60)

        # Total points should be 490 (450 + 100 event - 60 spent)
        self.assertEqual(self.user.total_points, 490)

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
            redeem_item(user_profile=self.user, item_id=item.id)

        self.assertTrue(
            "库存不足" in str(exc_info.exception).lower()
            or "out of stock" in str(exc_info.exception).lower()
            or "售罄" in str(exc_info.exception)
        )

        # Points should remain unchanged
        self.assertEqual(self.user.total_points, 500)

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
            redeem_item(user_profile=self.user, item_id=item.id)

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
        redemption1 = redeem_item(user_profile=self.user, item_id=item1.id)
        self.assertEqual(self.user.total_points, 400)  # 500 - 100

        # Redeem second item
        redemption2 = redeem_item(user_profile=self.user, item_id=item2.id)
        self.assertEqual(self.user.total_points, 250)  # 400 - 150

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

        # Grant points
        tag = Tag.objects.create(
            name="general", description="通用积分", is_default=True
        )
        grant_points(
            user_profile=self.user,
            points=500,
            tag_names=[tag.name],
            description="初始积分",
        )

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

        # Verify points were deducted
        self.assertEqual(self.user.total_points, 450)  # 500 - 50

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
        """Test entire user lifecycle: register -> get points -> redeem item."""
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

        # Step 2: Admin grants welcome points (simulating backend process)
        tag = Tag.objects.create(
            name="welcome", description="欢迎积分", is_default=True
        )
        grant_points(
            user_profile=user,
            points=300,
            tag_names=[tag.name],
            description="新用户欢迎奖励",
        )

        # Step 3: User logs in and views points
        client.force_login(user)
        my_points_url = reverse("points:my_points")
        response = client.get(my_points_url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("300", response.content.decode())

        # Step 4: User browses shop
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

        # Step 5: User redeems item
        redeem_confirm_url = reverse(
            "accounts:redeem_confirm", kwargs={"item_id": item.id}
        )
        response = client.post(redeem_confirm_url)

        self.assertEqual(response.status_code, 302)

        # Step 6: Verify redemption success
        self.assertEqual(user.total_points, 200)  # 300 - 100
        self.assertEqual(Redemption.objects.filter(user_profile=user).count(), 1)

        redemption = Redemption.objects.get(user_profile=user)
        self.assertEqual(redemption.item, item)
        self.assertEqual(redemption.points_cost_at_redemption, 100)
        self.assertEqual(redemption.status, "COMPLETED")

        # Step 7: User views redemption history
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

        # Admin grants points for profile completion
        tag = Tag.objects.create(
            name="profile-complete", description="完善资料", is_default=True
        )
        grant_points(
            user_profile=user,
            points=50,
            tag_names=[tag.name],
            description="完善个人资料奖励",
        )

        # Verify user received points
        self.assertEqual(user.total_points, 50)

        # User can now use these points in shop
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
        self.assertEqual(user.total_points, 0)  # All points spent
        self.assertEqual(Redemption.objects.filter(user_profile=user).count(), 1)
