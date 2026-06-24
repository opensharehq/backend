"""Browser E2E coverage for key backoffice journeys."""

from django.contrib.auth import get_user_model
from django.test import override_settings, tag
from django.urls import reverse

from accounts.models import Organization
from common.test_utils import BrowserE2ETestCase
from messages.models import UserMessage
from points import services as points_services
from points.models import PointType, Tag

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
        test_tag = Tag.objects.create(name="E2ETag", slug="e2e-tag")

        self.login_admin_via_ui(admin.username, "AdminPass123!")
        self.goto(f"/admin/points/grant-to-users/?ids={recipient.id}")
        # Cash points cannot have a tag - select cash and pick a tag
        self.page.check("input[value='cash']")
        self.page.fill("#id_amount", "10")
        self.page.fill("#id_reason", "Validation case cash with tag")
        self.page.select_option("#id_tag", str(test_tag.id))
        self.page.locator("input[type='submit'][value='提交发放']").click()
        self.page.wait_for_load_state("networkidle")

        self.assertIn(
            "/admin/points/grant-to-users/",
            self.page.url,
        )
        self.assertGreater(self.page.locator("ul.errorlist li").count(), 0)
        self.assertEqual(points_services.get_balance(recipient, PointType.CASH), 0)
