"""Tests for admin grant points functionality."""

from django.test import TestCase
from django.urls import reverse

from accounts.models import Organization, User
from points import services
from points.forms import GrantPointsForm
from points.models import PointSource, PointTransaction, PointType, Tag, TransactionType


class GrantPointsFormTests(TestCase):
    """Tests for GrantPointsForm."""

    def setUp(self):
        """Set up test fixtures."""
        self.tag = Tag.objects.create(name="测试标签", slug="test-tag")

    def test_valid_cash_form(self):
        """Test valid cash form data."""
        form = GrantPointsForm(
            data={
                "point_type": PointType.CASH.value,
                "amount": 100,
                "reason": "测试发放现金积分",
            }
        )
        self.assertTrue(form.is_valid())

    def test_valid_gift_form_with_tag(self):
        """Test valid gift form data with tag."""
        form = GrantPointsForm(
            data={
                "point_type": PointType.GIFT.value,
                "amount": 50,
                "reason": "测试发放礼物积分",
                "tag": self.tag.id,
            }
        )
        self.assertTrue(form.is_valid())

    def test_gift_without_tag_invalid(self):
        """Test gift points without tag is invalid."""
        form = GrantPointsForm(
            data={
                "point_type": PointType.GIFT.value,
                "amount": 50,
                "reason": "测试发放礼物积分",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("礼物积分必须选择标签", str(form.errors))

    def test_cash_with_tag_invalid(self):
        """Test cash points with tag is invalid."""
        form = GrantPointsForm(
            data={
                "point_type": PointType.CASH.value,
                "amount": 100,
                "reason": "测试发放现金积分",
                "tag": self.tag.id,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("现金积分不能选择标签", str(form.errors))

    def test_zero_amount_invalid(self):
        """Test zero amount is invalid."""
        form = GrantPointsForm(
            data={
                "point_type": PointType.CASH.value,
                "amount": 0,
                "reason": "测试发放",
            }
        )
        self.assertFalse(form.is_valid())

    def test_negative_amount_invalid(self):
        """Test negative amount is invalid."""
        form = GrantPointsForm(
            data={
                "point_type": PointType.CASH.value,
                "amount": -10,
                "reason": "测试发放",
            }
        )
        self.assertFalse(form.is_valid())

    def test_missing_reason_invalid(self):
        """Test missing reason is invalid."""
        form = GrantPointsForm(
            data={
                "point_type": PointType.CASH.value,
                "amount": 100,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("reason", form.errors)


class GrantPointsToUsersViewTests(TestCase):
    """Tests for grant_points_to_users_view."""

    def setUp(self):
        """Set up test fixtures."""
        self.admin = User.objects.create_superuser(
            username="admin", password="adminpass", email="admin@test.com"
        )
        self.user1 = User.objects.create_user(username="user1", password="pass1")
        self.user2 = User.objects.create_user(username="user2", password="pass2")
        self.tag = Tag.objects.create(name="测试标签", slug="test-tag")
        self.client.login(username="admin", password="adminpass")

    def test_permission_required(self):
        """Test that staff permission is required."""
        self.client.logout()
        User.objects.create_user(username="regular", password="pass")
        self.client.login(username="regular", password="pass")

        response = self.client.get(f"/admin/points/grant-to-users/?ids={self.user1.id}")
        # admin_view decorator redirects to login if not staff
        self.assertEqual(response.status_code, 302)

    def test_get_view_displays_form(self):
        """Test GET request displays form."""
        response = self.client.get(f"/admin/points/grant-to-users/?ids={self.user1.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "给用户发放积分")
        self.assertContains(response, self.user1.username)

    def test_get_view_with_multiple_users(self):
        """Test GET request with multiple users."""
        response = self.client.get(
            f"/admin/points/grant-to-users/?ids={self.user1.id},{self.user2.id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.user1.username)
        self.assertContains(response, self.user2.username)

    def test_grant_cash_to_single_user(self):
        """Test granting cash points to a single user."""
        response = self.client.post(
            f"/admin/points/grant-to-users/?ids={self.user1.id}",
            {
                "point_type": PointType.CASH.value,
                "amount": 100,
                "reason": "管理员发放",
            },
        )
        self.assertRedirects(response, reverse("admin:accounts_user_changelist"))

        # Verify points were granted
        balance = services.get_balance(self.user1, PointType.CASH)
        self.assertEqual(balance, 100)

        # Verify transaction was created
        wallet = self.user1.point_wallet
        transactions = PointTransaction.objects.filter(wallet=wallet)
        self.assertEqual(transactions.count(), 1)
        self.assertEqual(transactions.first().transaction_type, TransactionType.EARN)
        self.assertEqual(transactions.first().created_by, self.admin)

    def test_grant_cash_to_multiple_users(self):
        """Test granting cash points to multiple users."""
        response = self.client.post(
            f"/admin/points/grant-to-users/?ids={self.user1.id},{self.user2.id}",
            {
                "point_type": PointType.CASH.value,
                "amount": 200,
                "reason": "批量发放",
            },
        )
        self.assertRedirects(response, reverse("admin:accounts_user_changelist"))

        # Verify both users received points
        balance1 = services.get_balance(self.user1, PointType.CASH)
        balance2 = services.get_balance(self.user2, PointType.CASH)
        self.assertEqual(balance1, 200)
        self.assertEqual(balance2, 200)

    def test_grant_gift_points_with_tag(self):
        """Test granting gift points with tag."""
        response = self.client.post(
            f"/admin/points/grant-to-users/?ids={self.user1.id}",
            {
                "point_type": PointType.GIFT.value,
                "amount": 50,
                "reason": "礼物积分发放",
                "tag": self.tag.id,
            },
        )
        self.assertRedirects(response, reverse("admin:accounts_user_changelist"))

        # Verify gift points were granted
        balance = services.get_balance(self.user1, PointType.GIFT)
        self.assertEqual(balance, 50)

        # Verify point source has correct tag
        wallet = self.user1.point_wallet
        source = PointSource.objects.filter(wallet=wallet).first()
        self.assertEqual(source.tag, self.tag)

    def test_no_users_selected_redirects(self):
        """Test that no users selected redirects with error."""
        response = self.client.get("/admin/points/grant-to-users/")
        self.assertRedirects(response, reverse("admin:accounts_user_changelist"))

    def test_invalid_form_data(self):
        """Test invalid form data shows errors."""
        response = self.client.post(
            f"/admin/points/grant-to-users/?ids={self.user1.id}",
            {
                "point_type": PointType.GIFT.value,
                "amount": 50,
                "reason": "礼物积分发放",
                # Missing tag for gift points
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "礼物积分必须选择标签")


class GrantPointsToOrgsViewTests(TestCase):
    """Tests for grant_points_to_orgs_view."""

    def setUp(self):
        """Set up test fixtures."""
        self.admin = User.objects.create_superuser(
            username="admin", password="adminpass", email="admin@test.com"
        )
        self.org1 = Organization.objects.create(name="组织1", slug="org1")
        self.org2 = Organization.objects.create(name="组织2", slug="org2")
        self.tag = Tag.objects.create(name="测试标签", slug="test-tag")
        self.client.login(username="admin", password="adminpass")

    def test_permission_required(self):
        """Test that staff permission is required."""
        self.client.logout()
        User.objects.create_user(username="regular", password="pass")
        self.client.login(username="regular", password="pass")

        response = self.client.get(f"/admin/points/grant-to-orgs/?ids={self.org1.id}")
        # admin_view decorator redirects to login if not staff
        self.assertEqual(response.status_code, 302)

    def test_get_view_displays_form(self):
        """Test GET request displays form."""
        response = self.client.get(f"/admin/points/grant-to-orgs/?ids={self.org1.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "给组织发放积分")
        self.assertContains(response, self.org1.name)

    def test_get_view_with_multiple_orgs(self):
        """Test GET request with multiple organizations."""
        response = self.client.get(
            f"/admin/points/grant-to-orgs/?ids={self.org1.id},{self.org2.id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.org1.name)
        self.assertContains(response, self.org2.name)

    def test_grant_cash_to_single_org(self):
        """Test granting cash points to a single organization."""
        response = self.client.post(
            f"/admin/points/grant-to-orgs/?ids={self.org1.id}",
            {
                "point_type": PointType.CASH.value,
                "amount": 100,
                "reason": "管理员发放",
            },
        )
        self.assertRedirects(
            response, reverse("admin:accounts_organization_changelist")
        )

        # Verify points were granted
        balance = services.get_balance(self.org1, PointType.CASH)
        self.assertEqual(balance, 100)

        # Verify transaction was created
        wallet = self.org1.point_wallet
        transactions = PointTransaction.objects.filter(wallet=wallet)
        self.assertEqual(transactions.count(), 1)
        self.assertEqual(transactions.first().created_by, self.admin)

    def test_grant_cash_to_multiple_orgs(self):
        """Test granting cash points to multiple organizations."""
        response = self.client.post(
            f"/admin/points/grant-to-orgs/?ids={self.org1.id},{self.org2.id}",
            {
                "point_type": PointType.CASH.value,
                "amount": 200,
                "reason": "批量发放",
            },
        )
        self.assertRedirects(
            response, reverse("admin:accounts_organization_changelist")
        )

        # Verify both organizations received points
        balance1 = services.get_balance(self.org1, PointType.CASH)
        balance2 = services.get_balance(self.org2, PointType.CASH)
        self.assertEqual(balance1, 200)
        self.assertEqual(balance2, 200)

    def test_grant_gift_points_with_tag(self):
        """Test granting gift points with tag."""
        response = self.client.post(
            f"/admin/points/grant-to-orgs/?ids={self.org1.id}",
            {
                "point_type": PointType.GIFT.value,
                "amount": 50,
                "reason": "礼物积分发放",
                "tag": self.tag.id,
            },
        )
        self.assertRedirects(
            response, reverse("admin:accounts_organization_changelist")
        )

        # Verify gift points were granted
        balance = services.get_balance(self.org1, PointType.GIFT)
        self.assertEqual(balance, 50)

        # Verify point source has correct tag
        wallet = self.org1.point_wallet
        source = PointSource.objects.filter(wallet=wallet).first()
        self.assertEqual(source.tag, self.tag)

    def test_no_orgs_selected_redirects(self):
        """Test that no organizations selected redirects with error."""
        response = self.client.get("/admin/points/grant-to-orgs/")
        self.assertRedirects(
            response, reverse("admin:accounts_organization_changelist")
        )

    def test_invalid_form_data(self):
        """Test invalid form data shows errors."""
        response = self.client.post(
            f"/admin/points/grant-to-orgs/?ids={self.org1.id}",
            {
                "point_type": PointType.GIFT.value,
                "amount": 50,
                "reason": "礼物积分发放",
                # Missing tag for gift points
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "礼物积分必须选择标签")


class AdminActionTests(TestCase):
    """Tests for admin actions."""

    def setUp(self):
        """Set up test fixtures."""
        self.admin = User.objects.create_superuser(
            username="admin", password="adminpass", email="admin@test.com"
        )
        self.user1 = User.objects.create_user(username="user1", password="pass1")
        self.org1 = Organization.objects.create(name="组织1", slug="org1")
        self.client.login(username="admin", password="adminpass")

    def test_user_admin_grant_points_action(self):
        """Test UserAdmin grant_points_action redirects correctly."""
        response = self.client.post(
            reverse("admin:accounts_user_changelist"),
            {
                "action": "grant_points_action",
                "_selected_action": [str(self.user1.id)],
            },
            follow=True,
        )
        # Check that it redirects to the grant points page
        self.assertIn("/admin/points/grant-to-users/", response.redirect_chain[0][0])
        self.assertIn(str(self.user1.id), response.redirect_chain[0][0])

    def test_org_admin_grant_points_action(self):
        """Test OrganizationAdmin grant_points_action redirects correctly."""
        response = self.client.post(
            reverse("admin:accounts_organization_changelist"),
            {
                "action": "grant_points_action",
                "_selected_action": [str(self.org1.id)],
            },
            follow=True,
        )
        # Check that it redirects to the grant points page
        self.assertIn("/admin/points/grant-to-orgs/", response.redirect_chain[0][0])
        self.assertIn(str(self.org1.id), response.redirect_chain[0][0])


class IntegrationTests(TestCase):
    """Integration tests for complete grant points workflow."""

    def setUp(self):
        """Set up test fixtures."""
        self.admin = User.objects.create_superuser(
            username="admin", password="adminpass", email="admin@test.com"
        )
        self.user = User.objects.create_user(username="testuser", password="pass")
        self.tag = Tag.objects.create(name="活动奖励", slug="event-reward")
        self.client.login(username="admin", password="adminpass")

    def test_complete_grant_cash_workflow(self):
        """Test complete workflow for granting cash points."""
        # Step 1: Navigate to user list and select user (simulated)
        # Step 2: Access grant points view
        response = self.client.get(f"/admin/points/grant-to-users/?ids={self.user.id}")
        self.assertEqual(response.status_code, 200)

        # Step 3: Submit form
        response = self.client.post(
            f"/admin/points/grant-to-users/?ids={self.user.id}",
            {
                "point_type": PointType.CASH.value,
                "amount": 500,
                "reason": "完成项目贡献",
                "reference_id": "PROJECT-001",
            },
        )

        # Step 4: Verify redirect
        self.assertRedirects(response, reverse("admin:accounts_user_changelist"))

        # Step 5: Verify points were granted
        balance = services.get_balance(self.user, PointType.CASH)
        self.assertEqual(balance, 500)

        # Step 6: Verify transaction record
        wallet = self.user.point_wallet
        transaction = PointTransaction.objects.filter(wallet=wallet).first()
        self.assertEqual(transaction.amount, 500)
        self.assertEqual(transaction.description, "完成项目贡献")
        self.assertEqual(transaction.reference_id, "PROJECT-001")
        self.assertEqual(transaction.created_by, self.admin)

        # Step 7: Verify point source record
        source = PointSource.objects.filter(wallet=wallet).first()
        self.assertEqual(source.original_amount, 500)
        self.assertEqual(source.remaining_amount, 500)
        self.assertEqual(source.created_by, self.admin)

    def test_complete_grant_gift_workflow(self):
        """Test complete workflow for granting gift points."""
        # Access grant points view
        response = self.client.get(f"/admin/points/grant-to-users/?ids={self.user.id}")
        self.assertEqual(response.status_code, 200)

        # Submit form with gift points
        response = self.client.post(
            f"/admin/points/grant-to-users/?ids={self.user.id}",
            {
                "point_type": PointType.GIFT.value,
                "amount": 100,
                "reason": "活动参与奖励",
                "tag": self.tag.id,
            },
        )

        # Verify redirect
        self.assertRedirects(response, reverse("admin:accounts_user_changelist"))

        # Verify gift points were granted
        balance = services.get_balance(self.user, PointType.GIFT)
        self.assertEqual(balance, 100)

        # Verify tag is correctly set
        wallet = self.user.point_wallet
        source = PointSource.objects.filter(wallet=wallet).first()
        self.assertEqual(source.tag, self.tag)
        self.assertEqual(source.point_type, PointType.GIFT)

        # Verify transaction
        transaction = PointTransaction.objects.filter(wallet=wallet).first()
        self.assertEqual(transaction.tag, self.tag)
        self.assertEqual(transaction.point_type, PointType.GIFT)
