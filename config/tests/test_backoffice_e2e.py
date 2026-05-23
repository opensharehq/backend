"""Browser E2E coverage for key backoffice journeys."""

import re
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings, tag
from django.urls import reverse
from social_django.models import UserSocialAuth

from accounts.models import Organization
from common.test_utils import BrowserE2ETestCase
from messages.models import UserMessage
from points import services as points_services
from points.models import PendingPointGrant, PointAllocation, PointType, Tag

User = get_user_model()


@tag("e2e")
@override_settings(
    DEBUG=True,
    ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver", "[::1]"],
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    },
)
class BackOfficeE2ETests(BrowserE2ETestCase):
    """Backoffice browser flows that exercise real admin and allocation pages."""

    def test_admin_can_grant_points_to_users_and_orgs(self):
        admin = User.objects.create_superuser(
            username="admin-browser",
            email="admin-browser@example.com",
            password="AdminPass123!",
        )
        recipient = User.objects.create_user(
            username="grantee-user",
            email="grantee-user@example.com",
            password="UserPass123!",
        )
        organization = Organization.objects.create(name="Grant Org", slug="grant-org")

        self.login_admin_via_ui(admin.username, "AdminPass123!")

        self.goto(f"/admin/points/grant-to-users/?ids={recipient.id}")
        self.page.check("input[value='cash']")
        self.page.fill("#id_amount", "250")
        self.page.fill("#id_reason", "Browser admin grant to user")
        self.page.locator("input[type='submit'][value='提交发放']").click()
        self.page.wait_for_load_state("networkidle")

        self.assertEqual(points_services.get_balance(recipient, PointType.CASH), 250)

        self.goto(f"/admin/points/grant-to-orgs/?ids={organization.id}")
        self.page.check("input[value='cash']")
        self.page.fill("#id_amount", "400")
        self.page.fill("#id_reason", "Browser admin grant to org")
        self.page.locator("input[type='submit'][value='提交发放']").click()
        self.page.wait_for_load_state("networkidle")

        self.assertEqual(points_services.get_balance(organization, PointType.CASH), 400)

    def test_admin_can_send_targeted_and_broadcast_messages(self):
        admin = User.objects.create_superuser(
            username="message-admin",
            email="message-admin@example.com",
            password="AdminPass123!",
        )
        user_one = User.objects.create_user(
            username="message-target-one",
            email="message-target-one@example.com",
            password="UserPass123!",
        )
        user_two = User.objects.create_user(
            username="message-target-two",
            email="message-target-two@example.com",
            password="UserPass123!",
        )

        self.login_admin_via_ui(admin.username, "AdminPass123!")

        self.goto(reverse("admin:site_messages_message_add"))
        self.page.fill("#id_title", "定向消息")
        self.page.fill("#id_content", "只发给一个用户")
        self.page.locator("#id_recipients_from").wait_for()
        self.page.select_option("#id_recipients_from", str(user_one.id))
        self.page.locator("#id_recipients_add").click()
        self.page.locator("input[name='_save']").click()
        self.page.wait_for_load_state("networkidle")

        self.assertTrue(
            UserMessage.objects.filter(
                user=user_one,
                message__title="定向消息",
            ).exists()
        )
        self.assertFalse(
            UserMessage.objects.filter(
                user=user_two,
                message__title="定向消息",
            ).exists()
        )

        self.goto(reverse("admin:site_messages_message_add"))
        self.page.fill("#id_title", "广播消息")
        self.page.fill("#id_content", "发给所有激活用户")
        self.page.check("#id_is_broadcast")
        self.page.locator("input[name='_save']").click()
        self.page.wait_for_load_state("networkidle")

        self.assertTrue(
            UserMessage.objects.filter(
                user=user_one,
                message__title="广播消息",
            ).exists()
        )
        self.assertTrue(
            UserMessage.objects.filter(
                user=user_two,
                message__title="广播消息",
            ).exists()
        )
        self.assertTrue(
            UserMessage.objects.filter(
                user=admin,
                message__title="广播消息",
            ).exists()
        )

    def test_admin_grant_points_form_validation_errors_are_visible(self):
        admin = User.objects.create_superuser(
            username="admin-validate",
            email="admin-validate@example.com",
            password="AdminPass123!",
        )
        recipient = User.objects.create_user(
            username="validate-recipient",
            email="validate-recipient@example.com",
            password="UserPass123!",
        )

        self.login_admin_via_ui(admin.username, "AdminPass123!")
        self.goto(f"/admin/points/grant-to-users/?ids={recipient.id}")
        self.page.check("input[value='gift']")
        self.page.fill("#id_amount", "10")
        self.page.fill("#id_reason", "Validation case without tag")
        self.page.locator("input[type='submit'][value='提交发放']").click()
        self.page.wait_for_load_state("networkidle")

        self.assertIn(
            "/admin/points/grant-to-users/",
            self.page.url,
        )
        self.assertGreater(self.page.locator("ul.errorlist li").count(), 0)
        self.assertEqual(points_services.get_balance(recipient, PointType.CASH), 0)

    @patch("chdb.services.search_tags", return_value=[])
    def test_allocation_config_handles_empty_search_results(
        self,
        _mock_search_tags,
    ):
        operator = User.objects.create_user(
            username="allocation-empty-search",
            email="allocation-empty-search@example.com",
            password="AllocPass123!",
        )
        source_pool = points_services.grant_points(
            operator,
            500,
            PointType.CASH,
            "Allocation source pool",
            created_by=operator,
        )

        self.login_via_ui(operator.username, "AllocPass123!")
        self.goto(reverse("points:allocation_config"))
        self.page.select_option("#allocation-pool-select", str(source_pool.id))
        self.page.fill("#project-tag-search", "unlikely-keyword")
        self.page.wait_for_timeout(400)

        self.assertEqual(
            self.page.locator(
                "#project-tag-search-results .search-result-item"
            ).count(),
            0,
        )
        self.assertTrue(
            self.page.locator("#preview-contributions-button").is_disabled()
        )

    @patch(
        "chdb.services.search_tags",
        return_value=[
            {
                "id": "demo/project",
                "name": "Demo Project",
                "platform": "GitHub",
                "type": "repo",
                "openrank": 123.45,
            }
        ],
    )
    @patch(
        "chdb.services.get_label_users",
        return_value={"demo/project": {"platforms": ["GitHub"]}},
    )
    @patch(
        "contributions.services.ContributionService.get_contributions",
    )
    def test_allocation_config_preview_and_execute_journey(
        self,
        mock_get_contributions,
        _mock_get_label_users,
        _mock_search_tags,
    ):
        operator = User.objects.create_user(
            username="allocation-operator",
            email="allocation-operator@example.com",
            password="AllocPass123!",
        )
        registered = User.objects.create_user(
            username="registered-recipient",
            email="registered-recipient@example.com",
            password="AllocPass123!",
        )
        UserSocialAuth.objects.create(
            user=registered,
            provider="github",
            uid="1001",
        )
        source_pool = points_services.grant_points(
            operator,
            1000,
            PointType.CASH,
            "Allocation source pool",
            created_by=operator,
        )
        Tag.objects.create(name="Demo Project", slug="demo-project")

        mock_get_contributions.return_value = [
            {
                "platform": "GitHub",
                "actor_id": "1001",
                "actor_login": registered.username,
                "github_login": registered.username,
                "email": registered.email,
                "contribution_score": 2.0,
                "is_registered": True,
                "user_id": registered.id,
            },
            {
                "platform": "GitHub",
                "actor_id": "2002",
                "actor_login": "pending-recipient",
                "github_login": "pending-recipient",
                "email": "pending-recipient@example.com",
                "contribution_score": 1.0,
                "is_registered": False,
                "user_id": None,
            },
        ]

        self.login_via_ui(operator.username, "AllocPass123!")
        self.goto(reverse("points:allocation_config"))
        self.page.select_option("#allocation-pool-select", str(source_pool.id))
        self.page.fill("#allocation-total-amount", "900")
        self.page.fill("#project-tag-search", "demo")
        self.page.locator("#project-tag-search-results .search-result-item").click()
        self.page.locator("#preview-contributions-button").click()
        self.page.locator("#allocation-contributors-table").wait_for()

        self.assert_page_contains(registered.username)
        self.assert_page_contains("pending-recipient")

        self.page.on("dialog", lambda dialog: dialog.accept())
        self.page.locator("#execute-allocation-button").click()
        self.page.wait_for_url(re.compile(r".*/points/wallet/$"))

        allocation = PointAllocation.objects.latest("created_at")
        self.assertEqual(allocation.status, "completed")
        self.assertEqual(points_services.get_balance(registered, PointType.CASH), 600)
        self.assertEqual(
            PendingPointGrant.objects.filter(
                allocation=allocation,
                actor_login="pending-recipient",
            ).count(),
            1,
        )
