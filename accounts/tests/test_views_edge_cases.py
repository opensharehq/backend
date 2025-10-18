"""
Additional edge case tests for accounts views to ensure robustness.

This module adds comprehensive edge case tests beyond the existing test coverage
to ensure the views handle all possible scenarios correctly.
"""

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from social_django.models import UserSocialAuth

from accounts.models import Education, UserProfile, WorkExperience
from common.test_utils import CacheClearTestCase

User = get_user_model()


class SignUpViewEdgeCaseTests(TestCase):
    """Edge case tests for sign up view."""

    def test_sign_up_view_post_duplicate_username(self):
        """Test that duplicate username is rejected."""
        User.objects.create_user(
            username="existinguser",
            email="existing@example.com",
            password="testpass123",
        )
        data = {
            "username": "existinguser",
            "email": "newemail@example.com",
            "password1": "testpass123",
            "password2": "testpass123",
        }
        response = self.client.post(reverse("accounts:sign_up"), data)
        assert response.status_code == 200
        assert not User.objects.filter(email="newemail@example.com").exists()

    def test_sign_up_view_post_duplicate_email(self):
        """Test that duplicate email is rejected."""
        User.objects.create_user(
            username="user1",
            email="duplicate@example.com",
            password="testpass123",
        )
        data = {
            "username": "newuser",
            "email": "duplicate@example.com",
            "password1": "testpass123",
            "password2": "testpass123",
        }
        response = self.client.post(reverse("accounts:sign_up"), data)
        assert response.status_code == 200
        self.assertContains(response, "该邮箱已被注册")

    def test_sign_up_view_post_with_messages_success(self):
        """Test that successful sign up displays success message."""
        data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password1": "testpass123",
            "password2": "testpass123",
        }
        response = self.client.post(reverse("accounts:sign_up"), data, follow=True)
        messages = list(response.context["messages"])
        assert len(messages) == 1
        assert "注册成功" in str(messages[0])

    def test_sign_up_view_logs_user_in_automatically(self):
        """Test that user is logged in automatically after sign up."""
        data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password1": "testpass123",
            "password2": "testpass123",
        }
        response = self.client.post(reverse("accounts:sign_up"), data, follow=True)
        assert response.context["user"].is_authenticated
        assert response.context["user"].username == "newuser"


