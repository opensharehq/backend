"""Tests for authenticated user API endpoints."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import (
    AccountMergeRequest,
    ShippingAddress,
    UserProfile,
    WorkExperience,
)
from accounts.services.jwt_tokens import create_access_token


class ApiV1MeTests(TestCase):
    """Validate the authenticated `me` API."""

    def setUp(self):
        """Create a reusable authenticated user."""
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username="me_user",
            email="me_user@example.com",
            password="StrongPass123!",
        )
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.user)}"
        }

    def _json_headers(self):
        return {"content_type": "application/json", **self.headers}

    def test_profile_get_and_patch(self):
        """The profile endpoints should read and update the current profile."""
        self.assertFalse(UserProfile.objects.filter(user=self.user).exists())

        response = self.client.get("/api/v1/me/profile", **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["username"], self.user.username)
        self.assertEqual(response.json()["balance"]["total"], 0)
        self.assertFalse(UserProfile.objects.filter(user=self.user).exists())

        patch_response = self.client.patch(
            "/api/v1/me/profile",
            {"bio": "API updated bio", "company": "OpenShare"},
            **self._json_headers(),
        )

        self.assertEqual(patch_response.status_code, 200)
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.bio, "API updated bio")
        self.assertEqual(profile.company, "OpenShare")

    def test_work_experience_crud(self):
        """Work experience endpoints should support create, update, and delete."""
        create_response = self.client.post(
            "/api/v1/me/work-experiences",
            {
                "company_name": "OpenShare",
                "title": "Maintainer",
                "start_date": "2024-01-01",
                "end_date": "2025-01-01",
                "description": "Community work",
            },
            **self._json_headers(),
        )

        self.assertEqual(create_response.status_code, 201)
        experience_id = create_response.json()["id"]

        patch_response = self.client.patch(
            f"/api/v1/me/work-experiences/{experience_id}",
            {"title": "Senior Maintainer"},
            **self._json_headers(),
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.json()["title"], "Senior Maintainer")

        delete_response = self.client.delete(
            f"/api/v1/me/work-experiences/{experience_id}",
            **self.headers,
        )
        self.assertEqual(delete_response.status_code, 204)
        self.assertFalse(WorkExperience.objects.filter(id=experience_id).exists())

    def test_education_crud(self):
        """Education endpoints should support create, update, and delete."""
        create_response = self.client.post(
            "/api/v1/me/educations",
            {
                "institution_name": "Tsinghua",
                "degree": "Master",
                "field_of_study": "Computer Science",
                "start_date": "2018-09-01",
                "end_date": "2020-07-01",
            },
            **self._json_headers(),
        )
        self.assertEqual(create_response.status_code, 201)
        education_id = create_response.json()["id"]

        patch_response = self.client.patch(
            f"/api/v1/me/educations/{education_id}",
            {"degree": "PhD"},
            **self._json_headers(),
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.json()["degree"], "PhD")

        list_response = self.client.get("/api/v1/me/educations", **self.headers)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()["items"][0]["id"], education_id)

        delete_response = self.client.delete(
            f"/api/v1/me/educations/{education_id}",
            **self.headers,
        )
        self.assertEqual(delete_response.status_code, 204)

    def test_shipping_address_crud_and_set_default(self):
        """Shipping address endpoints should manage addresses for the current user."""
        create_response = self.client.post(
            "/api/v1/me/shipping-addresses",
            {
                "receiver_name": "API User",
                "phone": "13800138000",
                "province": "Shanghai",
                "city": "Shanghai",
                "district": "Pudong",
                "address": "1 API Road",
                "is_default": True,
            },
            **self._json_headers(),
        )

        self.assertEqual(create_response.status_code, 201)
        address_id = create_response.json()["id"]

        update_response = self.client.patch(
            f"/api/v1/me/shipping-addresses/{address_id}",
            {"city": "Beijing", "is_default": True},
            **self._json_headers(),
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.json()["city"], "Beijing")

        set_default_response = self.client.post(
            f"/api/v1/me/shipping-addresses/{address_id}/set-default",
            **self.headers,
        )
        self.assertEqual(set_default_response.status_code, 200)

        delete_response = self.client.delete(
            f"/api/v1/me/shipping-addresses/{address_id}",
            **self.headers,
        )
        self.assertEqual(delete_response.status_code, 204)
        self.assertFalse(ShippingAddress.objects.filter(id=address_id).exists())

        list_response = self.client.get("/api/v1/me/shipping-addresses", **self.headers)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.json()["items"], [])

    def test_work_experience_list_reflects_entries(self):
        """Listing work experiences should reflect stored entries."""
        for title in ("Engineer", "Lead"):
            self.client.post(
                "/api/v1/me/work-experiences",
                {
                    "company_name": "OpenShare",
                    "title": title,
                    "start_date": "2024-01-01",
                    "end_date": "2025-01-01",
                },
                **self._json_headers(),
            )
        list_response = self.client.get("/api/v1/me/work-experiences", **self.headers)
        self.assertEqual(len(list_response.json()["items"]), 2)
        titles = {item["title"] for item in list_response.json()["items"]}
        self.assertEqual(titles, {"Engineer", "Lead"})

    def test_account_merge_requires_target_details(self):
        """Account merge creation enforces required inputs."""
        response = self.client.post(
            "/api/v1/me/account-merges",
            {},
            **self._json_headers(),
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "validation_error")

    def test_account_merge_create_review_and_reject(self):
        """Account merge flows should support creation and target-side rejection."""
        target = self.User.objects.create_user(
            username="merge_target",
            email="merge_target@example.com",
            password="StrongPass123!",
        )
        target_headers = {"HTTP_AUTHORIZATION": f"Bearer {create_access_token(target)}"}

        create_response = self.client.post(
            "/api/v1/me/account-merges",
            {"target_username": target.username},
            content_type="application/json",
            **self.headers,
        )

        self.assertEqual(create_response.status_code, 201)
        payload = create_response.json()
        merge_request = AccountMergeRequest.objects.get(id=payload["id"])

        review_response = self.client.get(
            f"/api/v1/me/account-merges/review/{merge_request.approve_token}",
            **target_headers,
        )
        self.assertEqual(review_response.status_code, 200)
        self.assertTrue(review_response.json()["can_reject"])

        reject_response = self.client.post(
            f"/api/v1/me/account-merges/review/{merge_request.approve_token}/reject",
            **target_headers,
        )
        self.assertEqual(reject_response.status_code, 200)
        merge_request.refresh_from_db()
        self.assertEqual(merge_request.status, AccountMergeRequest.Status.REJECTED)

    def test_account_merge_accept_flow(self):
        """Accepted merge should mark request as accepted and unavailable afterwards."""
        target = self.User.objects.create_user(
            username="merge_accept_target",
            email="merge_accept_target@example.com",
            password="StrongPass123!",
        )
        target_headers = {"HTTP_AUTHORIZATION": f"Bearer {create_access_token(target)}"}

        create_response = self.client.post(
            "/api/v1/me/account-merges",
            {"target_username": target.username},
            **self._json_headers(),
        )
        merge_request = AccountMergeRequest.objects.get(id=create_response.json()["id"])

        accept_response = self.client.post(
            f"/api/v1/me/account-merges/review/{merge_request.approve_token}/accept",
            **target_headers,
        )
        self.assertEqual(accept_response.status_code, 200)
        merge_request.refresh_from_db()
        self.assertEqual(merge_request.status, AccountMergeRequest.Status.ACCEPTED)

        second_accept = self.client.post(
            f"/api/v1/me/account-merges/review/{merge_request.approve_token}/accept",
            **target_headers,
        )
        self.assertEqual(second_accept.status_code, 409)

    def test_account_merge_review_token_returns_not_found_for_other_users(self):
        """Review tokens should not reveal their existence to non-target users."""
        target = self.User.objects.create_user(
            username="merge_visibility_target",
            email="merge_visibility_target@example.com",
            password="StrongPass123!",
        )
        outsider = self.User.objects.create_user(
            username="merge_visibility_outsider",
            email="merge_visibility_outsider@example.com",
            password="StrongPass123!",
        )
        outsider_headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(outsider)}"
        }

        create_response = self.client.post(
            "/api/v1/me/account-merges",
            {"target_username": target.username},
            **self._json_headers(),
        )
        merge_request = AccountMergeRequest.objects.get(id=create_response.json()["id"])

        review_response = self.client.get(
            f"/api/v1/me/account-merges/review/{merge_request.approve_token}",
            **outsider_headers,
        )
        self.assertEqual(review_response.status_code, 404)

        reject_response = self.client.post(
            f"/api/v1/me/account-merges/review/{merge_request.approve_token}/reject",
            **outsider_headers,
        )
        self.assertEqual(reject_response.status_code, 404)
