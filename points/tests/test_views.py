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
                "id_card": "11010519491231002X",
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
                "id_card": "11010519491231002X",
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
            self.user,
            500,
            "张三",
            "13800138000",
            "11010519491231002X",
            "中国银行",
            "6222000000000000000",
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
            self.user,
            500,
            "张三",
            "13800138000",
            "11010519491231002X",
            "中国银行",
            "6222000000000000000",
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
                "id_card": "11010519491231002X",
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
            self.user,
            500,
            "张三",
            "13800138000",
            "11010519491231002X",
            "中国银行",
            "6222",
        )

        # Try to create another one - should show error
        response = self.client.post(
            reverse("points:create_withdrawal"),
            {
                "amount": "200",
                "real_name": "李四",
                "phone": "13900139000",
                "id_card": "11010519491231002X",
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
            self.org,
            500,
            "张三",
            "13800138000",
            "11010519491231002X",
            "中国银行",
            "6222",
        )

        # Try to create another one - should show error
        response = self.client.post(
            reverse("points:org_create_withdrawal", args=[self.org.slug]),
            {
                "amount": "200",
                "real_name": "李四",
                "phone": "13900139000",
                "id_card": "11010519491231002X",
                "bank_name": "建设银行",
                "bank_account": "6222111111111111111",
            },
        )
        self.assertEqual(response.status_code, 200)  # Form re-rendered with error


class TagSearchAPIViewTests(TestCase):
    """Tests for TagSearchAPIView."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.client = Client()
        self.client.login(username="testuser", password="testpass")

    def test_tag_search_api_requires_login(self):
        """Test that tag search API requires login."""
        self.client.logout()
        response = self.client.get(reverse("points:api_tag_search") + "?q=vscode")
        self.assertEqual(response.status_code, 302)

    def test_tag_search_api_empty_query(self):
        """Test tag search API with empty query."""
        response = self.client.get(reverse("points:api_tag_search"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["tags"], [])

    def test_tag_search_api_with_query(self):
        """Test tag search API with query keyword."""
        from unittest.mock import patch

        # Mock ClickHouse search results
        mock_tags = [
            {
                "id": "github-microsoft-vscode",
                "type": "repo",
                "platform": "github",
                "name": "microsoft/vscode",
                "openrank": 1234.56,
                "name_display": "microsoft/vscode (Github)",
                "slug": "github-microsoft-vscode",
            }
        ]

        with patch("chdb.services.search_tags", return_value=mock_tags):
            response = self.client.get(reverse("points:api_tag_search") + "?q=vscode")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data["tags"]), 1)
            self.assertEqual(data["tags"][0]["id"], "github-microsoft-vscode")
            self.assertEqual(data["tags"][0]["name"], "microsoft/vscode")

    def test_tag_search_api_exception_handling(self):
        """Test tag search API handles exceptions gracefully."""
        from unittest.mock import patch

        with patch(
            "chdb.services.search_tags", side_effect=Exception("Database error")
        ):
            response = self.client.get(reverse("points:api_tag_search") + "?q=vscode")
            self.assertEqual(response.status_code, 500)
            data = response.json()
            self.assertIn("error", data)


class ContributionPreviewAPIViewWithLabelsTests(TestCase):
    """Tests for ContributionPreviewAPIView with label info."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.client = Client()
        self.client.login(username="testuser", password="testpass")

    def test_contribution_preview_with_label_info(self):
        """Test contribution preview API includes label platforms info."""
        from unittest.mock import patch

        # Mock AllocationService.preview_allocation
        mock_preview = [
            {
                "github_login": "alice",
                "github_id": "123",
                "contribution_score": 250.5,
                "calculated_points": 75150,
                "adjusted_points": 75150,
            }
        ]

        # Mock get_label_users
        mock_label_info = {
            "github-microsoft-vscode": {
                "platforms": ["github", "gitee"],
                "users": {"github": [[123, 456]], "gitee": [[789]]},
            }
        }

        with (
            patch(
                "points.allocation_services.AllocationService.preview_allocation",
                return_value=mock_preview,
            ),
            patch("chdb.services.get_label_users", return_value=mock_label_info),
        ):
            response = self.client.post(
                reverse("points:api_contribution_preview"),
                data={
                    "project_scope": {"tags": ["github-microsoft-vscode"]},
                    "start_month": "2024-01-01",
                    "end_month": "2024-01-31",
                    "total_amount": 75150,
                },
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()

            # Verify contributions
            self.assertEqual(len(data["contributions"]), 1)
            self.assertEqual(data["contributions"][0]["github_login"], "alice")

            # Verify label_platforms_info
            self.assertIn("label_platforms_info", data)
            self.assertIn("github-microsoft-vscode", data["label_platforms_info"])
            label_info = data["label_platforms_info"]["github-microsoft-vscode"]
            self.assertEqual(label_info["platforms"], ["github", "gitee"])
            self.assertEqual(label_info["users"]["github"], [[123, 456]])

    def test_contribution_preview_without_project_tags(self):
        """Test contribution preview without project tags returns empty label info."""
        from unittest.mock import patch

        mock_preview = []

        with (
            patch(
                "points.allocation_services.AllocationService.preview_allocation",
                return_value=mock_preview,
            ),
            patch("chdb.services.get_label_users", return_value={}) as mock_get_labels,
        ):
            response = self.client.post(
                reverse("points:api_contribution_preview"),
                data={
                    "project_scope": {},
                    "start_month": "2024-01-01",
                    "end_month": "2024-01-31",
                    "total_amount": 10000,
                },
                content_type="application/json",
            )

            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["label_platforms_info"], {})
            # When project_scope has no tags, get_label_users should not be called
            mock_get_labels.assert_not_called()


class PointAllocationConfigViewTests(TestCase):
    """Tests for PointAllocationConfigView."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.client = Client()
        self.client.login(username="testuser", password="testpass")

    def test_allocation_config_requires_login(self):
        """Test that allocation config view requires login."""
        self.client.logout()
        response = self.client.get(reverse("points:allocation_config"))
        self.assertEqual(response.status_code, 302)

    def test_allocation_config_success(self):
        """Test allocation config view loads successfully."""
        response = self.client.get(reverse("points:allocation_config"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "points/allocation_config.html")

    def test_pools_aggregated_by_type_and_tag(self):
        """Test that multiple PointSources are aggregated by type and tag."""
        from points.models import Tag

        # Create a tag
        Tag.objects.create(name="Tag1", slug="tag1")

        # Grant cash points multiple times (no tags allowed for cash)
        services.grant_points(self.user, 1000, PointType.CASH, "First cash grant")
        services.grant_points(self.user, 500, PointType.CASH, "Second cash grant")

        # Grant gift points without tag
        services.grant_points(
            self.user, 10000, PointType.GIFT, "Gift grant without tag"
        )

        # Grant gift points with tag
        services.grant_points(
            self.user, 1532, PointType.GIFT, "Gift grant with tag", tag_slug="tag1"
        )

        response = self.client.get(reverse("points:allocation_config"))
        self.assertEqual(response.status_code, 200)

        user_pools = response.context["user_pools"]

        # Should have 3 aggregated pools:
        # 1. CASH without tag (1000 + 500 = 1500)
        # 2. GIFT without tag (10000)
        # 3. GIFT with tag1 (1532)
        self.assertEqual(len(user_pools), 3)

        # Find pools by type and tag
        cash_pools = [p for p in user_pools if p["point_type"] == "cash"]
        gift_no_tag = [
            p for p in user_pools if p["point_type"] == "gift" and not p["tag"]
        ]
        gift_with_tag = [
            p for p in user_pools if p["point_type"] == "gift" and p["tag"]
        ]

        # Check cash pool (aggregated)
        self.assertEqual(len(cash_pools), 1)
        self.assertEqual(cash_pools[0]["remaining_amount"], 1500)

        # Check gift pool without tag
        self.assertEqual(len(gift_no_tag), 1)
        self.assertEqual(gift_no_tag[0]["remaining_amount"], 10000)

        # Check gift pool with tag
        self.assertEqual(len(gift_with_tag), 1)
        self.assertEqual(gift_with_tag[0]["remaining_amount"], 1532)
        self.assertEqual(gift_with_tag[0]["tag"].slug, "tag1")

    def test_org_pools_aggregated_correctly(self):
        """Test that organization pools are aggregated correctly."""
        # Create organization
        org = Organization.objects.create(name="TestOrg", slug="testorg")
        OrganizationMembership.objects.create(
            user=self.user, organization=org, role="owner"
        )

        # Grant points to organization multiple times
        services.grant_points(org, 5000, PointType.CASH, "Org grant 1")
        services.grant_points(org, 5000, PointType.CASH, "Org grant 2")
        services.grant_points(org, 10000, PointType.GIFT, "Org gift grant")

        response = self.client.get(reverse("points:allocation_config"))
        self.assertEqual(response.status_code, 200)

        org_pools = response.context["org_pools"]

        # Should have 2 aggregated pools:
        # 1. CASH (5000 + 5000 = 10000)
        # 2. GIFT (10000)
        self.assertEqual(len(org_pools), 2)

        cash_pool = [p for p in org_pools if p["point_type"] == "cash"]
        gift_pool = [p for p in org_pools if p["point_type"] == "gift"]

        self.assertEqual(len(cash_pool), 1)
        self.assertEqual(cash_pool[0]["remaining_amount"], 10000)
        self.assertEqual(cash_pool[0]["wallet"]["owner"], org)

        self.assertEqual(len(gift_pool), 1)
        self.assertEqual(gift_pool[0]["remaining_amount"], 10000)

    def test_pools_exclude_zero_balance(self):
        """Test that pools with zero balance are excluded."""
        # Grant and spend all points
        services.grant_points(self.user, 100, PointType.CASH, "Grant")
        services.spend_points(self.user, 100, PointType.CASH, "Spend all")

        response = self.client.get(reverse("points:allocation_config"))
        self.assertEqual(response.status_code, 200)

        user_pools = response.context["user_pools"]
        # Should have no pools since balance is zero
        self.assertEqual(len(user_pools), 0)