class ProfileEditViewEdgeCaseTests(TestCase):
    """Edge case tests for profile edit view."""

    def test_profile_edit_view_post_invalid_work_formset(self):
        """Test that invalid work formset prevents submission."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)

        # Missing required fields in work formset
        data = {
            "bio": "",
            "birth_date": "",
            "company": "",
            "location": "",
            "github_url": "",
            "homepage_url": "",
            "blog_url": "",
            "twitter_url": "",
            "linkedin_url": "",
            "work_experiences-TOTAL_FORMS": "1",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            "work_experiences-0-company_name": "",  # Required field empty
            "work_experiences-0-title": "Engineer",
            "work_experiences-0-start_date": "2020-01-01",
            "educations-TOTAL_FORMS": "1",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
            "shipping_addresses-TOTAL_FORMS": "0",
            "shipping_addresses-INITIAL_FORMS": "0",
            "shipping_addresses-MIN_NUM_FORMS": "0",
            "shipping_addresses-MAX_NUM_FORMS": "1000",
        }
        response = self.client.post(reverse("accounts:profile_edit"), data)
        assert response.status_code == 200
        # Should re-render the form with errors
        self.assertTemplateUsed(response, "profile_edit.html")

    def test_profile_edit_view_post_invalid_education_formset(self):
        """Test that invalid education formset prevents submission."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)

        # Missing required fields in education formset
        data = {
            "bio": "",
            "birth_date": "",
            "company": "",
            "location": "",
            "github_url": "",
            "homepage_url": "",
            "blog_url": "",
            "twitter_url": "",
            "linkedin_url": "",
            "work_experiences-TOTAL_FORMS": "1",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            "educations-TOTAL_FORMS": "1",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
            "educations-0-institution_name": "",  # Required field empty
            "educations-0-field_of_study": "CS",
            "educations-0-start_date": "2015-09-01",
            "shipping_addresses-TOTAL_FORMS": "0",
            "shipping_addresses-INITIAL_FORMS": "0",
            "shipping_addresses-MIN_NUM_FORMS": "0",
            "shipping_addresses-MAX_NUM_FORMS": "1000",
        }
        response = self.client.post(reverse("accounts:profile_edit"), data)
        assert response.status_code == 200
        # Should re-render the form with errors
        self.assertTemplateUsed(response, "profile_edit.html")

    def test_profile_edit_view_update_existing_work_experience(self):
        """Test that updating existing work experience works correctly."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        profile = UserProfile.objects.create(user=user)
        work = WorkExperience.objects.create(
            profile=profile,
            company_name="Old Company",
            title="Old Title",
            start_date=date(2020, 1, 1),
        )
        self.client.force_login(user)

        data = {
            "bio": "",
            "birth_date": "",
            "company": "",
            "location": "",
            "github_url": "",
            "homepage_url": "",
            "blog_url": "",
            "twitter_url": "",
            "linkedin_url": "",
            "work_experiences-TOTAL_FORMS": "2",
            "work_experiences-INITIAL_FORMS": "1",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            "work_experiences-0-id": str(work.id),
            "work_experiences-0-profile": str(profile.user_id),
            "work_experiences-0-company_name": "Updated Company",  # Updated
            "work_experiences-0-title": "Updated Title",  # Updated
            "work_experiences-0-start_date": "2020-01-01",
            "work_experiences-0-end_date": "",
            "work_experiences-0-description": "",
            "educations-TOTAL_FORMS": "1",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
            "shipping_addresses-TOTAL_FORMS": "0",
            "shipping_addresses-INITIAL_FORMS": "0",
            "shipping_addresses-MIN_NUM_FORMS": "0",
            "shipping_addresses-MAX_NUM_FORMS": "1000",
        }
        response = self.client.post(reverse("accounts:profile_edit"), data, follow=True)
        messages = list(response.context["messages"])
        assert "个人资料已更新" in str(messages[0])

        work.refresh_from_db()
        assert work.company_name == "Updated Company"
        assert work.title == "Updated Title"

    def test_profile_edit_view_update_existing_education(self):
        """Test that updating existing education works correctly."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        profile = UserProfile.objects.create(user=user)
        edu = Education.objects.create(
            profile=profile,
            institution_name="Old University",
            field_of_study="Old Field",
            start_date=date(2015, 9, 1),
        )
        self.client.force_login(user)

        data = {
            "bio": "",
            "birth_date": "",
            "company": "",
            "location": "",
            "github_url": "",
            "homepage_url": "",
            "blog_url": "",
            "twitter_url": "",
            "linkedin_url": "",
            "work_experiences-TOTAL_FORMS": "1",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            "educations-TOTAL_FORMS": "2",
            "educations-INITIAL_FORMS": "1",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
            "educations-0-id": str(edu.id),
            "educations-0-profile": str(profile.user_id),
            "educations-0-institution_name": "Updated University",  # Updated
            "educations-0-field_of_study": "Updated Field",  # Updated
            "educations-0-start_date": "2015-09-01",
            "educations-0-end_date": "",
            "educations-0-degree": "",
            "shipping_addresses-TOTAL_FORMS": "0",
            "shipping_addresses-INITIAL_FORMS": "0",
            "shipping_addresses-MIN_NUM_FORMS": "0",
            "shipping_addresses-MAX_NUM_FORMS": "1000",
        }
        response = self.client.post(reverse("accounts:profile_edit"), data, follow=True)
        messages = list(response.context["messages"])
        assert "个人资料已更新" in str(messages[0])

        edu.refresh_from_db()
        assert edu.institution_name == "Updated University"
        assert edu.field_of_study == "Updated Field"


class SocialConnectionsViewEdgeCaseTests(TestCase):
    """Edge case tests for social connections view."""

    def test_social_connections_view_with_partial_config(self):
        """Test that providers with only key but no secret are hidden."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)

        # Only key, no secret
        with self.settings(
            SOCIAL_AUTH_GITHUB_KEY="test_key",
            SOCIAL_AUTH_GITHUB_SECRET="",
        ):
            response = self.client.get(reverse("accounts:social_connections"))
            # Should not show GitHub since secret is missing
            self.assertNotContains(response, "GitHub")

    def test_social_connections_view_with_no_password_and_no_social(self):
        """Test edge case where user has no password and no social accounts."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
        )
        user.set_unusable_password()
        user.save()
        self.client.force_login(user)

        with self.settings(
            SOCIAL_AUTH_GITHUB_KEY="test_key",
            SOCIAL_AUTH_GITHUB_SECRET="test_secret",
        ):
            response = self.client.get(reverse("accounts:social_connections"))
            # User should not be able to disconnect anything
            assert response.context["can_disconnect"] is False


