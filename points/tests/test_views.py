"""Tests for points views."""

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Organization, OrganizationMembership, User
from points import services
from points.models import PointType, WithdrawalStatus


class UserWalletViewTests(TestCase):
    """Tests for user_wallet_view."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.client = Client()
        self.client.login(username="testuser", password="testpass")

    def test_wallet_view_requires_login(self):
        """Test that wallet view requires login."""
        self.client.logout()
        response = self.client.get(reverse("points:user_wallet"))
        self.assertEqual(response.status_code, 302)

    def test_wallet_view_success(self):
        """Test wallet view loads successfully."""
        response = self.client.get(reverse("points:user_wallet"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "points/user_wallet.html")

    def test_wallet_view_shows_balance(self):
        """Test wallet view shows balance."""
        services.grant_points(self.user, 100, PointType.CASH, "Test")
        services.grant_points(self.user, 50, PointType.GIFT, "Test")

        response = self.client.get(reverse("points:user_wallet"))

        self.assertContains(response, "100")
        self.assertContains(response, "50")


class UserTransactionsViewTests(TestCase):
    """Tests for user_transactions_view."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.client = Client()
        self.client.login(username="testuser", password="testpass")

    def test_transactions_view_requires_login(self):
        """Test that transactions view requires login."""
        self.client.logout()
        response = self.client.get(reverse("points:user_transactions"))
        self.assertEqual(response.status_code, 302)

    def test_transactions_view_success(self):
        """Test transactions view loads successfully."""
        response = self.client.get(reverse("points:user_transactions"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "points/user_transactions.html")

    def test_transactions_view_filter_by_type(self):
        """Test filtering transactions by point type."""
        services.grant_points(self.user, 100, PointType.CASH, "Cash")
        services.grant_points(self.user, 50, PointType.GIFT, "Gift")

        response = self.client.get(
            reverse("points:user_transactions") + "?point_type=cash"
        )
        self.assertEqual(response.status_code, 200)


class CreateWithdrawalViewTests(TestCase):
    """Tests for create_withdrawal_view."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.client = Client()
        self.client.login(username="testuser", password="testpass")
        services.grant_points(self.user, 1000, PointType.CASH, "Initial")

    def test_withdrawal_view_requires_login(self):
        """Test that withdrawal view requires login."""
        self.client.logout()
        response = self.client.get(reverse("points:create_withdrawal"))
        self.assertEqual(response.status_code, 302)

    def test_withdrawal_form_loads(self):
        """Test withdrawal form loads."""
        response = self.client.get(reverse("points:create_withdrawal"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "points/withdrawal_form.html")

    def test_withdrawal_form_submit_success(self):
        """Test successful withdrawal form submission."""
        response = self.client.post(
            reverse("points:create_withdrawal"),
            {
                "amount": "500",
                "real_name": "张三",
                "phone": "13800138000",
                "bank_name": "中国银行",
                "bank_account": "6222000000000000000",
            },
        )
        self.assertRedirects(response, reverse("points:withdrawal_list"))

        # Check withdrawal was created
        wallet = services.get_or_create_wallet(self.user)
        self.assertTrue(wallet.withdrawals.filter(amount=500).exists())

    def test_withdrawal_form_validation(self):
        """Test withdrawal form validation."""
        response = self.client.post(
            reverse("points:create_withdrawal"),
            {
                "amount": "2000",  # More than available
                "real_name": "张三",
                "phone": "13800138000",
                "bank_name": "中国银行",
                "bank_account": "6222000000000000000",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "积分不足")


class WithdrawalListViewTests(TestCase):
    """Tests for withdrawal_list_view."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.client = Client()
        self.client.login(username="testuser", password="testpass")
        services.grant_points(self.user, 1000, PointType.CASH, "Initial")

    def test_withdrawal_list_requires_login(self):
        """Test that withdrawal list requires login."""
        self.client.logout()
        response = self.client.get(reverse("points:withdrawal_list"))
        self.assertEqual(response.status_code, 302)

    def test_withdrawal_list_shows_withdrawals(self):
        """Test withdrawal list shows withdrawals."""
        services.create_withdrawal_request(
            self.user, 500, "张三", "13800138000", "中国银行", "6222000000000000000"
        )

        response = self.client.get(reverse("points:withdrawal_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "500")


class CancelWithdrawalViewTests(TestCase):
    """Tests for cancel_withdrawal_view."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.client = Client()
        self.client.login(username="testuser", password="testpass")
        services.grant_points(self.user, 1000, PointType.CASH, "Initial")

    def test_cancel_withdrawal_success(self):
        """Test canceling withdrawal."""
        withdrawal = services.create_withdrawal_request(
            self.user, 500, "张三", "13800138000", "中国银行", "6222000000000000000"
        )

        response = self.client.post(
            reverse("points:cancel_withdrawal", args=[withdrawal.id])
        )
        self.assertRedirects(response, reverse("points:withdrawal_list"))

        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, WithdrawalStatus.CANCELLED)


class OrgWalletViewTests(TestCase):
    """Tests for org_wallet_view."""

    def setUp(self):
        """Set up test fixtures."""
        self.org = Organization.objects.create(name="Test Org", slug="test-org")
        self.owner = User.objects.create_user(username="owner", password="pass")
        self.non_member = User.objects.create_user(
            username="nonmember", password="pass"
        )

        OrganizationMembership.objects.create(
            user=self.owner,
            organization=self.org,
            role=OrganizationMembership.Role.OWNER,
        )

        self.client = Client()

    def test_org_wallet_requires_login(self):
        """Test that org wallet requires login."""
        response = self.client.get(reverse("points:org_wallet", args=[self.org.slug]))
        self.assertEqual(response.status_code, 302)

    def test_org_wallet_requires_membership(self):
        """Test that org wallet requires membership."""
        self.client.login(username="nonmember", password="pass")
        response = self.client.get(reverse("points:org_wallet", args=[self.org.slug]))
        self.assertRedirects(response, reverse("homepage:index"))

    def test_org_wallet_success(self):
        """Test org wallet loads for member."""
        self.client.login(username="owner", password="pass")
        response = self.client.get(reverse("points:org_wallet", args=[self.org.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "points/organization_wallet.html")


class OrgTransactionsViewTests(TestCase):
    """Tests for org_transactions_view."""

    def setUp(self):
        """Set up test fixtures."""
        self.org = Organization.objects.create(name="Test Org", slug="test-org")
        self.owner = User.objects.create_user(username="owner", password="pass")

        OrganizationMembership.objects.create(
            user=self.owner,
            organization=self.org,
            role=OrganizationMembership.Role.OWNER,
        )

        self.client = Client()
        self.client.login(username="owner", password="pass")

    def test_org_transactions_success(self):
        """Test org transactions loads."""
        response = self.client.get(
            reverse("points:org_transactions", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 200)


class OrgCreateWithdrawalViewTests(TestCase):
    """Tests for org_create_withdrawal_view."""

    def setUp(self):
        """Set up test fixtures."""
        self.org = Organization.objects.create(name="Test Org", slug="test-org")
        self.owner = User.objects.create_user(username="owner", password="pass")
        self.member = User.objects.create_user(username="member", password="pass")

        OrganizationMembership.objects.create(
            user=self.owner,
            organization=self.org,
            role=OrganizationMembership.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            user=self.member,
            organization=self.org,
            role=OrganizationMembership.Role.MEMBER,
        )

        services.grant_points(self.org, 1000, PointType.CASH, "Initial")
        self.client = Client()

    def test_org_withdrawal_requires_admin(self):
        """Test that org withdrawal requires admin role."""
        self.client.login(username="member", password="pass")
        response = self.client.get(
            reverse("points:org_create_withdrawal", args=[self.org.slug])
        )
        self.assertRedirects(
            response, reverse("points:org_wallet", args=[self.org.slug])
        )

    def test_org_withdrawal_form_loads_for_owner(self):
        """Test org withdrawal form loads for owner."""
        self.client.login(username="owner", password="pass")
        response = self.client.get(
            reverse("points:org_create_withdrawal", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 200)

    def test_org_withdrawal_post_success(self):
        """Test successful org withdrawal POST."""
        self.client.login(username="owner", password="pass")
        response = self.client.post(
            reverse("points:org_create_withdrawal", args=[self.org.slug]),
            {
                "amount": "500",
                "real_name": "张三",
                "phone": "13800138000",
                "bank_name": "中国银行",
                "bank_account": "6222000000000000000",
            },
        )
        self.assertRedirects(
            response, reverse("points:org_wallet", args=[self.org.slug])
        )


class ViewEdgeCaseTests(TestCase):
    """Tests for view edge cases."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.client = Client()
        self.client.login(username="testuser", password="testpass")
        services.grant_points(self.user, 1000, PointType.CASH, "Initial")

    def test_transactions_filter_by_transaction_type(self):
        """Test filtering transactions by transaction type."""
        response = self.client.get(
            reverse("points:user_transactions") + "?transaction_type=earn"
        )
        self.assertEqual(response.status_code, 200)

    def test_create_withdrawal_error_handling(self):
        """Test error handling when creating withdrawal fails."""
        # Create a pending withdrawal first
        services.create_withdrawal_request(
            self.user, 500, "张三", "13800138000", "中国银行", "6222"
        )

        # Try to create another one - should show error
        response = self.client.post(
            reverse("points:create_withdrawal"),
            {
                "amount": "200",
                "real_name": "李四",
                "phone": "13900139000",
                "bank_name": "建设银行",
                "bank_account": "6222111111111111111",
            },
        )
        self.assertEqual(response.status_code, 200)  # Form re-rendered with error

    def test_cancel_withdrawal_error_handling(self):
        """Test error handling when canceling withdrawal fails."""
        # Try to cancel a nonexistent withdrawal
        response = self.client.post(reverse("points:cancel_withdrawal", args=[99999]))
        self.assertRedirects(response, reverse("points:withdrawal_list"))


class OrgViewEdgeCaseTests(TestCase):
    """Tests for organization view edge cases."""

    def setUp(self):
        """Set up test fixtures."""
        self.org = Organization.objects.create(name="Test Org", slug="test-org")
        self.owner = User.objects.create_user(username="owner", password="pass")
        self.non_member = User.objects.create_user(
            username="nonmember", password="pass"
        )

        OrganizationMembership.objects.create(
            user=self.owner,
            organization=self.org,
            role=OrganizationMembership.Role.OWNER,
        )

        services.grant_points(self.org, 1000, PointType.CASH, "Initial")
        self.client = Client()

    def test_org_transactions_requires_membership(self):
        """Test that org transactions requires membership."""
        self.client.login(username="nonmember", password="pass")
        response = self.client.get(
            reverse("points:org_transactions", args=[self.org.slug])
        )
        self.assertRedirects(response, reverse("homepage:index"))

    def test_org_transactions_filter_by_point_type(self):
        """Test filtering org transactions by point type."""
        self.client.login(username="owner", password="pass")
        response = self.client.get(
            reverse("points:org_transactions", args=[self.org.slug])
            + "?point_type=cash"
        )
        self.assertEqual(response.status_code, 200)

    def test_org_transactions_filter_by_transaction_type(self):
        """Test filtering org transactions by transaction type."""
        self.client.login(username="owner", password="pass")
        response = self.client.get(
            reverse("points:org_transactions", args=[self.org.slug])
            + "?transaction_type=earn"
        )
        self.assertEqual(response.status_code, 200)

    def test_org_withdrawal_post_error_handling(self):
        """Test error handling when org withdrawal fails."""
        self.client.login(username="owner", password="pass")
        # Create a pending withdrawal first
        services.create_withdrawal_request(
            self.org, 500, "张三", "13800138000", "中国银行", "6222"
        )

        # Try to create another one - should show error
        response = self.client.post(
            reverse("points:org_create_withdrawal", args=[self.org.slug]),
            {
                "amount": "200",
                "real_name": "李四",
                "phone": "13900139000",
                "bank_name": "建设银行",
                "bank_account": "6222111111111111111",
            },
        )
        self.assertEqual(response.status_code, 200)  # Form re-rendered with error
