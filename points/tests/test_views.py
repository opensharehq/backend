"""Tests for points views."""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Organization, OrganizationMembership, User
from points import services, views
from points.models import PointAllocation, PointType, Tag, TagType, WithdrawalStatus


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

    def test_withdrawal_requires_invoice_over_limit(self):
        """Test invoice required when amount exceeds limit."""
        services.grant_points(self.user, 6000, PointType.CASH, "Extra")
        response = self.client.post(
            reverse("points:create_withdrawal"),
            {
                "amount": "6000",
                "real_name": "张三",
                "phone": "13800138000",
                "id_card": "11010519491231002X",
                "bank_name": "中国银行",
                "bank_account": "6222000000000000000",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "必须上传发票")


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

    def test_cancel_withdrawal_get_only_redirects_without_changes(self):
        """GET requests should not mutate the withdrawal status."""
        withdrawal = services.create_withdrawal_request(
            self.user,
            500,
            "张三",
            "13800138000",
            "11010519491231002X",
            "中国银行",
            "6222000000000000000",
        )

        response = self.client.get(
            reverse("points:cancel_withdrawal", args=[withdrawal.id])
        )

        self.assertRedirects(response, reverse("points:withdrawal_list"))
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, WithdrawalStatus.PENDING)


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

    def test_org_withdrawal_invalid_post_rerenders_form(self):
        """Invalid org withdrawal submissions should stay on the form page."""
        self.client.login(username="owner", password="pass")

        response = self.client.post(
            reverse("points:org_create_withdrawal", args=[self.org.slug]),
            {
                "amount": "",
                "real_name": "张三",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "points/organization_withdrawal_form.html")


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

    def test_tag_search_api_whitespace_query_skips_backend(self):
        """Whitespace-only queries should short-circuit before hitting ClickHouse."""
        with patch("chdb.services.search_tags") as search_mock:
            response = self.client.get(reverse("points:api_tag_search") + "?q=   ")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tags"], [])
        search_mock.assert_not_called()

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


class PoolListAPIViewTests(TestCase):
    """Tests for PoolListAPIView."""

    def setUp(self):
        self.user = User.objects.create_user(username="pool-user", password="testpass")
        self.org = Organization.objects.create(name="Pool Org", slug="pool-org")
        OrganizationMembership.objects.create(
            user=self.user,
            organization=self.org,
            role=OrganizationMembership.Role.OWNER,
        )
        self.tag = Tag.objects.create(
            name="Pool Tag",
            slug="pool-tag",
            tag_type=TagType.REPO,
        )
        services.grant_points(self.user, 100, PointType.CASH, "User cash")
        services.grant_points(
            self.user,
            50,
            PointType.GIFT,
            "User tagged gift",
            tag_slug=self.tag.slug,
        )
        services.grant_points(self.org, 80, PointType.GIFT, "Org gift")

        self.client = Client()
        self.client.login(username="pool-user", password="testpass")

    def test_pool_list_api_requires_login(self):
        """Pool list API should require authentication."""
        self.client.logout()

        response = self.client.get(reverse("points:api_pool_list"))

        self.assertEqual(response.status_code, 302)

    def test_pool_list_api_serializes_user_and_org_pools(self):
        """Test pool list API includes both personal and organization pools."""
        response = self.client.get(reverse("points:api_pool_list"))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["user_pools"]), 2)
        self.assertEqual(len(data["org_pools"]), 1)
        self.assertTrue(any(pool["owner"] == "个人" for pool in data["user_pools"]))
        self.assertEqual(data["org_pools"][0]["owner"], str(self.org))
        self.assertEqual(data["user_pools"][1]["tag"], self.tag.slug)
        self.assertEqual(
            set(data["user_pools"][0].keys()),
            {"id", "type", "type_display", "balance", "tag", "tag_name", "owner"},
        )

    def test_pool_list_excludes_org_pools_for_non_admin_members(self):
        """Regular org members should not receive organization pools from the API."""
        member = User.objects.create_user(username="org-member", password="testpass")
        OrganizationMembership.objects.create(
            user=member,
            organization=self.org,
            role=OrganizationMembership.Role.MEMBER,
        )
        self.client.login(username="org-member", password="testpass")

        response = self.client.get(reverse("points:api_pool_list"))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["org_pools"], [])