class DisconnectSocialAccountEdgeCaseTests(TestCase):
    """Edge case tests for disconnect social account view."""

    def test_disconnect_social_account_wrong_provider(self):
        """Test that disconnecting with wrong provider name fails."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        social_auth = UserSocialAuth.objects.create(
            user=user,
            provider="github",
            uid="github123",
        )
        self.client.force_login(user)

        # Try to disconnect with wrong provider name
        response = self.client.post(
            reverse(
                "accounts:disconnect_social",
                args=["google-oauth2", social_auth.id],  # Wrong provider
            ),
            follow=True,
        )
        messages = list(response.context["messages"])
        assert "未找到该社交账号绑定" in str(messages[0])
        # Social auth should still exist
        assert UserSocialAuth.objects.filter(id=social_auth.id).exists()


class ChangePasswordViewEdgeCaseTests(TestCase):
    """Edge case tests for change password view."""

    def test_change_password_view_post_session_updated(self):
        """Test that session auth hash is updated after password change."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="oldpass123",
        )
        self.client.force_login(user)

        # Get session auth hash before password change

        data = {
            "old_password": "oldpass123",
            "new_password1": "newpass123",
            "new_password2": "newpass123",
        }
        self.client.post(reverse("accounts:change_password"), data)

        # User should still be logged in after password change
        assert self.client.session.get("_auth_user_id") is not None

    def test_change_password_view_post_displays_success_message(self):
        """Test that password change displays success message."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="oldpass123",
        )
        self.client.force_login(user)
        data = {
            "old_password": "oldpass123",
            "new_password1": "newpass123",
            "new_password2": "newpass123",
        }
        response = self.client.post(
            reverse("accounts:change_password"), data, follow=True
        )
        messages = list(response.context["messages"])
        assert len(messages) == 1
        assert "密码修改成功" in str(messages[0])


class ChangeEmailViewEdgeCaseTests(TestCase):
    """Edge case tests for change email view."""

    def test_change_email_view_post_displays_success_message(self):
        """Test that email change displays success message."""
        user = User.objects.create_user(
            username="testuser",
            email="old@example.com",
            password="testpass123",
        )
        self.client.force_login(user)
        data = {
            "email": "new@example.com",
            "password": "testpass123",
        }
        response = self.client.post(reverse("accounts:change_email"), data, follow=True)
        messages = list(response.context["messages"])
        assert len(messages) == 1
        assert "邮箱修改成功" in str(messages[0])


class PasswordResetRequestEdgeCaseTests(TestCase):
    """Edge case tests for password reset request view."""

    @patch("accounts.views.send_password_reset_email")
    def test_password_reset_request_with_multiple_social_providers(self, mock_task):
        """Test password reset with user having multiple social providers."""
        user = User.objects.create_user(
            username="socialuser",
            email="social@example.com",
        )
        user.set_unusable_password()
        user.save()

        # Create multiple social auths
        UserSocialAuth.objects.create(user=user, provider="github", uid="12345")
        UserSocialAuth.objects.create(user=user, provider="google-oauth2", uid="67890")
        UserSocialAuth.objects.create(user=user, provider="facebook", uid="11111")

        response = self.client.post(
            reverse("accounts:password_reset_request"),
            {"email": "social@example.com"},
            follow=True,
        )

        messages = list(response.context["messages"])
        # Should show first 3 providers
        assert "github" in str(messages[0])
        assert "google-oauth2" in str(messages[0])
        mock_task.enqueue.assert_not_called()

    def test_password_reset_request_with_invalid_email_format(self):
        """Test password reset with invalid email format."""
        response = self.client.post(
            reverse("accounts:password_reset_request"),
            {"email": "invalid-email"},
        )
        assert response.status_code == 200
        # Form should have validation errors
        self.assertContains(response, "输入一个有效的 Email 地址")


class PasswordResetConfirmEdgeCaseTests(TestCase):
    """Edge case tests for password reset confirm view."""

    def test_password_reset_confirm_view_with_type_error_in_uidb64(self):
        """Test password reset confirm with TypeError in uidb64 decoding."""
        url = reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": "!!!invalid!!!", "token": "some-token"},
        )
        response = self.client.get(url)
        assert response.status_code == 200
        self.assertContains(response, "链接无效或已过期")

    def test_password_reset_confirm_view_with_overflow_error(self):
        """Test password reset confirm with OverflowError in user pk."""
        # Create a very large number that will overflow
        large_uid = urlsafe_base64_encode(
            force_bytes("999999999999999999999999999999999999")
        )
        url = reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": large_uid, "token": "some-token"},
        )
        response = self.client.get(url)
        assert response.status_code == 200
        self.assertContains(response, "链接无效或已过期")

    def test_password_reset_confirm_view_post_weak_password(self):
        """Test POST with weak password that fails validation."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="oldpass123",
        )
        token = default_token_generator.make_token(user)
        uidb64 = urlsafe_base64_encode(force_bytes(user.pk))

        url = reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": uidb64, "token": token},
        )
        response = self.client.post(
            url,
            {
                "new_password1": "123",  # Too short
                "new_password2": "123",
            },
        )

        assert response.status_code == 200
        # Password should not be changed
        user.refresh_from_db()
        assert user.check_password("oldpass123")


