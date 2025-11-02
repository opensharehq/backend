"""Tests for Organization models and pipeline."""

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from accounts.models import Organization, OrganizationMembership

User = get_user_model()


class OrganizationModelTests(TestCase):
    """Test cases for Organization model."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )

    def test_organization_creation(self):
        """Test basic organization creation."""
        org = Organization.objects.create(
            name="Test Organization",
            slug="test-org",
            description="A test organization",
            provider="github",
            provider_id="123456",
            provider_login="test-org",
        )

        self.assertEqual(org.name, "Test Organization")
        self.assertEqual(org.slug, "test-org")
        self.assertEqual(org.provider, "github")
        self.assertEqual(str(org), "Test Organization")

    def test_organization_unique_provider_id(self):
        """Test that provider+provider_id combination is unique."""
        Organization.objects.create(
            name="Org 1",
            slug="org-1",
            provider="github",
            provider_id="123",
            provider_login="org1",
        )

        # Creating another org with same provider+provider_id should fail
        with self.assertRaises(IntegrityError):
            Organization.objects.create(
                name="Org 2",
                slug="org-2",
                provider="github",
                provider_id="123",
                provider_login="org2",
            )

    def test_organization_different_providers_same_id(self):
        """Test that same provider_id is allowed for different providers."""
        org1 = Organization.objects.create(
            name="GitHub Org",
            slug="github-org",
            provider="github",
            provider_id="123",
            provider_login="github-org",
        )

        org2 = Organization.objects.create(
            name="Gitee Org",
            slug="gitee-org",
            provider="gitee",
            provider_id="123",
            provider_login="gitee-org",
        )

        self.assertNotEqual(org1.id, org2.id)


class OrganizationMembershipModelTests(TestCase):
    """Test cases for OrganizationMembership model."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )
        self.org = Organization.objects.create(
            name="Test Organization",
            slug="test-org",
            provider="github",
            provider_id="123456",
            provider_login="test-org",
        )

    def test_membership_creation(self):
        """Test basic membership creation."""
        membership = OrganizationMembership.objects.create(
            user=self.user,
            organization=self.org,
            role=OrganizationMembership.Role.MEMBER,
        )

        self.assertEqual(membership.user, self.user)
        self.assertEqual(membership.organization, self.org)
        self.assertEqual(membership.role, OrganizationMembership.Role.MEMBER)

    def test_membership_default_role(self):
        """Test that default role is MEMBER."""
        membership = OrganizationMembership.objects.create(
            user=self.user,
            organization=self.org,
        )

        self.assertEqual(membership.role, OrganizationMembership.Role.MEMBER)

    def test_membership_unique_user_org(self):
        """Test that user+organization combination is unique."""
        OrganizationMembership.objects.create(
            user=self.user,
            organization=self.org,
            role=OrganizationMembership.Role.MEMBER,
        )

        # Creating another membership with same user+org should fail
        with self.assertRaises(IntegrityError):
            OrganizationMembership.objects.create(
                user=self.user,
                organization=self.org,
                role=OrganizationMembership.Role.ADMIN,
            )

    def test_membership_is_admin_or_owner(self):
        """Test is_admin_or_owner method."""
        member = OrganizationMembership.objects.create(
            user=self.user,
            organization=self.org,
            role=OrganizationMembership.Role.MEMBER,
        )
        self.assertFalse(member.is_admin_or_owner())

        admin_user = User.objects.create_user(
            username="admin", email="admin@example.com", password="password123"
        )
        admin = OrganizationMembership.objects.create(
            user=admin_user,
            organization=self.org,
            role=OrganizationMembership.Role.ADMIN,
        )
        self.assertTrue(admin.is_admin_or_owner())

        owner_user = User.objects.create_user(
            username="owner", email="owner@example.com", password="password123"
        )
        owner = OrganizationMembership.objects.create(
            user=owner_user,
            organization=self.org,
            role=OrganizationMembership.Role.OWNER,
        )
        self.assertTrue(owner.is_admin_or_owner())

    def test_organization_members_relationship(self):
        """Test many-to-many relationship through OrganizationMembership."""
        user2 = User.objects.create_user(
            username="user2", email="user2@example.com", password="password123"
        )

        OrganizationMembership.objects.create(
            user=self.user,
            organization=self.org,
            role=OrganizationMembership.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            user=user2,
            organization=self.org,
            role=OrganizationMembership.Role.MEMBER,
        )

        members = self.org.members.all()
        self.assertEqual(members.count(), 2)
        self.assertIn(self.user, members)
        self.assertIn(user2, members)

    def test_user_organizations_relationship(self):
        """Test reverse many-to-many relationship."""
        org2 = Organization.objects.create(
            name="Org 2",
            slug="org-2",
            provider="github",
            provider_id="789",
            provider_login="org-2",
        )

        OrganizationMembership.objects.create(
            user=self.user,
            organization=self.org,
            role=OrganizationMembership.Role.MEMBER,
        )
        OrganizationMembership.objects.create(
            user=self.user,
            organization=org2,
            role=OrganizationMembership.Role.ADMIN,
        )

        orgs = self.user.organizations.all()
        self.assertEqual(orgs.count(), 2)
        self.assertIn(self.org, orgs)
        self.assertIn(org2, orgs)
