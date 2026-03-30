"""Tests for accounts admin."""

from datetime import date, timedelta
from uuid import uuid4

from django.contrib import admin
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from accounts.admin import (
    AccountMergeRequestAdmin,
    OrganizationAdmin,
    UserAdmin,
    UserProfileAdmin,
    WorkExperienceAdmin,
)
from accounts.models import (
    AccountMergeRequest,
    Organization,
    OrganizationMembership,
    UserProfile,
    WorkExperience,
)


class UserAdminRegistrationTests(TestCase):
    """Test cases for User model admin registration."""

    databases = {"default"}

    def test_user_registered_with_admin_site(self):
        """Test that User model is registered with Django admin."""
        from accounts import admin as accounts_admin

        user_model = get_user_model()

        assert user_model in admin.site._registry
        assert isinstance(admin.site._registry[user_model], accounts_admin.UserAdmin)


class AccountsAdminBehaviorTests(TestCase):
    """Behavior coverage for the custom accounts admin classes."""

    def setUp(self):
        """Create reusable admin fixtures."""
        self.site = AdminSite()
        self.factory = RequestFactory()
        self.superuser = get_user_model().objects.create_superuser(
            username="accounts-admin",
            email="accounts-admin@example.com",
            password="password123",
        )
        self.user = get_user_model().objects.create_user(
            username="regular-user",
            email="regular@example.com",
            password="password123",
        )
        self.organization = Organization.objects.create(
            name="Open Org", slug="open-org"
        )
        self.profile, _ = UserProfile.objects.get_or_create(user=self.user)
        self.user_admin = UserAdmin(get_user_model(), self.site)
        self.profile_admin = UserProfileAdmin(UserProfile, self.site)
        self.work_experience_admin = WorkExperienceAdmin(WorkExperience, self.site)
        self.organization_admin = OrganizationAdmin(Organization, self.site)
        self.merge_request_admin = AccountMergeRequestAdmin(
            AccountMergeRequest, self.site
        )

    def _request(self):
        """Build a request with a logged-in superuser."""
        request = self.factory.get("/admin/accounts/")
        request.user = self.superuser
        return request

    def test_user_admin_displays_points_and_redirects_grant_action(self):
        """The user admin should expose total points and reuse the grant workflow."""
        response = self.user_admin.grant_points_action(
            self._request(),
            get_user_model().objects.filter(pk=self.user.pk),
        )

        self.assertEqual(self.user_admin.display_total_points(self.user), 0)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"], f"/admin/points/grant-to-users/?ids={self.user.pk}"
        )

    def test_profile_and_work_experience_helpers_reflect_model_state(self):
        """Profile/work history helpers should collapse to simple booleans."""
        self.profile.bio = "Open source contributor"
        self.profile.save(update_fields=["bio"])
        work = WorkExperience.objects.create(
            profile=self.profile,
            company_name="OpenShare",
            title="Engineer",
            start_date=date(2024, 1, 1),
            end_date=None,
            description="Building tests",
        )

        self.assertTrue(self.profile_admin.has_bio(self.profile))
        self.assertTrue(self.work_experience_admin.is_current(work))

    def test_merge_request_admin_is_read_only_for_existing_records(self):
        """Merge requests should be visible but not editable or manually creatable."""
        merge_request = AccountMergeRequest.objects.create(
            id=uuid4(),
            source_user=self.user,
            target_user=self.superuser,
            target_username_input=self.superuser.username,
            approve_token="merge-admin-token",
            expires_at=timezone.now() + timedelta(days=1),
            asset_snapshot={},
        )

        self.assertFalse(self.merge_request_admin.has_add_permission(self._request()))
        self.assertFalse(
            self.merge_request_admin.has_change_permission(
                self._request(),
                obj=merge_request,
            )
        )
        self.assertTrue(
            self.merge_request_admin.has_change_permission(self._request(), obj=None)
        )

    def test_organization_admin_counts_members_and_redirects_grant_action(self):
        """Organization admin should expose member counts and reuse grant workflow."""
        OrganizationMembership.objects.create(
            user=self.user,
            organization=self.organization,
            role=OrganizationMembership.Role.OWNER,
        )

        response = self.organization_admin.grant_points_action(
            self._request(),
            Organization.objects.filter(pk=self.organization.pk),
        )

        self.assertEqual(self.organization_admin.member_count(self.organization), 1)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"/admin/points/grant-to-orgs/?ids={self.organization.pk}",
        )
