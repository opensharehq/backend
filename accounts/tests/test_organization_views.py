"""Tests for Organization views."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Organization, OrganizationMembership

User = get_user_model()


class OrganizationListViewTests(TestCase):
    """Test cases for organization list view."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )
        self.org1 = Organization.objects.create(
            name="Test Org 1",
            slug="test-org-1",
            provider="github",
            provider_id="123",
            provider_login="test-org-1",
        )
        self.org2 = Organization.objects.create(
            name="Test Org 2",
            slug="test-org-2",
            provider="github",
            provider_id="456",
            provider_login="test-org-2",
        )
        OrganizationMembership.objects.create(
            user=self.user,
            organization=self.org1,
            role=OrganizationMembership.Role.MEMBER,
        )
        OrganizationMembership.objects.create(
            user=self.user,
            organization=self.org2,
            role=OrganizationMembership.Role.ADMIN,
        )

    def test_organization_list_requires_login(self):
        """Test that organization list view requires login."""
        response = self.client.get(reverse("accounts:organization_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_organization_list_shows_user_organizations(self):
        """Test that organization list shows only user's organizations."""
        self.client.login(username="testuser", password="password123")
        response = self.client.get(reverse("accounts:organization_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Org 1")
        self.assertContains(response, "Test Org 2")

    def test_organization_list_empty_state(self):
        """Test organization list shows empty state when user has no organizations."""
        User.objects.create_user(
            username="user2", email="user2@example.com", password="password123"
        )
        self.client.login(username="user2", password="password123")
        response = self.client.get(reverse("accounts:organization_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "暂无组织")

    def test_organization_list_shows_sync_button_when_social_connected(self):
        """Test that sync button appears when user has connected social accounts."""
        from social_django.models import UserSocialAuth

        # Create a social auth connection
        UserSocialAuth.objects.create(
            user=self.user,
            provider="github",
            uid="123456",
        )

        self.client.login(username="testuser", password="password123")
        response = self.client.get(reverse("accounts:organization_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "同步组织")
        self.assertContains(response, "从 GitHub 同步")

    def test_organization_list_no_sync_button_without_social(self):
        """Test that sync button is hidden when user has no connected social accounts."""
        self.client.login(username="testuser", password="password123")
        response = self.client.get(reverse("accounts:organization_list"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "同步组织")


class OrganizationDetailViewTests(TestCase):
    """Test cases for organization detail view."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )
        self.member_user = User.objects.create_user(
            username="member", email="member@example.com", password="password123"
        )
        self.non_member_user = User.objects.create_user(
            username="nonmember", email="nonmember@example.com", password="password123"
        )
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org",
            provider="github",
            provider_id="123",
            provider_login="test-org",
        )
        OrganizationMembership.objects.create(
            user=self.user,
            organization=self.org,
            role=OrganizationMembership.Role.ADMIN,
        )
        OrganizationMembership.objects.create(
            user=self.member_user,
            organization=self.org,
            role=OrganizationMembership.Role.MEMBER,
        )

    def test_organization_detail_requires_login(self):
        """Test that organization detail view requires login."""
        response = self.client.get(
            reverse("accounts:organization_detail", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_organization_detail_requires_membership(self):
        """Test that organization detail requires user to be a member."""
        self.client.login(username="nonmember", password="password123")
        response = self.client.get(
            reverse("accounts:organization_detail", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 403)

    def test_organization_detail_shows_org_info(self):
        """Test that organization detail shows organization information."""
        self.client.login(username="testuser", password="password123")
        response = self.client.get(
            reverse("accounts:organization_detail", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Organization")
        self.assertContains(response, "test-org")

    def test_organization_detail_shows_members(self):
        """Test that organization detail shows member list."""
        self.client.login(username="testuser", password="password123")
        response = self.client.get(
            reverse("accounts:organization_detail", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "testuser")
        self.assertContains(response, "member")

    def test_organization_detail_shows_admin_links_to_admins(self):
        """Test that admin links are shown to admins."""
        self.client.login(username="testuser", password="password123")
        response = self.client.get(
            reverse("accounts:organization_detail", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "成员管理")
        self.assertContains(response, "组织设置")

    def test_organization_detail_hides_admin_links_from_members(self):
        """Test that admin links are hidden from regular members."""
        self.client.login(username="member", password="password123")
        response = self.client.get(
            reverse("accounts:organization_detail", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "成员管理")
        self.assertNotContains(response, "组织设置")


class OrganizationSettingsViewTests(TestCase):
    """Test cases for organization settings view."""

    def setUp(self):
        """Set up test fixtures."""
        self.admin_user = User.objects.create_user(
            username="admin", email="admin@example.com", password="password123"
        )
        self.member_user = User.objects.create_user(
            username="member", email="member@example.com", password="password123"
        )
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org",
            provider="github",
            provider_id="123",
            provider_login="test-org",
        )
        OrganizationMembership.objects.create(
            user=self.admin_user,
            organization=self.org,
            role=OrganizationMembership.Role.ADMIN,
        )
        OrganizationMembership.objects.create(
            user=self.member_user,
            organization=self.org,
            role=OrganizationMembership.Role.MEMBER,
        )

    def test_organization_settings_requires_login(self):
        """Test that organization settings view requires login."""
        response = self.client.get(
            reverse("accounts:organization_settings", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_organization_settings_requires_admin(self):
        """Test that organization settings requires admin permissions."""
        self.client.login(username="member", password="password123")
        response = self.client.get(
            reverse("accounts:organization_settings", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 403)

    def test_organization_settings_shows_form(self):
        """Test that organization settings shows edit form."""
        self.client.login(username="admin", password="password123")
        response = self.client.get(
            reverse("accounts:organization_settings", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Organization")
        self.assertContains(response, 'name="name"')
        self.assertContains(response, 'name="slug"')

    def test_organization_settings_update_success(self):
        """Test that organization settings can be updated successfully."""
        self.client.login(username="admin", password="password123")
        data = {
            "name": "Updated Organization",
            "slug": "test-org",
            "description": "Updated description",
            "website": "https://example.com",
            "location": "San Francisco",
            "avatar_url": "",
        }
        response = self.client.post(
            reverse("accounts:organization_settings", args=[self.org.slug]), data
        )
        self.assertEqual(response.status_code, 302)
        self.org.refresh_from_db()
        self.assertEqual(self.org.name, "Updated Organization")
        self.assertEqual(self.org.description, "Updated description")
        self.assertEqual(self.org.website, "https://example.com")

    def test_organization_settings_validates_slug_uniqueness(self):
        """Test that slug uniqueness is validated."""
        # Create conflicting organization for slug uniqueness test
        Organization.objects.create(
            name="Org 2",
            slug="org-2",
            provider="github",
            provider_id="456",
            provider_login="org-2",
        )
        self.client.login(username="admin", password="password123")
        data = {
            "name": "Updated Organization",
            "slug": "org-2",
            "description": "",
            "website": "",
            "location": "",
            "avatar_url": "",
        }
        response = self.client.post(
            reverse("accounts:organization_settings", args=[self.org.slug]), data
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "已存在")


class OrganizationMembersViewTests(TestCase):
    """Test cases for organization members view."""

    def setUp(self):
        """Set up test fixtures."""
        self.admin_user = User.objects.create_user(
            username="admin", email="admin@example.com", password="password123"
        )
        self.member_user = User.objects.create_user(
            username="member", email="member@example.com", password="password123"
        )
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org",
            provider="github",
            provider_id="123",
            provider_login="test-org",
        )
        self.admin_membership = OrganizationMembership.objects.create(
            user=self.admin_user,
            organization=self.org,
            role=OrganizationMembership.Role.ADMIN,
        )
        self.member_membership = OrganizationMembership.objects.create(
            user=self.member_user,
            organization=self.org,
            role=OrganizationMembership.Role.MEMBER,
        )

    def test_organization_members_requires_login(self):
        """Test that organization members view requires login."""
        response = self.client.get(
            reverse("accounts:organization_members", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_organization_members_requires_admin(self):
        """Test that organization members requires admin permissions."""
        self.client.login(username="member", password="password123")
        response = self.client.get(
            reverse("accounts:organization_members", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 403)

    def test_organization_members_shows_member_list(self):
        """Test that organization members shows all members."""
        self.client.login(username="admin", password="password123")
        response = self.client.get(
            reverse("accounts:organization_members", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "admin")
        self.assertContains(response, "member")

    def test_organization_members_shows_role_actions(self):
        """Test that role action buttons are displayed."""
        self.client.login(username="admin", password="password123")
        response = self.client.get(
            reverse("accounts:organization_members", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "更改角色")
        self.assertContains(response, "移除")


class OrganizationMemberUpdateRoleViewTests(TestCase):
    """Test cases for organization member update role view."""

    def setUp(self):
        """Set up test fixtures."""
        self.owner_user = User.objects.create_user(
            username="owner", email="owner@example.com", password="password123"
        )
        self.admin_user = User.objects.create_user(
            username="admin", email="admin@example.com", password="password123"
        )
        self.member_user = User.objects.create_user(
            username="member", email="member@example.com", password="password123"
        )
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org",
            provider="github",
            provider_id="123",
            provider_login="test-org",
        )
        self.owner_membership = OrganizationMembership.objects.create(
            user=self.owner_user,
            organization=self.org,
            role=OrganizationMembership.Role.OWNER,
        )
        self.admin_membership = OrganizationMembership.objects.create(
            user=self.admin_user,
            organization=self.org,
            role=OrganizationMembership.Role.ADMIN,
        )
        self.member_membership = OrganizationMembership.objects.create(
            user=self.member_user,
            organization=self.org,
            role=OrganizationMembership.Role.MEMBER,
        )

    def test_update_role_requires_login(self):
        """Test that updating role requires login."""
        response = self.client.post(
            reverse(
                "accounts:organization_member_update_role",
                args=[self.org.slug, self.member_membership.id],
            ),
            {"role": "admin"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_update_role_requires_admin(self):
        """Test that updating role requires admin permissions."""
        self.client.login(username="member", password="password123")
        response = self.client.post(
            reverse(
                "accounts:organization_member_update_role",
                args=[self.org.slug, self.admin_membership.id],
            ),
            {"role": "member"},
        )
        self.assertEqual(response.status_code, 403)

    def test_update_role_success(self):
        """Test that role can be updated successfully."""
        self.client.login(username="owner", password="password123")
        response = self.client.post(
            reverse(
                "accounts:organization_member_update_role",
                args=[self.org.slug, self.member_membership.id],
            ),
            {"role": "admin"},
        )
        self.assertEqual(response.status_code, 302)
        self.member_membership.refresh_from_db()
        self.assertEqual(self.member_membership.role, OrganizationMembership.Role.ADMIN)

    def test_update_role_prevents_demoting_last_owner(self):
        """Test that the last owner cannot be demoted."""
        self.client.login(username="owner", password="password123")
        response = self.client.post(
            reverse(
                "accounts:organization_member_update_role",
                args=[self.org.slug, self.owner_membership.id],
            ),
            {"role": "admin"},
        )
        self.assertEqual(response.status_code, 302)
        self.owner_membership.refresh_from_db()
        # Role should not change
        self.assertEqual(self.owner_membership.role, OrganizationMembership.Role.OWNER)

    def test_update_role_allows_demoting_owner_when_multiple_owners(self):
        """Test that an owner can be demoted when there are multiple owners."""
        # Add another owner
        user2 = User.objects.create_user(
            username="owner2", email="owner2@example.com", password="password123"
        )
        OrganizationMembership.objects.create(
            user=user2, organization=self.org, role=OrganizationMembership.Role.OWNER
        )

        self.client.login(username="owner", password="password123")
        response = self.client.post(
            reverse(
                "accounts:organization_member_update_role",
                args=[self.org.slug, self.owner_membership.id],
            ),
            {"role": "admin"},
        )
        self.assertEqual(response.status_code, 302)
        self.owner_membership.refresh_from_db()
        self.assertEqual(self.owner_membership.role, OrganizationMembership.Role.ADMIN)


class OrganizationMemberRemoveViewTests(TestCase):
    """Test cases for organization member remove view."""

    def setUp(self):
        """Set up test fixtures."""
        self.owner_user = User.objects.create_user(
            username="owner", email="owner@example.com", password="password123"
        )
        self.admin_user = User.objects.create_user(
            username="admin", email="admin@example.com", password="password123"
        )
        self.member_user = User.objects.create_user(
            username="member", email="member@example.com", password="password123"
        )
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org",
            provider="github",
            provider_id="123",
            provider_login="test-org",
        )
        self.owner_membership = OrganizationMembership.objects.create(
            user=self.owner_user,
            organization=self.org,
            role=OrganizationMembership.Role.OWNER,
        )
        self.admin_membership = OrganizationMembership.objects.create(
            user=self.admin_user,
            organization=self.org,
            role=OrganizationMembership.Role.ADMIN,
        )
        self.member_membership = OrganizationMembership.objects.create(
            user=self.member_user,
            organization=self.org,
            role=OrganizationMembership.Role.MEMBER,
        )

    def test_remove_member_requires_login(self):
        """Test that removing member requires login."""
        response = self.client.post(
            reverse(
                "accounts:organization_member_remove",
                args=[self.org.slug, self.member_membership.id],
            )
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_remove_member_requires_admin(self):
        """Test that removing member requires admin permissions."""
        self.client.login(username="member", password="password123")
        response = self.client.post(
            reverse(
                "accounts:organization_member_remove",
                args=[self.org.slug, self.admin_membership.id],
            )
        )
        self.assertEqual(response.status_code, 403)

    def test_remove_member_success(self):
        """Test that member can be removed successfully."""
        self.client.login(username="owner", password="password123")
        response = self.client.post(
            reverse(
                "accounts:organization_member_remove",
                args=[self.org.slug, self.member_membership.id],
            )
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            OrganizationMembership.objects.filter(id=self.member_membership.id).exists()
        )

    def test_remove_member_prevents_removing_last_owner(self):
        """Test that the last owner cannot be removed."""
        self.client.login(username="owner", password="password123")
        response = self.client.post(
            reverse(
                "accounts:organization_member_remove",
                args=[self.org.slug, self.owner_membership.id],
            )
        )
        self.assertEqual(response.status_code, 302)
        # Owner should still exist
        self.assertTrue(
            OrganizationMembership.objects.filter(id=self.owner_membership.id).exists()
        )

    def test_remove_member_allows_removing_owner_when_multiple_owners(self):
        """Test that an owner can be removed when there are multiple owners."""
        # Add another owner
        user2 = User.objects.create_user(
            username="owner2", email="owner2@example.com", password="password123"
        )
        OrganizationMembership.objects.create(
            user=user2, organization=self.org, role=OrganizationMembership.Role.OWNER
        )

        self.client.login(username="owner", password="password123")
        response = self.client.post(
            reverse(
                "accounts:organization_member_remove",
                args=[self.org.slug, self.owner_membership.id],
            )
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            OrganizationMembership.objects.filter(id=self.owner_membership.id).exists()
        )


class OrganizationSyncViewTests(TestCase):
    """Test cases for organization sync view."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )

    def test_organization_sync_requires_login(self):
        """Test that organization sync view requires login."""
        response = self.client.get(
            reverse("accounts:organization_sync", args=["github"])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_organization_sync_invalid_provider(self):
        """Test that invalid provider is rejected."""
        from django.contrib.messages import get_messages

        self.client.login(username="testuser", password="password123")
        response = self.client.get(
            reverse("accounts:organization_sync", args=["invalid"])
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("accounts:organization_list"))

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("不支持的 OAuth 提供商", str(messages[0]))

    def test_organization_sync_missing_social_account(self):
        """Test that missing social account shows error."""
        from django.contrib.messages import get_messages

        self.client.login(username="testuser", password="password123")
        response = self.client.get(
            reverse("accounts:organization_sync", args=["github"])
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("accounts:social_connections"))

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("您还未连接", str(messages[0]))

    def test_organization_sync_github_success(self):
        """Test successful GitHub organization sync redirect."""
        from django.contrib.messages import get_messages
        from social_django.models import UserSocialAuth

        # Create GitHub social auth
        UserSocialAuth.objects.create(user=self.user, provider="github", uid="123456")

        self.client.login(username="testuser", password="password123")
        response = self.client.get(
            reverse("accounts:organization_sync", args=["github"])
        )

        # Should redirect to OAuth begin
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/github/", response.url)
        self.assertIn("next=", response.url)

        # Should set session flag
        self.assertTrue(self.client.session.get("is_organization_sync"))

        # Should show helpful message for GitHub
        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("Organization access", str(messages[0]))
        self.assertIn("Grant", str(messages[0]))

    def test_organization_sync_gitee_success(self):
        """Test successful Gitee organization sync redirect."""
        from social_django.models import UserSocialAuth

        # Create Gitee social auth
        UserSocialAuth.objects.create(user=self.user, provider="gitee", uid="123456")

        self.client.login(username="testuser", password="password123")
        response = self.client.get(
            reverse("accounts:organization_sync", args=["gitee"])
        )

        # Should redirect to OAuth begin
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/gitee/", response.url)
        self.assertIn("next=", response.url)

        # Should set session flag
        self.assertTrue(self.client.session.get("is_organization_sync"))

    def test_organization_sync_huggingface_success(self):
        """Test successful HuggingFace organization sync redirect."""
        from social_django.models import UserSocialAuth

        # Create HuggingFace social auth
        UserSocialAuth.objects.create(
            user=self.user, provider="huggingface", uid="123456"
        )

        self.client.login(username="testuser", password="password123")
        response = self.client.get(
            reverse("accounts:organization_sync", args=["huggingface"])
        )

        # Should redirect to OAuth begin
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/huggingface/", response.url)
        self.assertIn("next=", response.url)

        # Should set session flag
        self.assertTrue(self.client.session.get("is_organization_sync"))

    def test_organization_sync_includes_next_parameter(self):
        """Test that next parameter is included in OAuth URL."""
        from urllib.parse import parse_qs, urlparse

        from social_django.models import UserSocialAuth

        UserSocialAuth.objects.create(user=self.user, provider="github", uid="123456")

        self.client.login(username="testuser", password="password123")
        response = self.client.get(
            reverse("accounts:organization_sync", args=["github"])
        )

        # Should include next parameter to return to organization list
        parsed = urlparse(response.url)
        query_params = parse_qs(parsed.query)
        self.assertIn("next", query_params)
        self.assertEqual(query_params["next"][0], reverse("accounts:organization_list"))
