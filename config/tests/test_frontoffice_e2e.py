"""Browser E2E coverage for core user-facing journeys."""

import re
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings, tag
from django.urls import reverse

from accounts.models import (
    AccountMergeRequest,
    Organization,
    OrganizationMembership,
    UserProfile,
)
from common.test_utils import BrowserE2ETestCase
from messages.models import UserMessage
from messages.services import send_message
from points import services as points_services
from points.models import PointType, WithdrawalStatus
from shop.models import Redemption, ShopItem

User = get_user_model()


@tag("e2e")
@override_settings(
    DEBUG=True,
    ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver", "[::1]"],
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    FRONTEND_APP_URL="",
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    },
)
class FrontOfficeE2ETests(BrowserE2ETestCase):
    """High-value browser journeys across the main user flows."""

    def test_registration_profile_public_profile_and_login_journey(self):
        self.goto("/")
        self.page.locator("a[href='/accounts/signup/']").first.click()
        self.page.fill("#username", "e2e-new-user")
        self.page.fill("#email", "e2e-new-user@example.com")
        self.page.fill("#password1", "ComplexPass123!")
        self.page.fill("#password2", "ComplexPass123!")
        self.page.locator("form button[type='submit']").click()
        self.page.wait_for_url(re.compile(r".*/$"))

        self.assertTrue(User.objects.filter(username="e2e-new-user").exists())

        self.goto(reverse("accounts:profile_edit"))
        self.page.fill("#id_bio", "Browser-driven profile update")
        self.page.fill("#id_company", "OpenShare Labs")
        self.page.fill("#id_location", "Shanghai")
        self.page.fill("#id_github_url", "https://github.com/e2e-new-user")
        self.page.locator("button[type='submit']:has-text('保存更改')").click()
        self.page.wait_for_url(re.compile(r".*/accounts/profile/$"))

        self.assert_page_contains("Browser-driven profile update")
        self.assert_page_contains("OpenShare Labs")
        self.goto("/e2e-new-user/")
        self.assert_page_contains("Browser-driven profile update")
        self.assert_page_contains("OpenShare Labs")

        self.goto(reverse("accounts:logout"))
        self.page.wait_for_url(re.compile(r".*/$"))
        self.login_via_ui("e2e-new-user", "ComplexPass123!")
        self.page.wait_for_url(re.compile(r".*/accounts/profile/$"))
        self.assert_page_contains("e2e-new-user")

    def test_password_reset_journey(self):
        user = User.objects.create_user(
            username="reset-user",
            email="reset-user@example.com",
            password="OldPass123!",
        )

        def send_reset_now(user_id, domain, use_https):
            from accounts.tasks import send_password_reset_email

            send_password_reset_email.func(user_id, domain, use_https)

        with patch(
            "accounts.views.send_password_reset_email",
            new=SimpleNamespace(enqueue=send_reset_now),
        ):
            self.goto(reverse("accounts:password_reset_request"))
            self.page.fill("input[name='email']", user.email)
            self.page.locator("form button[type='submit']").click()
            self.page.wait_for_url(re.compile(r".*/accounts/password-reset/done/$"))

        self.assertEqual(len(mail.outbox), 1)
        reset_url = re.search(r"http://[^\s]+", mail.outbox[0].body).group(0)

        self.goto(reset_url)
        self.page.fill("#id_new_password1", "NewPass123!")
        self.page.fill("#id_new_password2", "NewPass123!")
        self.page.locator("button[type='submit']").click()
        self.page.wait_for_url(re.compile(r".*/accounts/login/$"))

        user.refresh_from_db()
        self.assertTrue(user.check_password("NewPass123!"))

        self.login_via_ui("reset-user", "NewPass123!")
        self.page.wait_for_url(re.compile(r".*/accounts/profile/$"))
        self.assert_page_contains("reset-user")

    def test_homepage_search_filters_refresh_after_profile_update(self):
        alice = User.objects.create_user(
            username="search-cache-alice",
            email="search-cache-alice@example.com",
            password="SearchPass123!",
        )
        UserProfile.objects.create(
            user=alice,
            bio="Searchable profile",
            company="Cache Labs",
            location="Shanghai",
        )
        bob = User.objects.create_user(
            username="search-cache-bob",
            email="search-cache-bob@example.com",
            password="SearchPass123!",
        )
        UserProfile.objects.create(
            user=bob,
            bio="Another profile",
            company="Cache Labs",
            location="Beijing",
        )

        self.goto("/search/?q=search-cache")

        self.page.select_option("#filter-location", "Shanghai")
        self.page.locator("button[type='submit']:has-text('应用筛选')").click()
        self.page.wait_for_load_state("networkidle")
        self.assert_page_contains("search-cache-alice")

        profile = alice.profile
        profile.location = "Shenzhen"
        profile.save(update_fields=["location"])

        self.goto("/search/?q=search-cache&location=Shanghai")
        self.assert_page_contains("暂无匹配的用户")

    def test_invalid_password_reset_link_shows_expired_state(self):
        self.goto(reverse("accounts:password_reset_confirm", args=["invalid", "bad"]))

        self.assert_page_contains("链接无效或已过期")
        self.assertEqual(self.page.locator("#id_new_password1").count(), 0)

    def test_shipping_redemption_wallet_and_withdrawal_journey(self):
        user = User.objects.create_user(
            username="shop-user",
            email="shop-user@example.com",
            password="ShopPass123!",
        )
        points_services.grant_points(
            user,
            1200,
            PointType.GIFT,
            "Redeemable points",
            created_by=user,
        )
        points_services.grant_points(
            user,
            800,
            PointType.CASH,
            "Withdrawable points",
            created_by=user,
        )
        item = ShopItem.objects.create(
            name="OpenShare Hoodie",
            description="Shipped reward",
            cost=200,
            stock=3,
            is_active=True,
            requires_shipping=True,
        )

        self.login_via_ui("shop-user", "ShopPass123!")
        self.goto(reverse("accounts:shop_list"))
        self.goto(reverse("accounts:redeem_confirm", args=[item.id]))
        self.page.wait_for_url(
            re.compile(
                rf".*{reverse('accounts:shipping_address_create_guide', args=[item.id])}$"
            )
        )

        self.page.fill("#id_receiver_name", "张三")
        self.page.fill("#id_phone", "13800138000")
        self.page.fill("#id_province", "上海市")
        self.page.fill("#id_city", "上海市")
        self.page.fill("#id_district", "浦东新区")
        self.page.fill("#id_address", "世纪大道 100 号")
        self.page.check("#id_is_default")
        self.page.locator("button[type='submit']:has-text('保存并继续兑换')").click()
        self.page.wait_for_url(
            re.compile(rf".*{reverse('accounts:redeem_confirm', args=[item.id])}$")
        )

        self.page.locator("button[type='submit']:has-text('确认兑换')").click()
        self.page.wait_for_url(re.compile(r".*/accounts/redemption/$"))

        self.assert_page_contains("OpenShare Hoodie")
        self.assertTrue(
            Redemption.objects.filter(user_profile=user, item=item).exists()
        )

        self.goto(reverse("points:user_wallet"))
        self.assert_page_contains("兑换商品: OpenShare Hoodie")

        self.goto(reverse("points:create_withdrawal"))
        self.page.fill("#id_amount", "300")
        self.page.fill("#id_real_name", "张三")
        self.page.fill("#id_phone", "13800138000")
        self.page.fill("#id_id_card", "11010519491231002X")
        self.page.fill("#id_bank_name", "中国银行")
        self.page.fill("#id_bank_account", "6222000000000000000")
        self.page.locator("button[type='submit']:has-text('提交申请')").click()
        self.page.wait_for_url(re.compile(r".*/points/withdrawals/$"))

        withdrawal = user.point_wallet.withdrawals.get()
        self.assertEqual(withdrawal.status, WithdrawalStatus.PENDING)
        self.assert_page_contains("待审核")

        self.page.on("dialog", lambda dialog: dialog.accept())
        self.page.locator("button:has-text('取消')").click()
        self.page.wait_for_load_state("networkidle")

        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, WithdrawalStatus.CANCELLED)
        self.assertEqual(points_services.get_balance(user, PointType.CASH), 800)
        self.assert_page_contains("已取消")

    def test_message_center_journey(self):
        user = User.objects.create_user(
            username="message-user",
            email="message-user@example.com",
            password="MessagePass123!",
        )
        message = send_message(
            title="系统通知",
            content="请查看这条消息",
            recipients=[user],
        )
        user_message = UserMessage.objects.get(user=user, message=message)

        self.login_via_ui("message-user", "MessagePass123!")
        self.goto(reverse("messages:list"))
        self.page.locator(f"text={message.title}").click()
        self.page.wait_for_url(
            re.compile(rf".*{reverse('messages:detail', args=[message.id])}$")
        )
        self.page.wait_for_load_state("networkidle")

        self.wait_for_database(
            lambda: self.assertTrue(UserMessage.objects.get(pk=user_message.pk).is_read)
        )

        self.goto(reverse("messages:list"))
        self.page.locator("#selectAll").click()
        with self.page.expect_response(
            lambda response: (
                reverse("messages:mark_unread") in response.url
                and response.status == 200
            )
        ):
            self.page.locator("#markUnreadBtn").click()
        self.page.wait_for_load_state("networkidle")

        self.wait_for_database(
            lambda: self.assertFalse(
                UserMessage.objects.get(pk=user_message.pk).is_read
            )
        )

        self.page.locator("#selectAll").click()
        self.page.on("dialog", lambda dialog: dialog.accept())
        with self.page.expect_response(
            lambda response: (
                reverse("messages:delete") in response.url and response.status == 200
            )
        ):
            self.page.locator("#deleteBtn").click()
        self.page.wait_for_load_state("networkidle")

        self.wait_for_database(
            lambda: self.assertTrue(
                UserMessage.objects.get(pk=user_message.pk).is_deleted
            )
        )

    def test_organization_management_journey(self):
        owner = User.objects.create_user(
            username="org-owner",
            email="org-owner@example.com",
            password="OrgPass123!",
        )
        member = User.objects.create_user(
            username="org-member",
            email="org-member@example.com",
            password="OrgPass123!",
        )

        self.login_via_ui("org-owner", "OrgPass123!")
        self.goto(reverse("accounts:organization_create"))
        self.page.fill("#id_name", "Browser Org")
        self.page.fill("#id_slug", "browser-org")
        self.page.fill("#id_description", "Created from browser E2E")
        self.page.fill("#id_location", "Hangzhou")
        self.page.locator("button[type='submit']:has-text('创建组织')").click()
        self.page.wait_for_url(re.compile(r".*/accounts/organizations/browser-org/$"))

        org = Organization.objects.get(slug="browser-org")
        points_services.grant_points(
            org,
            900,
            PointType.CASH,
            "Organization seed points",
            created_by=owner,
        )

        self.assert_page_contains("Browser Org")
        self.page.locator(
            f"a[href='{reverse('accounts:organization_members', args=[org.slug])}']"
        ).click()
        self.page.fill("#username", member.username)
        self.page.select_option("#role", OrganizationMembership.Role.ADMIN)
        self.page.locator("button[type='submit']:has-text('添加成员')").click()
        self.page.wait_for_load_state("networkidle")

        self.assert_page_contains(member.username)
        self.goto(reverse("accounts:organization_detail", args=[org.slug]))
        self.page.locator(
            f"a[href='{reverse('points:org_wallet', args=[org.slug])}']"
        ).click()
        self.page.wait_for_url(
            re.compile(rf".*{reverse('points:org_wallet', args=[org.slug])}$")
        )

        self.assert_page_contains("900")
        self.assert_page_contains("完整记录")

    def test_account_merge_journey(self):
        source = User.objects.create_user(
            username="merge-e2e-source",
            email="merge-e2e-source@example.com",
            password="MergePass123!",
        )
        target = User.objects.create_user(
            username="merge-e2e-target",
            email="merge-e2e-target@example.com",
            password="MergePass123!",
        )
        organization = Organization.objects.create(name="Merge Org", slug="merge-org")
        OrganizationMembership.objects.create(
            user=source,
            organization=organization,
            role=OrganizationMembership.Role.MEMBER,
        )

        self.login_via_ui(source.username, "MergePass123!")
        self.goto(reverse("accounts:merge_request"))
        self.page.fill("input[name='target_username']", target.username)
        self.page.locator("button[type='submit']:has-text('提交申请')").click()
        self.page.wait_for_load_state("networkidle")
        merge_request = AccountMergeRequest.objects.get(source_user=source)

        self.assertTrue(
            UserMessage.objects.filter(
                user=target,
                message__title="账号合并申请",
            ).exists()
        )

        target_context, target_page = self.new_context_page()
        try:
            target_page.goto(
                self.absolute_url("/accounts/login/"), wait_until="networkidle"
            )
            target_page.fill("#login-id", target.username)
            target_page.fill("#password", "MergePass123!")
            target_page.locator("form#loginForm button[type='submit']").click()
            target_page.wait_for_load_state("networkidle")

            target_page.goto(
                self.absolute_url(reverse("accounts:merge_request")),
                wait_until="networkidle",
            )
            target_page.locator(
                f"a[href='{reverse('accounts:merge_review', args=[merge_request.approve_token])}']"
            ).click()
            target_page.wait_for_load_state("networkidle")
            target_page.locator("button[type='submit']:has-text('同意并合并')").click()
            target_page.wait_for_load_state("networkidle")
        finally:
            target_context.close()

        source.refresh_from_db()
        self.assertFalse(source.is_active)
        self.assertEqual(source.merged_into, target)