class ShopListViewEdgeCaseTests(TestCase):
    """Edge case tests for shop list view."""

    def test_shop_list_view_template_rendered(self):
        """Test that shop list view renders correct template."""
        User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        self.client.login(username="testuser", password="password123")
        response = self.client.get(reverse("accounts:shop_list"))
        self.assertTemplateUsed(response, "shop_list.html")

    def test_shop_list_view_items_prefetch_tags(self):
        """Test that shop items are prefetched with tags."""
        from points.models import Tag
        from shop.models import ShopItem

        User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )

        # Create tags and item
        tag1 = Tag.objects.create(name="tag1")
        tag2 = Tag.objects.create(name="tag2")
        item = ShopItem.objects.create(
            name="Item",
            description="Description",
            cost=50,
            is_active=True,
        )
        item.allowed_tags.add(tag1, tag2)

        self.client.login(username="testuser", password="password123")
        response = self.client.get(reverse("accounts:shop_list"))

        # Verify items are in context with prefetched tags
        items = response.context["items"]
        assert item in items


class RedemptionListViewEdgeCaseTests(TestCase):
    """Edge case tests for redemption list view."""

    def test_redemption_list_view_template_rendered(self):
        """Test that redemption list view renders correct template."""
        User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        self.client.login(username="testuser", password="password123")
        response = self.client.get(reverse("accounts:redemption_list"))
        self.assertTemplateUsed(response, "redemption_list.html")

    def test_redemption_list_view_select_related(self):
        """Test that redemptions are select_related with item and transaction."""
        from points.models import PointSource, PointTransaction, Tag
        from shop.models import Redemption, ShopItem

        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )

        # Create test data
        item = ShopItem.objects.create(
            name="Test Item",
            description="Description",
            cost=50,
            is_active=True,
        )
        tag = Tag.objects.create(name="test-tag")
        source = PointSource.objects.create(
            user_profile=user,
            initial_points=100,
            remaining_points=50,
        )
        source.tags.add(tag)

        transaction = PointTransaction.objects.create(
            user_profile=user,
            points=-50,
            transaction_type=PointTransaction.TransactionType.SPEND,
            description="Test redemption",
        )

        Redemption.objects.create(
            user_profile=user,
            item=item,
            points_cost_at_redemption=50,
            transaction=transaction,
            status=Redemption.StatusChoices.COMPLETED,
        )

        self.client.login(username="testuser", password="password123")
        response = self.client.get(reverse("accounts:redemption_list"))

        # Verify redemptions are in context
        redemptions = response.context["redemptions"]
        assert redemptions.count() == 1