class TagListAPIViewTests(TestCase):
    """Tests for TagListAPIView."""

    def setUp(self):
        self.user = User.objects.create_user(username="tag-user", password="testpass")
        self.client = Client()
        self.client.login(username="tag-user", password="testpass")
        self.repo_official = Tag.objects.create(
            name="Official Repo",
            slug="official-repo",
            tag_type=TagType.REPO,
            is_official=True,
        )
        self.repo_unofficial = Tag.objects.create(
            name="Unofficial Repo",
            slug="unofficial-repo",
            tag_type=TagType.REPO,
            is_official=False,
        )
        Tag.objects.create(
            name="Official User",
            slug="official-user",
            tag_type=TagType.USER,
            is_official=True,
        )

    def test_tag_list_api_requires_login(self):
        """Tag list API should require authentication."""
        self.client.logout()

        response = self.client.get(reverse("points:api_tag_list"))

        self.assertEqual(response.status_code, 302)

    def test_tag_list_api_filters_by_type_and_official(self):
        """Test tag list API filters by tag type and official flag."""
        response = self.client.get(
            reverse("points:api_tag_list") + "?type=repo&official=true"
        )

        self.assertEqual(response.status_code, 200)
        tags = response.json()["tags"]
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0]["slug"], self.repo_official.slug)

    def test_tag_list_api_filters_unofficial_tags(self):
        """Test tag list API returns unofficial tags when requested."""
        response = self.client.get(reverse("points:api_tag_list") + "?official=false")

        self.assertEqual(response.status_code, 200)
        tags = response.json()["tags"]
        self.assertEqual([tag["slug"] for tag in tags], [self.repo_unofficial.slug])
        self.assertEqual(
            set(tags[0].keys()),
            {"slug", "name", "type", "is_official", "entity_identifier"},
        )

    def test_tag_list_api_without_official_filter_returns_all_matching_types(self):
        """Omitting the official flag should keep both official and unofficial matches."""
        response = self.client.get(reverse("points:api_tag_list") + "?type=repo")

        self.assertEqual(response.status_code, 200)
        tags = response.json()["tags"]
        self.assertEqual(
            {tag["slug"] for tag in tags},
            {self.repo_official.slug, self.repo_unofficial.slug},
        )


