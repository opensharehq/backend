"""Tests for organization API endpoints."""

import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import TestCase, override_settings

from accounts.models import Organization, OrganizationMembership
from accounts.services.jwt_tokens import create_access_token


class ApiV1OrganizationTests(TestCase):
    """Validate organization management APIs."""

    def setUp(self):
        """Create an authenticated user."""
        self.User = get_user_model()
        self.owner = self.User.objects.create_user(
            username="org_owner",
            email="org_owner@example.com",
            password="StrongPass123!",
        )
        self.member = self.User.objects.create_user(
            username="org_member",
            email="org_member@example.com",
            password="StrongPass123!",
        )
        self.admin = self.User.objects.create_user(
            username="org_admin",
            email="org_admin@example.com",
            password="StrongPass123!",
        )
        self.outsider = self.User.objects.create_user(
            username="org_outsider",
            email="org_outsider@example.com",
            password="StrongPass123!",
        )
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.owner)}"
        }

    def _headers_for(self, user):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_access_token(user)}"}

    def test_create_list_update_and_delete_organization(self):
        """Organizations should be manageable through the API."""
        create_response = self.client.post(
            "/api/v1/organizations/",
            {
                "name": "OpenShare Org",
                "slug": "openshare-org",
                "description": "API org",
                "website": "https://example.com",
                "location": "Shanghai",
            },
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(create_response.status_code, 201)
        organization = Organization.objects.get(slug="openshare-org")
        self.assertTrue(
            OrganizationMembership.objects.filter(
                user=self.owner,
                organization=organization,
                role=OrganizationMembership.Role.OWNER,
            ).exists()
        )

        list_response = self.client.get("/api/v1/organizations/", **self.headers)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()["items"][0]["slug"], organization.slug)

        update_response = self.client.patch(
            f"/api/v1/organizations/{organization.slug}",
            {"location": "Beijing"},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(update_response.status_code, 200)
        organization.refresh_from_db()
        self.assertEqual(organization.location, "Beijing")

        delete_response = self.client.delete(
            f"/api/v1/organizations/{organization.slug}?confirm_slug={organization.slug}",
            **self.headers,
        )
        self.assertEqual(delete_response.status_code, 204)
        self.assertFalse(Organization.objects.filter(id=organization.id).exists())

    def test_member_add_update_and_remove(self):
        """Organization member management should work for owners."""
        organization = Organization.objects.create(name="Org", slug="org")
        OrganizationMembership.objects.create(
            user=self.owner,
            organization=organization,
            role=OrganizationMembership.Role.OWNER,
        )

        add_response = self.client.post(
            f"/api/v1/organizations/{organization.slug}/members",
            {
                "username": self.member.username,
                "role": OrganizationMembership.Role.MEMBER,
            },
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(add_response.status_code, 201)
        membership_id = add_response.json()["id"]

        update_response = self.client.patch(
            f"/api/v1/organizations/{organization.slug}/members/{membership_id}",
            {"role": OrganizationMembership.Role.ADMIN},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(
            update_response.json()["role"], OrganizationMembership.Role.ADMIN
        )

        remove_response = self.client.delete(
            f"/api/v1/organizations/{organization.slug}/members/{membership_id}",
            **self.headers,
        )
        self.assertEqual(remove_response.status_code, 204)
        self.assertFalse(
            OrganizationMembership.objects.filter(id=membership_id).exists()
        )

    def test_member_candidate_search_matches_id_username_and_name(self):
        """Admins can find active non-members without exposing private fields."""
        organization = Organization.objects.create(name="Search Org", slug="search-org")
        OrganizationMembership.objects.create(
            user=self.owner,
            organization=organization,
            role=OrganizationMembership.Role.OWNER,
        )
        candidate = self.User.objects.create_user(
            id=12345,
            username="searchable_handle",
            email="private@example.com",
            first_name="Ming",
            last_name="Zhao",
            password="StrongPass123!",
        )

        username_response = self.client.get(
            f"/api/v1/organizations/{organization.slug}/member-candidates",
            {"q": "able_han"},
            **self.headers,
        )
        name_response = self.client.get(
            f"/api/v1/organizations/{organization.slug}/member-candidates",
            {"q": "Ming Zh"},
            **self.headers,
        )
        id_response = self.client.get(
            f"/api/v1/organizations/{organization.slug}/member-candidates",
            {"q": "234"},
            **self.headers,
        )

        for response in (username_response, name_response, id_response):
            self.assertEqual(response.status_code, 200)
            item = next(
                item for item in response.json()["items"] if item["id"] == candidate.id
            )
            self.assertEqual(item["username"], candidate.username)
            self.assertEqual(item["display_name"], "Ming Zhao")
            self.assertNotIn("email", item)

    def test_member_candidate_search_excludes_unavailable_users(self):
        """Existing, inactive, and merged users should not be available as candidates."""
        organization = Organization.objects.create(
            name="Search Org", slug="search-hide"
        )
        OrganizationMembership.objects.create(
            user=self.owner,
            organization=organization,
            role=OrganizationMembership.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            user=self.member,
            organization=organization,
            role=OrganizationMembership.Role.MEMBER,
        )
        self.member.username = "hidden_search_member"
        self.member.save(update_fields=["username"])
        inactive = self.User.objects.create_user(
            username="hidden_search_inactive",
            is_active=False,
        )
        merged = self.User.objects.create_user(username="hidden_search_merged")
        merged.merged_into = self.outsider
        merged.save(update_fields=["merged_into"])

        response = self.client.get(
            f"/api/v1/organizations/{organization.slug}/member-candidates",
            {"q": "hidden_search"},
            **self.headers,
        )
        blank_response = self.client.get(
            f"/api/v1/organizations/{organization.slug}/member-candidates",
            {"q": "   "},
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        result_ids = {item["id"] for item in response.json()["items"]}
        self.assertNotIn(self.member.id, result_ids)
        self.assertNotIn(inactive.id, result_ids)
        self.assertNotIn(merged.id, result_ids)
        self.assertEqual(blank_response.status_code, 200)
        self.assertEqual(blank_response.json()["items"], [])

    def test_member_candidate_search_limits_results(self):
        """Candidate searches should return no more than 20 users."""
        organization = Organization.objects.create(name="Limit Org", slug="limit-org")
        OrganizationMembership.objects.create(
            user=self.owner,
            organization=organization,
            role=OrganizationMembership.Role.OWNER,
        )
        self.User.objects.bulk_create(
            [self.User(username=f"candidate_limit_{index:02d}") for index in range(21)]
        )

        response = self.client.get(
            f"/api/v1/organizations/{organization.slug}/member-candidates",
            {"q": "candidate_limit"},
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 20)

    def test_member_candidate_search_requires_admin_role(self):
        """Regular members and outsiders cannot enumerate organization candidates."""
        organization = Organization.objects.create(
            name="Locked Search", slug="locked-search"
        )
        OrganizationMembership.objects.create(
            user=self.owner,
            organization=organization,
            role=OrganizationMembership.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            user=self.member,
            organization=organization,
            role=OrganizationMembership.Role.MEMBER,
        )

        member_response = self.client.get(
            f"/api/v1/organizations/{organization.slug}/member-candidates",
            {"q": "org"},
            **self._headers_for(self.member),
        )
        outsider_response = self.client.get(
            f"/api/v1/organizations/{organization.slug}/member-candidates",
            {"q": "org"},
            **self._headers_for(self.outsider),
        )

        self.assertEqual(member_response.status_code, 403)
        self.assertEqual(outsider_response.status_code, 403)

    def test_admin_can_manage_non_owner_members_and_avatar(self):
        """Admins can manage organization settings, avatars, and non-owner members."""
        organization = Organization.objects.create(name="Managed Org", slug="managed")
        OrganizationMembership.objects.create(
            user=self.owner,
            organization=organization,
            role=OrganizationMembership.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            user=self.admin,
            organization=organization,
            role=OrganizationMembership.Role.ADMIN,
        )
        membership = OrganizationMembership.objects.create(
            user=self.member,
            organization=organization,
            role=OrganizationMembership.Role.MEMBER,
        )

        admin_headers = self._headers_for(self.admin)
        update_response = self.client.patch(
            f"/api/v1/organizations/{organization.slug}",
            {"location": "Hangzhou"},
            content_type="application/json",
            **admin_headers,
        )
        self.assertEqual(update_response.status_code, 200)
        organization.refresh_from_db()
        self.assertEqual(organization.location, "Hangzhou")

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(
                MEDIA_ROOT=media_root,
                STORAGES={
                    "default": {
                        "BACKEND": "django.core.files.storage.FileSystemStorage"
                    },
                    "staticfiles": {
                        "BACKEND": (
                            "django.contrib.staticfiles.storage.StaticFilesStorage"
                        )
                    },
                },
            ):
                avatar_response = self.client.post(
                    f"/api/v1/organizations/{organization.slug}/avatar",
                    {
                        "avatar": SimpleUploadedFile(
                            "avatar.png",
                            b"filecontent",
                            "image/png",
                        )
                    },
                    **admin_headers,
                )
                self.assertEqual(avatar_response.status_code, 200)
                organization.refresh_from_db()
                self.assertTrue(bool(organization.avatar))

                avatar_delete_response = self.client.delete(
                    f"/api/v1/organizations/{organization.slug}/avatar",
                    **admin_headers,
                )
                self.assertEqual(avatar_delete_response.status_code, 204)
                organization.refresh_from_db()
                self.assertFalse(bool(organization.avatar))

        promote_response = self.client.patch(
            f"/api/v1/organizations/{organization.slug}/members/{membership.id}",
            {"role": OrganizationMembership.Role.ADMIN},
            content_type="application/json",
            **admin_headers,
        )
        self.assertEqual(promote_response.status_code, 200)
        membership.refresh_from_db()
        self.assertEqual(membership.role, OrganizationMembership.Role.ADMIN)

        remove_response = self.client.delete(
            f"/api/v1/organizations/{organization.slug}/members/{membership.id}",
            **admin_headers,
        )
        self.assertEqual(remove_response.status_code, 204)
        self.assertFalse(
            OrganizationMembership.objects.filter(id=membership.id).exists()
        )

    def test_create_organization_validates_unique_slug(self):
        """Creating with an existing slug should return a validation error."""
        Organization.objects.create(name="Existing Org", slug="existing-slug")

        response = self.client.post(
            "/api/v1/organizations/",
            {
                "name": "New Org",
                "slug": "existing-slug",
                "description": "Duplicate slug",
                "website": "https://example.com",
                "location": "Shanghai",
            },
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "validation_error")

    def test_create_organization_returns_conflict_on_slug_integrity_error(self):
        """Slug uniqueness races should surface as a conflict instead of a 500."""
        with mock.patch(
            "accounts.api_orgs_v1.Organization.objects.create",
            side_effect=IntegrityError,
        ):
            response = self.client.post(
                "/api/v1/organizations/",
                {
                    "name": "New Org",
                    "slug": "racy-slug",
                    "description": "Race condition",
                    "website": "https://example.com",
                    "location": "Shanghai",
                },
                content_type="application/json",
                **self.headers,
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "slug_conflict")

    def test_member_add_returns_conflict_on_membership_integrity_error(self):
        """Membership uniqueness races should surface as member_exists."""
        organization = Organization.objects.create(name="Org", slug="org-race")
        OrganizationMembership.objects.create(
            user=self.owner,
            organization=organization,
            role=OrganizationMembership.Role.OWNER,
        )

        with mock.patch(
            "accounts.api_orgs_v1.OrganizationMembership.objects.create",
            side_effect=IntegrityError,
        ):
            response = self.client.post(
                f"/api/v1/organizations/{organization.slug}/members",
                {
                    "username": self.member.username,
                    "role": OrganizationMembership.Role.MEMBER,
                },
                content_type="application/json",
                **self.headers,
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "member_exists")

    def test_organization_detail_includes_membership(self):
        """Organization detail payload should include membership for the current user."""
        organization = Organization.objects.create(name="Detail Org", slug="detail-org")
        OrganizationMembership.objects.create(
            user=self.owner,
            organization=organization,
            role=OrganizationMembership.Role.ADMIN,
        )

        response = self.client.get(
            f"/api/v1/organizations/{organization.slug}", **self.headers
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["membership"]["role"], OrganizationMembership.Role.ADMIN
        )
        self.assertTrue(payload["membership"]["is_admin_or_owner"])

    def test_member_cannot_demote_last_owner(self):
        """The last owner cannot be demoted or removed via the API."""
        organization = Organization.objects.create(name="Solo Owner", slug="solo-owner")
        membership = OrganizationMembership.objects.create(
            user=self.owner,
            organization=organization,
            role=OrganizationMembership.Role.OWNER,
        )

        demote_response = self.client.patch(
            f"/api/v1/organizations/{organization.slug}/members/{membership.id}",
            {"role": OrganizationMembership.Role.MEMBER},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(demote_response.status_code, 409)

        remove_response = self.client.delete(
            f"/api/v1/organizations/{organization.slug}/members/{membership.id}",
            **self.headers,
        )
        self.assertEqual(remove_response.status_code, 409)

    def test_owner_can_promote_member_to_owner(self):
        """Owners can assign the owner role to another organization member."""
        organization = Organization.objects.create(name="Promotion Org", slug="promote")
        OrganizationMembership.objects.create(
            user=self.owner,
            organization=organization,
            role=OrganizationMembership.Role.OWNER,
        )
        membership = OrganizationMembership.objects.create(
            user=self.member,
            organization=organization,
            role=OrganizationMembership.Role.MEMBER,
        )

        response = self.client.patch(
            f"/api/v1/organizations/{organization.slug}/members/{membership.id}",
            {"role": OrganizationMembership.Role.OWNER},
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(response.status_code, 200)
        membership.refresh_from_db()
        self.assertEqual(membership.role, OrganizationMembership.Role.OWNER)

    def test_admin_cannot_delete_org_or_manage_owner_roles(self):
        """Admins cannot delete organizations or change owner-role memberships."""
        organization = Organization.objects.create(
            name="Protected Org", slug="protected"
        )
        owner_membership = OrganizationMembership.objects.create(
            user=self.owner,
            organization=organization,
            role=OrganizationMembership.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            user=self.admin,
            organization=organization,
            role=OrganizationMembership.Role.ADMIN,
        )
        member_membership = OrganizationMembership.objects.create(
            user=self.member,
            organization=organization,
            role=OrganizationMembership.Role.MEMBER,
        )
        admin_headers = self._headers_for(self.admin)

        promote_response = self.client.patch(
            f"/api/v1/organizations/{organization.slug}/members/{member_membership.id}",
            {"role": OrganizationMembership.Role.OWNER},
            content_type="application/json",
            **admin_headers,
        )
        self.assertEqual(promote_response.status_code, 403)

        demote_owner_response = self.client.patch(
            f"/api/v1/organizations/{organization.slug}/members/{owner_membership.id}",
            {"role": OrganizationMembership.Role.MEMBER},
            content_type="application/json",
            **admin_headers,
        )
        self.assertEqual(demote_owner_response.status_code, 403)

        remove_owner_response = self.client.delete(
            f"/api/v1/organizations/{organization.slug}/members/{owner_membership.id}",
            **admin_headers,
        )
        self.assertEqual(remove_owner_response.status_code, 403)

        delete_org_response = self.client.delete(
            f"/api/v1/organizations/{organization.slug}?confirm_slug={organization.slug}",
            **admin_headers,
        )
        self.assertEqual(delete_org_response.status_code, 403)
        self.assertTrue(Organization.objects.filter(id=organization.id).exists())

    def test_member_and_non_member_cannot_manage_organization(self):
        """Members and non-members cannot use organization management endpoints."""
        organization = Organization.objects.create(name="Locked Org", slug="locked")
        OrganizationMembership.objects.create(
            user=self.owner,
            organization=organization,
            role=OrganizationMembership.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            user=self.member,
            organization=organization,
            role=OrganizationMembership.Role.MEMBER,
        )

        member_headers = self._headers_for(self.member)
        outsider_headers = self._headers_for(self.outsider)

        member_update = self.client.patch(
            f"/api/v1/organizations/{organization.slug}",
            {"location": "Suzhou"},
            content_type="application/json",
            **member_headers,
        )
        self.assertEqual(member_update.status_code, 403)

        member_add = self.client.post(
            f"/api/v1/organizations/{organization.slug}/members",
            {
                "username": self.outsider.username,
                "role": OrganizationMembership.Role.MEMBER,
            },
            content_type="application/json",
            **member_headers,
        )
        self.assertEqual(member_add.status_code, 403)

        outsider_detail = self.client.get(
            f"/api/v1/organizations/{organization.slug}",
            **outsider_headers,
        )
        self.assertEqual(outsider_detail.status_code, 403)

        outsider_members = self.client.get(
            f"/api/v1/organizations/{organization.slug}/members",
            **outsider_headers,
        )
        self.assertEqual(outsider_members.status_code, 403)

    def test_validation_error_branches_for_payloads_avatar_delete_and_members(self):
        """Validation and not-found branches should return stable API errors."""
        organization = Organization.objects.create(name="Branch Org", slug="branch-org")
        OrganizationMembership.objects.create(
            user=self.owner,
            organization=organization,
            role=OrganizationMembership.Role.OWNER,
        )
        existing = Organization.objects.create(name="Existing", slug="existing")

        empty_payload = self.client.post(
            "/api/v1/organizations/",
            {"name": "   ", "slug": "   "},
            content_type="application/json",
            **self.headers,
        )
        invalid_slug = self.client.post(
            "/api/v1/organizations/",
            {"name": "Invalid Slug", "slug": "bad slug"},
            content_type="application/json",
            **self.headers,
        )
        update_duplicate_slug = self.client.patch(
            f"/api/v1/organizations/{organization.slug}",
            {"slug": existing.slug},
            content_type="application/json",
            **self.headers,
        )
        missing_avatar = self.client.post(
            f"/api/v1/organizations/{organization.slug}/avatar",
            {},
            **self.headers,
        )
        delete_empty_avatar = self.client.delete(
            f"/api/v1/organizations/{organization.slug}/avatar",
            **self.headers,
        )
        wrong_confirm_slug = self.client.delete(
            f"/api/v1/organizations/{organization.slug}?confirm_slug=wrong",
            **self.headers,
        )
        invalid_role_add = self.client.post(
            f"/api/v1/organizations/{organization.slug}/members",
            {"username": self.member.username, "role": "invalid"},
            content_type="application/json",
            **self.headers,
        )
        missing_user_add = self.client.post(
            f"/api/v1/organizations/{organization.slug}/members",
            {"username": "missing-user", "role": OrganizationMembership.Role.MEMBER},
            content_type="application/json",
            **self.headers,
        )
        duplicate_membership = OrganizationMembership.objects.create(
            user=self.member,
            organization=organization,
            role=OrganizationMembership.Role.MEMBER,
        )
        duplicate_add = self.client.post(
            f"/api/v1/organizations/{organization.slug}/members",
            {
                "username": self.member.username,
                "role": OrganizationMembership.Role.MEMBER,
            },
            content_type="application/json",
            **self.headers,
        )
        invalid_role_update = self.client.patch(
            f"/api/v1/organizations/{organization.slug}/members/{duplicate_membership.id}",
            {"role": "invalid"},
            content_type="application/json",
            **self.headers,
        )
        missing_member_update = self.client.patch(
            f"/api/v1/organizations/{organization.slug}/members/999999",
            {"role": OrganizationMembership.Role.ADMIN},
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(empty_payload.status_code, 422)
        self.assertEqual(invalid_slug.status_code, 422)
        self.assertEqual(update_duplicate_slug.status_code, 422)
        self.assertEqual(missing_avatar.status_code, 422)
        self.assertEqual(delete_empty_avatar.status_code, 204)
        self.assertEqual(wrong_confirm_slug.status_code, 422)
        self.assertEqual(invalid_role_add.status_code, 422)
        self.assertEqual(missing_user_add.status_code, 404)
        self.assertEqual(duplicate_add.status_code, 409)
        self.assertEqual(invalid_role_update.status_code, 422)
        self.assertEqual(missing_member_update.status_code, 404)

    def test_owner_branches_for_avatar_replacement_and_multi_owner_changes(self):
        """Avatar replacement and multi-owner role changes should cover success branches."""
        organization = Organization.objects.create(name="Owners Org", slug="owners-org")
        owner_membership = OrganizationMembership.objects.create(
            user=self.owner,
            organization=organization,
            role=OrganizationMembership.Role.OWNER,
        )
        second_owner_membership = OrganizationMembership.objects.create(
            user=self.member,
            organization=organization,
            role=OrganizationMembership.Role.OWNER,
        )
        third_owner_membership = OrganizationMembership.objects.create(
            user=self.outsider,
            organization=organization,
            role=OrganizationMembership.Role.OWNER,
        )

        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(
                MEDIA_ROOT=media_root,
                STORAGES={
                    "default": {
                        "BACKEND": "django.core.files.storage.FileSystemStorage"
                    },
                    "staticfiles": {
                        "BACKEND": (
                            "django.contrib.staticfiles.storage.StaticFilesStorage"
                        )
                    },
                },
            ):
                first_avatar = self.client.post(
                    f"/api/v1/organizations/{organization.slug}/avatar",
                    {
                        "avatar": SimpleUploadedFile(
                            "first.png",
                            b"first",
                            "image/png",
                        )
                    },
                    **self.headers,
                )
                second_avatar = self.client.post(
                    f"/api/v1/organizations/{organization.slug}/avatar",
                    {
                        "avatar": SimpleUploadedFile(
                            "second.png",
                            b"second",
                            "image/png",
                        )
                    },
                    **self.headers,
                )
                delete_with_avatar = self.client.delete(
                    f"/api/v1/organizations/{organization.slug}/avatar",
                    **self.headers,
                )

                organization.avatar.save(
                    "delete.png",
                    SimpleUploadedFile("delete.png", b"delete", "image/png"),
                    save=True,
                )
                avatar_delete_org = Organization.objects.create(
                    name="Avatar Delete Org",
                    slug="avatar-delete-org",
                    avatar=organization.avatar.name,
                )
                OrganizationMembership.objects.create(
                    user=self.owner,
                    organization=avatar_delete_org,
                    role=OrganizationMembership.Role.OWNER,
                )
                delete_org_with_avatar = self.client.delete(
                    f"/api/v1/organizations/{avatar_delete_org.slug}?confirm_slug={avatar_delete_org.slug}",
                    **self.headers,
                )

        demote_owner = self.client.patch(
            f"/api/v1/organizations/{organization.slug}/members/{second_owner_membership.id}",
            {"role": OrganizationMembership.Role.ADMIN},
            content_type="application/json",
            **self.headers,
        )

        remove_owner = self.client.delete(
            f"/api/v1/organizations/{organization.slug}/members/{third_owner_membership.id}",
            **self.headers,
        )
        demote_last_owner = self.client.patch(
            f"/api/v1/organizations/{organization.slug}/members/{owner_membership.id}",
            {"role": OrganizationMembership.Role.MEMBER},
            content_type="application/json",
            **self.headers,
        )
        members_response = self.client.get(
            f"/api/v1/organizations/{organization.slug}/members",
            **self.headers,
        )

        self.assertEqual(first_avatar.status_code, 200)
        self.assertEqual(second_avatar.status_code, 200)
        self.assertEqual(delete_with_avatar.status_code, 204)
        self.assertEqual(delete_org_with_avatar.status_code, 204)
        self.assertEqual(demote_owner.status_code, 200)
        self.assertEqual(remove_owner.status_code, 204)
        self.assertEqual(demote_last_owner.status_code, 409)
        self.assertEqual(members_response.status_code, 200)
        self.assertEqual(members_response.json()["owner_count"], 1)
