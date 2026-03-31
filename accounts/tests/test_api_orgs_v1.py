"""Tests for organization API endpoints."""

from django.contrib.auth import get_user_model
from django.test import TestCase

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
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.owner)}"
        }

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

        self.assertEqual(create_response.status_code, 200)
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
        self.assertEqual(delete_response.status_code, 200)
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
        self.assertEqual(add_response.status_code, 200)
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
        self.assertEqual(remove_response.status_code, 200)
        self.assertFalse(
            OrganizationMembership.objects.filter(id=membership_id).exists()
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