class ContributionPreviewAPIViewWithLabelsTests(TestCase):
    """Tests for ContributionPreviewAPIView with label info."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.client = Client()
        self.client.login(username="testuser", password="testpass")

    def test_contribution_preview_requires_login(self):
        """Contribution preview API should require authentication."""
        self.client.logout()

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

        self.assertEqual(response.status_code, 302)

    def test_contribution_preview_with_label_info(self):
        """Test contribution preview API includes label platforms info."""
        from unittest.mock import patch

        # Mock AllocationService.preview_allocation
        mock_preview = [
            {
                "actor_login": "alice",
                "actor_id": "123",
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
            self.assertEqual(data["contributions"][0]["actor_login"], "alice")

            # Verify label_platforms_info
            self.assertIn("label_platforms_info", data)
            self.assertIn("github-microsoft-vscode", data["label_platforms_info"])
            label_info = data["label_platforms_info"]["github-microsoft-vscode"]
            self.assertEqual(label_info["platforms"], ["github", "gitee"])
            self.assertEqual(label_info["users"]["github"], [[123, 456]])

    def test_contribution_preview_success_response_shape(self):
        """Successful preview responses should expose the documented top-level fields."""
        mock_preview = [
            {
                "actor_login": "alice",
                "actor_id": "123",
                "contribution_score": 250.5,
                "calculated_points": 75150,
                "adjusted_points": 75150,
            }
        ]

        with (
            patch(
                "points.allocation_services.AllocationService.preview_allocation",
                return_value=mock_preview,
            ),
            patch("chdb.services.get_label_users", return_value={}),
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
        self.assertEqual(
            set(data.keys()),
            {
                "contributions",
                "label_platforms_info",
                "total_points",
                "total_recipients",
            },
        )
        self.assertIsInstance(data["contributions"][0]["contribution_score"], float)

    def test_contribution_preview_keeps_items_without_contribution_score(self):
        """Preview serialization should only coerce contribution_score when present."""
        mock_preview = [
            {
                "actor_login": "alice",
                "actor_id": "123",
                "contribution_score": 250.5,
                "calculated_points": 100,
                "adjusted_points": 100,
            },
            {
                "actor_login": "bob",
                "actor_id": "456",
                "calculated_points": 80,
                "adjusted_points": 80,
            },
        ]

        with (
            patch(
                "points.allocation_services.AllocationService.preview_allocation",
                return_value=mock_preview,
            ),
            patch("chdb.services.get_label_users", return_value={}),
        ):
            response = self.client.post(
                reverse("points:api_contribution_preview"),
                data={
                    "project_scope": {"tags": ["github-microsoft-vscode"]},
                    "start_month": "2024-01-01",
                    "end_month": "2024-01-31",
                    "total_amount": 180,
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        contributions = response.json()["contributions"]
        self.assertIn("contribution_score", contributions[0])
        self.assertNotIn("contribution_score", contributions[1])

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


class ContributionPreviewAPIViewErrorTests(TestCase):
    """Tests for error handling in ContributionPreviewAPIView."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="preview-error-user",
            password="testpass",
        )
        self.client = Client()
        self.client.login(username="preview-error-user", password="testpass")

    def test_contribution_preview_invalid_payload_returns_400(self):
        """Test malformed preview payloads are rejected with a JSON error."""
        response = self.client.post(
            reverse("points:api_contribution_preview"),
            data="{invalid json",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_contribution_preview_non_object_json_body_returns_400(self):
        """JSON arrays should be rejected before field-level validation."""
        response = self.client.post(
            reverse("points:api_contribution_preview"),
            data='["not", "an", "object"]',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "请求参数格式不正确。")

    def test_contribution_preview_get_is_not_allowed(self):
        """Preview endpoint should reject GET requests."""
        response = self.client.get(reverse("points:api_contribution_preview"))

        self.assertEqual(response.status_code, 405)

    def test_contribution_preview_missing_required_field_returns_400(self):
        """Missing required payload keys should be reported as JSON errors."""
        response = self.client.post(
            reverse("points:api_contribution_preview"),
            data={
                "project_scope": {"tags": ["tag"]},
                "start_month": "2024-01-01",
                "end_month": "2024-01-31",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_contribution_preview_invalid_date_returns_400(self):
        """Invalid preview dates should surface as JSON validation errors."""
        response = self.client.post(
            reverse("points:api_contribution_preview"),
            data={
                "project_scope": {"tags": ["tag"]},
                "start_month": "not-a-date",
                "end_month": "2024-01-31",
                "total_amount": 1000,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_contribution_preview_non_dict_project_scope_returns_400(self):
        """Non-dict project scope payloads should be rejected."""
        response = self.client.post(
            reverse("points:api_contribution_preview"),
            data={
                "project_scope": ["tag"],
                "start_month": "2024-01-01",
                "end_month": "2024-01-31",
                "total_amount": 1000,
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_contribution_preview_negative_individual_adjustment_returns_400(self):
        """Preview should reject negative individual adjustments with a clear error."""
        response = self.client.post(
            reverse("points:api_contribution_preview"),
            data={
                "project_scope": {"tags": ["tag"]},
                "start_month": "2024-01-01",
                "end_month": "2024-01-31",
                "total_amount": 1000,
                "individual_adjustments": {"someone": -1},
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "individual_adjustments 的值必须是大于等于 0 的整数。",
        )

    def test_contribution_preview_runtime_error_is_sanitized(self):
        """Runtime failures should not leak internal preview details."""
        with patch(
            "points.views.AllocationService.preview_allocation",
            side_effect=RuntimeError("SELECT * FROM dangerous_table"),
        ):
            response = self.client.post(
                reverse("points:api_contribution_preview"),
                data={
                    "project_scope": {"tags": ["tag"]},
                    "start_month": "2024-01-01",
                    "end_month": "2024-01-31",
                    "total_amount": 1000,
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "无法生成贡献预览，请检查请求参数后重试。",
        )

    def test_contribution_preview_requires_csrf(self):
        """Session-authenticated preview POSTs should still enforce CSRF."""
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.login(username="preview-error-user", password="testpass")

        with (
            patch(
                "points.allocation_services.AllocationService.preview_allocation",
                return_value=[],
            ),
            patch("chdb.services.get_label_users", return_value={}),
        ):
            response = csrf_client.post(
                reverse("points:api_contribution_preview"),
                data={
                    "project_scope": {"tags": ["tag"]},
                    "start_month": "2024-01-01",
                    "end_month": "2024-01-31",
                    "total_amount": 1000,
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 403)


class AllocationPayloadParsingTests(TestCase):
    """Tests for allocation payload parsing helpers."""

    def test_parse_individual_adjustments_normalizes_keys(self):
        """Valid individual adjustments should be normalized to string keys."""
        self.assertEqual(
            views._parse_individual_adjustments({123: 5}),
            {"123": 5},
        )


class AllocationExecuteAPIViewTests(TestCase):
    """Tests for AllocationExecuteAPIView."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="execute-user",
            password="testpass",
        )
        self.client = Client()
        self.client.login(username="execute-user", password="testpass")
        services.grant_points(self.user, 1000, PointType.GIFT, "Initial pool")
        self.pool = self.user.point_wallet.sources.first()

    def test_allocation_execute_requires_login(self):
        """Execute API should require authentication."""
        self.client.logout()

        response = self.client.post(
            reverse("points:api_allocation_execute"),
            data={
                "pool_id": self.pool.id,
                "total_amount": 300,
                "project_scope": {"tags": ["test-repo"], "operation": "AND"},
                "start_month": "2024-01-01",
                "end_month": "2024-01-31",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 302)

    def test_allocation_execute_api_creates_allocation_and_returns_result(self):
        """Test execute API creates an allocation before dispatching work."""
        mock_preview = [
            {
                "actor_id": "1",
                "actor_login": "alice",
                "platform": "github",
                "email": "alice@example.com",
                "is_registered": True,
                "user_id": 1,
                "contribution_score": 1.0,
            }
        ]
        with (
            patch(
                "points.views.AllocationService.preview_allocation",
                return_value=mock_preview,
            ),
            patch(
                "points.views.AllocationService.execute_allocation",
                return_value={
                    "success": 1,
                    "pending": 0,
                    "failed": 0,
                    "total_points": 300,
                },
            ),
        ):
            response = self.client.post(
                reverse("points:api_allocation_execute"),
                data={
                    "pool_id": self.pool.id,
                    "total_amount": 300,
                    "project_scope": {"tags": ["test-repo"], "operation": "AND"},
                    "start_month": "2024-01-01",
                    "end_month": "2024-01-31",
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["success"], 1)
        allocation = PointAllocation.objects.get(id=data["allocation_id"])
        self.assertEqual(allocation.source_pool_id, self.pool.id)
        self.assertEqual(allocation.initiator_id, self.user.id)
        self.assertEqual(
            set(data.keys()),
            {"allocation_id", "success", "pending", "failed", "total_points"},
        )

    def test_allocation_execute_api_invalid_payload_returns_400(self):
        """Test malformed execute payloads are rejected with a JSON error."""
        response = self.client.post(
            reverse("points:api_allocation_execute"),
            data="{invalid json",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_allocation_execute_get_is_not_allowed(self):
        """Execute endpoint should reject GET requests."""
        response = self.client.get(reverse("points:api_allocation_execute"))

        self.assertEqual(response.status_code, 405)

    def test_allocation_execute_missing_required_field_returns_400(self):
        """Missing execute payload fields should be reported as JSON errors."""
        response = self.client.post(
            reverse("points:api_allocation_execute"),
            data={
                "pool_id": self.pool.id,
                "project_scope": {"tags": ["test-repo"], "operation": "AND"},
                "start_month": "2024-01-01",
                "end_month": "2024-01-31",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_allocation_execute_invalid_date_returns_400(self):
        """Invalid execute dates should surface as JSON validation errors."""
        response = self.client.post(
            reverse("points:api_allocation_execute"),
            data={
                "pool_id": self.pool.id,
                "total_amount": 300,
                "project_scope": {"tags": ["test-repo"], "operation": "AND"},
                "start_month": "not-a-date",
                "end_month": "2024-01-31",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_allocation_execute_non_dict_project_scope_returns_400(self):
        """Execute payload should reject non-object project scopes."""
        response = self.client.post(
            reverse("points:api_allocation_execute"),
            data={
                "pool_id": self.pool.id,
                "total_amount": 300,
                "project_scope": ["test-repo"],
                "start_month": "2024-01-01",
                "end_month": "2024-01-31",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_allocation_execute_missing_pool_returns_sanitized_message(self):
        """Missing pools should return a safe client-facing message."""
        response = self.client.post(
            reverse("points:api_allocation_execute"),
            data={
                "pool_id": self.pool.id + 9999,
                "total_amount": 300,
                "project_scope": {"tags": ["test-repo"], "operation": "AND"},
                "start_month": "2024-01-01",
                "end_month": "2024-01-31",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "积分池不存在。")

    def test_allocation_execute_runtime_error_is_sanitized(self):
        """Runtime failures should not expose internal allocation details."""
        with patch(
            "points.views.AllocationService.execute_allocation",
            side_effect=RuntimeError("syntax error at or near users"),
        ):
            response = self.client.post(
                reverse("points:api_allocation_execute"),
                data={
                    "pool_id": self.pool.id,
                    "total_amount": 300,
                    "project_scope": {"tags": ["test-repo"], "operation": "AND"},
                    "start_month": "2024-01-01",
                    "end_month": "2024-01-31",
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "积分分配执行失败，请检查请求参数后重试。",
        )

    def test_allocation_execute_insufficient_points_returns_business_error(self):
        """Business failures should return a client-handleable JSON error."""
        with patch(
            "points.views.AllocationService.execute_allocation",
            side_effect=services.InsufficientPointsError("积分池余额不足。"),
        ):
            response = self.client.post(
                reverse("points:api_allocation_execute"),
                data={
                    "pool_id": self.pool.id,
                    "total_amount": 300,
                    "project_scope": {"tags": ["test-repo"], "operation": "AND"},
                    "start_month": "2024-01-01",
                    "end_month": "2024-01-31",
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "积分池余额不足。")

    def test_allocation_execute_negative_individual_adjustment_returns_400(self):
        """Execute should reject negative individual adjustments before creation."""
        initial_count = PointAllocation.objects.count()

        response = self.client.post(
            reverse("points:api_allocation_execute"),
            data={
                "pool_id": self.pool.id,
                "total_amount": 300,
                "project_scope": {"tags": ["test-repo"], "operation": "AND"},
                "start_month": "2024-01-01",
                "end_month": "2024-01-31",
                "individual_adjustments": {"someone": -1},
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "individual_adjustments 的值必须是大于等于 0 的整数。",
        )
        self.assertEqual(PointAllocation.objects.count(), initial_count)

    def test_allocation_execute_rejects_other_users_pool(self):
        """Users should not be able to execute allocations from someone else's pool."""
        other_user = User.objects.create_user(
            username="pool-owner", password="testpass"
        )
        services.grant_points(other_user, 500, PointType.GIFT, "Other pool")
        other_pool = other_user.point_wallet.sources.first()

        with patch("points.views.AllocationService.execute_allocation") as execute_mock:
            response = self.client.post(
                reverse("points:api_allocation_execute"),
                data={
                    "pool_id": other_pool.id,
                    "total_amount": 300,
                    "project_scope": {"tags": ["test-repo"], "operation": "AND"},
                    "start_month": "2024-01-01",
                    "end_month": "2024-01-31",
                },
                content_type="application/json",
            )

        self.assertIn(response.status_code, {400, 403})
        execute_mock.assert_not_called()
        self.assertFalse(
            PointAllocation.objects.filter(
                initiator_id=self.user.id,
                source_pool_id=other_pool.id,
            ).exists()
        )

    def test_allocation_execute_rejects_org_pool_for_non_admin_member(self):
        """Regular members should not be able to execute allocations from org pools."""
        org = Organization.objects.create(name="Execute Org", slug="execute-org")
        member = User.objects.create_user(username="org-member", password="testpass")
        OrganizationMembership.objects.create(
            user=member,
            organization=org,
            role=OrganizationMembership.Role.MEMBER,
        )
        services.grant_points(org, 800, PointType.GIFT, "Org pool")
        org_pool = org.point_wallet.sources.first()
        self.client.login(username="org-member", password="testpass")

        with patch("points.views.AllocationService.execute_allocation") as execute_mock:
            response = self.client.post(
                reverse("points:api_allocation_execute"),
                data={
                    "pool_id": org_pool.id,
                    "total_amount": 300,
                    "project_scope": {"tags": ["test-repo"], "operation": "AND"},
                    "start_month": "2024-01-01",
                    "end_month": "2024-01-31",
                },
                content_type="application/json",
            )

        self.assertIn(response.status_code, {400, 403})
        execute_mock.assert_not_called()
        self.assertFalse(
            PointAllocation.objects.filter(
                initiator_id=member.id,
                source_pool_id=org_pool.id,
            ).exists()
        )

    def test_allocation_execute_requires_csrf(self):
        """Session-authenticated execute POSTs should still enforce CSRF."""
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.login(username="execute-user", password="testpass")

        with patch(
            "points.views.AllocationService.execute_allocation",
            return_value={"success": 1, "pending": 0, "failed": 0, "total_points": 300},
        ):
            response = csrf_client.post(
                reverse("points:api_allocation_execute"),
                data={
                    "pool_id": self.pool.id,
                    "total_amount": 300,
                    "project_scope": {"tags": ["test-repo"], "operation": "AND"},
                    "start_month": "2024-01-01",
                    "end_month": "2024-01-31",
                },
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 403)

    def test_can_use_source_pool_rejects_unexpected_owner_types(self):
        """Pools with unsupported owners should be rejected defensively."""
        source_pool = SimpleNamespace(wallet=SimpleNamespace(owner=object()))

        self.assertFalse(
            views.AllocationExecuteAPIView._can_use_source_pool(
                self.user,
                source_pool,
            )
        )


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
