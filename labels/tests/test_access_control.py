from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Organization, OrganizationMembership
from labels.models import (
    GranteeType,
    Label,
    LabelPermission,
    LabelType,
    OwnerType,
    PermissionLevel,
)


class LabelAccessTests(TestCase):
    """Tests covering Label.has_access permission logic."""

    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", password="pass")
        self.alice = User.objects.create_user(username="alice", password="pass")
        self.bob = User.objects.create_user(username="bob", password="pass")

        self.org = Organization.objects.create(name="Org", slug="org")
        OrganizationMembership.objects.create(
            user=self.alice,
            organization=self.org,
            role=OrganizationMembership.Role.MEMBER,
        )
        OrganizationMembership.objects.create(
            user=self.bob,
            organization=self.org,
            role=OrganizationMembership.Role.ADMIN,
        )

    def test_public_label_allows_view_and_use(self):
        label = Label.objects.create(
            name="public-label",
            name_zh="公开标签",
            type=LabelType.PROJECT,
            owner_type=OwnerType.USER,
            owner_id=self.owner.id,
            is_public=True,
        )

        self.assertTrue(label.has_access(self.alice, required_level="view"))
        self.assertTrue(label.has_access(self.alice, required_level="use"))
        self.assertFalse(label.has_access(self.alice, required_level="edit"))

    def test_org_owned_label_respects_membership_roles(self):
        label = Label.objects.create(
            name="org-label",
            name_zh="组织标签",
            type=LabelType.PROJECT,
            owner_type=OwnerType.ORGANIZATION,
            owner_id=self.org.id,
        )

        # Regular member: view/use allowed, edit/manage denied
        self.assertTrue(label.has_access(self.alice, required_level="view"))
        self.assertTrue(label.has_access(self.alice, required_level="use"))
        self.assertFalse(label.has_access(self.alice, required_level="edit"))
        self.assertFalse(label.has_access(self.alice, required_level="manage"))

        # Admin: full control
        self.assertTrue(label.has_access(self.bob, required_level="edit"))
        self.assertTrue(label.has_access(self.bob, required_level="manage"))

    def test_org_granted_permission_honors_membership(self):
        label = Label.objects.create(
            name="shared-to-org",
            name_zh="共享标签",
            type=LabelType.PROJECT,
            owner_type=OwnerType.USER,
            owner_id=self.owner.id,
        )
        LabelPermission.objects.create(
            label=label,
            grantee_type=GranteeType.ORGANIZATION,
            grantee_id=self.org.id,
            permission_level=PermissionLevel.USE,
            granted_by=self.owner,
        )

        # Member inherits org permission
        self.assertTrue(label.has_access(self.alice, required_level="view"))
        self.assertTrue(label.has_access(self.alice, required_level="use"))
        self.assertFalse(label.has_access(self.alice, required_level="edit"))