class RedeemConfirmViewEdgeCaseTests(TestCase):
    """Edge case tests for redeem confirm view."""

    def test_redeem_confirm_get_exact_points_match(self):
        """Test GET when user has exact points needed."""
        from points.models import PointSource, Tag
        from shop.models import ShopItem

        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )

        # User has exactly the cost amount
        tag = Tag.objects.create(name="test-tag")
        source = PointSource.objects.create(
            user_profile=user,
            initial_points=50,
            remaining_points=50,
        )
        source.tags.add(tag)

        item = ShopItem.objects.create(
            name="Test Item",
            description="Description",
            cost=50,
            is_active=True,
        )

        self.client.login(username="testuser", password="password123")
        response = self.client.get(reverse("accounts:redeem_confirm", args=[item.id]))

        assert response.context["can_afford"] is True
        assert response.context["remaining_after_redeem"] == 0
        assert response.context["points_needed"] == 0

    def test_redeem_confirm_post_redemption_error_message(self):
        """Test that RedemptionError displays appropriate error message."""
        from shop.models import ShopItem

        User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )

        # Create inactive item
        inactive_item = ShopItem.objects.create(
            name="Inactive Item",
            description="Description",
            cost=50,
            is_active=False,
        )

        self.client.login(username="testuser", password="password123")
        response = self.client.post(
            reverse("accounts:redeem_confirm", args=[inactive_item.id]), follow=True
        )

        messages = list(response.context["messages"])
        assert len(messages) == 1
        assert "兑换失败" in str(messages[0])

    def test_redeem_confirm_post_insufficient_points_message(self):
        """Test that InsufficientPointsError displays appropriate message."""
        from shop.models import ShopItem

        User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )

        # Create expensive item with no points
        expensive_item = ShopItem.objects.create(
            name="Expensive Item",
            description="Description",
            cost=1000,
            is_active=True,
        )

        self.client.login(username="testuser", password="password123")
        response = self.client.post(
            reverse("accounts:redeem_confirm", args=[expensive_item.id]), follow=True
        )

        messages = list(response.context["messages"])
        assert len(messages) == 1
        assert "积分不足" in str(messages[0])

    def test_redeem_confirm_post_success_message(self):
        """Test that successful redemption displays success message."""
        from points.models import PointSource, Tag
        from shop.models import ShopItem

        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )

        tag = Tag.objects.create(name="test-tag")
        source = PointSource.objects.create(
            user_profile=user,
            initial_points=100,
            remaining_points=100,
        )
        source.tags.add(tag)

        item = ShopItem.objects.create(
            name="Test Item",
            description="Description",
            cost=50,
            is_active=True,
        )

        self.client.login(username="testuser", password="password123")
        response = self.client.post(
            reverse("accounts:redeem_confirm", args=[item.id]), follow=True
        )

        messages = list(response.context["messages"])
        assert len(messages) == 1
        assert "成功兑换" in str(messages[0])
        assert "Test Item" in str(messages[0])


class PublicProfileViewEdgeCaseTests(CacheClearTestCase):
    """Edge case tests for public profile view."""

    def test_public_profile_view_with_zero_points(self):
        """Test public profile displays zero points correctly."""
        User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )

        response = self.client.get(reverse("public_profile", args=["testuser"]))
        assert response.context["total_points"] == 0

    def test_public_profile_view_empty_work_and_education(self):
        """Test public profile with no work experience or education."""
        User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )

        response = self.client.get(reverse("public_profile", args=["testuser"]))
        assert len(response.context["work_experiences"]) == 0
        assert len(response.context["educations"]) == 0

    def test_public_profile_view_multiple_work_experiences(self):
        """Test public profile displays multiple work experiences."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        profile = UserProfile.objects.create(user=user)

        # Create multiple work experiences
        WorkExperience.objects.create(
            profile=profile,
            company_name="Company 1",
            title="Engineer 1",
            start_date=date(2018, 1, 1),
            end_date=date(2020, 12, 31),
        )
        WorkExperience.objects.create(
            profile=profile,
            company_name="Company 2",
            title="Engineer 2",
            start_date=date(2021, 1, 1),
        )

        response = self.client.get(reverse("public_profile", args=["testuser"]))
        assert len(response.context["work_experiences"]) == 2

    def test_public_profile_view_multiple_educations(self):
        """Test public profile displays multiple educations."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        profile = UserProfile.objects.create(user=user)

        # Create multiple educations
        Education.objects.create(
            profile=profile,
            institution_name="University 1",
            field_of_study="CS",
            start_date=date(2014, 9, 1),
            end_date=date(2018, 6, 30),
        )
        Education.objects.create(
            profile=profile,
            institution_name="University 2",
            field_of_study="AI",
            start_date=date(2018, 9, 1),
            end_date=date(2020, 6, 30),
        )

        response = self.client.get(reverse("public_profile", args=["testuser"]))
        assert len(response.context["educations"]) == 2
