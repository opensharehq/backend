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
        )
        self.org2 = Organization.objects.create(
            name="Test Org 2",
            slug="test-org-2",
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


class OrganizationMemberAddViewTests(TestCase):
    """Test cases for organization member add view."""

    def setUp(self):
        """Set up test fixtures."""
        self.admin_user = User.objects.create_user(
            username="admin", email="admin@example.com", password="password123"
        )
        self.member_user = User.objects.create_user(
            username="member", email="member@example.com", password="password123"
        )
        self.new_user = User.objects.create_user(
            username="newuser", email="newuser@example.com", password="password123"
        )
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org",
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

    def test_add_member_requires_login(self):
        """Test that adding member requires login."""
        response = self.client.post(
            reverse("accounts:organization_member_add", args=[self.org.slug]),
            {"username": "newuser", "role": "member"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_add_member_requires_admin(self):
        """Test that adding member requires admin permissions."""
        self.client.login(username="member", password="password123")
        response = self.client.post(
            reverse("accounts:organization_member_add", args=[self.org.slug]),
            {"username": "newuser", "role": "member"},
        )
        self.assertEqual(response.status_code, 403)

    def test_add_member_success(self):
        """Test that member can be added successfully."""
        self.client.login(username="admin", password="password123")
        response = self.client.post(
            reverse("accounts:organization_member_add", args=[self.org.slug]),
            {"username": "newuser", "role": "member"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            OrganizationMembership.objects.filter(
                user=self.new_user, organization=self.org
            ).exists()
        )
        membership = OrganizationMembership.objects.get(
            user=self.new_user, organization=self.org
        )
        self.assertEqual(membership.role, OrganizationMembership.Role.MEMBER)

    def test_add_member_with_admin_role(self):
        """Test that member can be added as admin."""
        self.client.login(username="admin", password="password123")
        response = self.client.post(
            reverse("accounts:organization_member_add", args=[self.org.slug]),
            {"username": "newuser", "role": "admin"},
        )
        self.assertEqual(response.status_code, 302)
        membership = OrganizationMembership.objects.get(
            user=self.new_user, organization=self.org
        )
        self.assertEqual(membership.role, OrganizationMembership.Role.ADMIN)

    def test_add_member_with_owner_role(self):
        """Test that member can be added as owner."""
        self.client.login(username="admin", password="password123")
        response = self.client.post(
            reverse("accounts:organization_member_add", args=[self.org.slug]),
            {"username": "newuser", "role": "owner"},
        )
        self.assertEqual(response.status_code, 302)
        membership = OrganizationMembership.objects.get(
            user=self.new_user, organization=self.org
        )
        self.assertEqual(membership.role, OrganizationMembership.Role.OWNER)

    def test_add_member_nonexistent_user(self):
        """Test that adding non-existent user returns error."""
        self.client.login(username="admin", password="password123")
        response = self.client.post(
            reverse("accounts:organization_member_add", args=[self.org.slug]),
            {"username": "nonexistent", "role": "member"},
        )
        self.assertEqual(response.status_code, 302)
        # Check that no membership was created
        self.assertFalse(
            OrganizationMembership.objects.filter(
                organization=self.org, user__username="nonexistent"
            ).exists()
        )

    def test_add_member_duplicate(self):
        """Test that adding existing member returns error."""
        self.client.login(username="admin", password="password123")
        response = self.client.post(
            reverse("accounts:organization_member_add", args=[self.org.slug]),
            {"username": "member", "role": "admin"},
        )
        self.assertEqual(response.status_code, 302)
        # Ensure role wasn't changed
        self.member_membership.refresh_from_db()
        self.assertEqual(
            self.member_membership.role, OrganizationMembership.Role.MEMBER
        )

    def test_add_member_invalid_role(self):
        """Test that invalid role returns error."""
        self.client.login(username="admin", password="password123")
        response = self.client.post(
            reverse("accounts:organization_member_add", args=[self.org.slug]),
            {"username": "newuser", "role": "invalid_role"},
        )
        self.assertEqual(response.status_code, 302)
        # Check that no membership was created
        self.assertFalse(
            OrganizationMembership.objects.filter(
                user=self.new_user, organization=self.org
            ).exists()
        )

    def test_add_member_get_request_redirects(self):
        """Test that GET request redirects to members page."""
        self.client.login(username="admin", password="password123")
        response = self.client.get(
            reverse("accounts:organization_member_add", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url, reverse("accounts:organization_members", args=[self.org.slug])
        )


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


class OrganizationDeleteViewTests(TestCase):
    """Test cases for organization delete view."""

    def setUp(self):
        """Set up test fixtures."""
        self.admin_user = User.objects.create_user(
            username="admin", email="admin@example.com", password="password123"
        )
        self.owner_user = User.objects.create_user(
            username="owner", email="owner@example.com", password="password123"
        )
        self.member_user = User.objects.create_user(
            username="member", email="member@example.com", password="password123"
        )
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org",
        )
        OrganizationMembership.objects.create(
            user=self.admin_user,
            organization=self.org,
            role=OrganizationMembership.Role.ADMIN,
        )
        OrganizationMembership.objects.create(
            user=self.owner_user,
            organization=self.org,
            role=OrganizationMembership.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            user=self.member_user,
            organization=self.org,
            role=OrganizationMembership.Role.MEMBER,
        )

    def test_delete_requires_login(self):
        """Test that deleting organization requires login."""
        response = self.client.post(
            reverse("accounts:organization_delete", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)
        self.assertTrue(Organization.objects.filter(id=self.org.id).exists())

    def test_delete_requires_admin(self):
        """Test that only admins/owners can delete organization."""
        self.client.login(username="member", password="password123")
        response = self.client.post(
            reverse("accounts:organization_delete", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Organization.objects.filter(id=self.org.id).exists())

    def test_delete_success_by_admin(self):
        """Test that admin can delete organization."""
        org_id = self.org.id
        self.client.login(username="admin", password="password123")
        response = self.client.post(
            reverse("accounts:organization_delete", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Organization.objects.filter(id=org_id).exists())
        self.assertEqual(
            OrganizationMembership.objects.filter(organization_id=org_id).count(), 0
        )

    def test_delete_success_by_owner(self):
        """Test that owner can delete organization."""
        org_id = self.org.id
        owner = User.objects.get(username="owner")
        self.assertTrue(owner.check_password("password123"))
        self.assertTrue(self.client.login(username="owner", password="password123"))
        response = self.client.post(
            reverse("accounts:organization_delete", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Organization.objects.filter(id=org_id).exists())
        self.assertEqual(
            OrganizationMembership.objects.filter(organization_id=org_id).count(), 0
        )

    def test_get_request_redirects_to_settings(self):
        """Test that GET request is rejected for non-POST methods."""
        self.client.login(username="admin", password="password123")
        response = self.client.get(
            reverse("accounts:organization_delete", args=[self.org.slug])
        )
        self.assertEqual(response.status_code, 405)
