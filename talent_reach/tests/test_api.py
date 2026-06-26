"""Tests for talent_reach API endpoints."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from social_django.models import UserSocialAuth

from accounts.services.jwt_tokens import create_access_token
from points.models import PointType
from points.services import grant_points
from talent_reach.models import OutreachCampaign, OutreachDraft
from talent_reach.services import create_draft

User = get_user_model()


class TestDraftAPI(TestCase):
    """Tests for draft CRUD API endpoints."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="api_user", email="api@example.com", password="pass123"
        )
        self.other_user = User.objects.create_user(
            username="api_other", email="other@example.com", password="pass123"
        )
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.user)}"
        }
        self.other_headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.other_user)}"
        }

    def test_create_draft_authenticated(self):
        """POST /talent-reach/drafts - creates draft."""
        response = self.client.post(
            "/api/v1/talent-reach/drafts",
            {"title": "My Draft", "content": "Draft body"},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["title"], "My Draft")
        self.assertEqual(data["content"], "Draft body")
        self.assertIn("id", data)

    def test_create_draft_unauthenticated(self):
        """POST /talent-reach/drafts - returns 401."""
        response = self.client.post(
            "/api/v1/talent-reach/drafts",
            {"title": "Unauth", "content": "Body"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_create_draft_empty_title(self):
        """POST /talent-reach/drafts - rejects empty title."""
        response = self.client.post(
            "/api/v1/talent-reach/drafts",
            {"title": "  ", "content": "Body"},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_list_drafts(self):
        """GET /talent-reach/drafts - returns user's drafts."""
        create_draft(author=self.user, title="Draft A", content="A")
        create_draft(author=self.user, title="Draft B", content="B")
        create_draft(author=self.other_user, title="Other", content="C")

        response = self.client.get("/api/v1/talent-reach/drafts", **self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)

    def test_get_draft(self):
        """GET /talent-reach/drafts/{id} - returns draft detail."""
        draft = create_draft(author=self.user, title="Detail", content="Body")
        response = self.client.get(
            f"/api/v1/talent-reach/drafts/{draft.id}", **self.headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "Detail")

    def test_get_draft_not_owner(self):
        """GET /talent-reach/drafts/{id} - returns 404 for other user's draft."""
        draft = create_draft(author=self.user, title="Private", content="Body")
        response = self.client.get(
            f"/api/v1/talent-reach/drafts/{draft.id}", **self.other_headers
        )
        self.assertEqual(response.status_code, 404)

    def test_update_draft(self):
        """PUT /talent-reach/drafts/{id} - updates draft."""
        draft = create_draft(author=self.user, title="Old", content="Old body")
        response = self.client.put(
            f"/api/v1/talent-reach/drafts/{draft.id}",
            {"title": "New Title", "content": "New body"},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["title"], "New Title")
        self.assertEqual(response.json()["content"], "New body")

    def test_delete_draft(self):
        """DELETE /talent-reach/drafts/{id} - deletes draft."""
        draft = create_draft(author=self.user, title="Delete Me", content="Body")
        response = self.client.delete(
            f"/api/v1/talent-reach/drafts/{draft.id}", **self.headers
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(OutreachDraft.objects.filter(id=draft.id).exists())


class TestLanguagesAPI(TestCase):
    """Tests for languages endpoint."""

    @patch("talent_reach.api_v1.get_available_languages")
    def test_get_languages(self, mock_langs):
        """GET /talent-reach/languages - returns language list."""
        mock_langs.return_value = ["Python", "Java", "Go"]
        response = self.client.get("/api/v1/talent-reach/languages")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"], ["Python", "Java", "Go"])

    @patch("talent_reach.api_v1.get_available_languages")
    def test_get_languages_no_auth_required(self, mock_langs):
        """GET /talent-reach/languages - no authentication needed."""
        mock_langs.return_value = ["Rust"]
        response = self.client.get("/api/v1/talent-reach/languages")
        self.assertEqual(response.status_code, 200)


class TestPreviewAPI(TestCase):
    """Tests for preview endpoint."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="preview_user", email="preview@example.com", password="pass123"
        )
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.user)}"
        }
        # Create a registered developer
        self.dev_user = User.objects.create_user(
            username="developer", email="dev@example.com", password="pass123"
        )
        UserSocialAuth.objects.create(user=self.dev_user, provider="github", uid="3001")

    @patch("talent_reach.services.query_developers_for_outreach")
    def test_preview(self, mock_query):
        """POST /talent-reach/preview - returns user count and cost."""
        mock_query.return_value = [
            {"platform": "GitHub", "actor_id": "3001", "openrank_score": 7.5},
        ]

        response = self.client.post(
            "/api/v1/talent-reach/preview",
            {"tag_ids": ["repo:test/example"]},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["reachable_users"], 1)
        self.assertIn("estimated_cost", data)
        self.assertIn("reward_pool", data)

    @patch("talent_reach.services.query_developers_for_outreach")
    def test_preview_empty_tags(self, mock_query):
        """POST /talent-reach/preview - rejects empty tag_ids."""
        response = self.client.post(
            "/api/v1/talent-reach/preview",
            {"tag_ids": []},
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 422)

    def test_preview_unauthenticated(self):
        """POST /talent-reach/preview - returns 401 without auth."""
        response = self.client.post(
            "/api/v1/talent-reach/preview",
            {"tag_ids": ["repo:test/example"]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)


class TestSendAPI(TestCase):
    """Tests for send endpoint."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="send_user", email="send@example.com", password="pass123"
        )
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.user)}"
        }
        self.draft = create_draft(
            author=self.user, title="Send Draft", content="Hello world"
        )
        self.dev_user = User.objects.create_user(
            username="target_dev", email="target@example.com", password="pass123"
        )
        UserSocialAuth.objects.create(user=self.dev_user, provider="github", uid="4001")
        # Give user enough points
        grant_points(
            owner=self.user,
            amount=500,
            point_type=PointType.CASH,
            reason="Test fixture",
        )

    @patch("talent_reach.services.query_developers_for_outreach")
    def test_send_success(self, mock_query):
        """POST /talent-reach/send - returns campaign."""
        mock_query.return_value = [
            {"platform": "GitHub", "actor_id": "4001", "openrank_score": 8.0},
        ]

        response = self.client.post(
            "/api/v1/talent-reach/send",
            {
                "draft_id": self.draft.id,
                "tag_ids": ["repo:test/example"],
                "tag_names": ["test/example"],
                "point_type": "cash",
            },
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["title"], "Send Draft")
        self.assertEqual(data["status"], "completed")
        self.assertIn("id", data)

    @patch("talent_reach.services.query_developers_for_outreach")
    def test_send_invalid_point_type(self, mock_query):
        """POST /talent-reach/send - rejects invalid point_type."""
        mock_query.return_value = [
            {"platform": "GitHub", "actor_id": "4001", "openrank_score": 8.0},
        ]

        response = self.client.post(
            "/api/v1/talent-reach/send",
            {
                "draft_id": self.draft.id,
                "tag_ids": ["repo:test/example"],
                "tag_names": ["test/example"],
                "point_type": "invalid",
            },
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 422)

    @patch("talent_reach.services.query_developers_for_outreach")
    def test_send_insufficient_points(self, mock_query):
        """POST /talent-reach/send - returns 409 when insufficient points."""
        mock_query.return_value = [
            {"platform": "GitHub", "actor_id": "4001", "openrank_score": 8.0},
        ]

        # Create user with no points
        poor_user = User.objects.create_user(
            username="poor_api", email="poor_api@example.com", password="pass123"
        )
        poor_headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(poor_user)}"
        }
        draft = create_draft(author=poor_user, title="Poor Draft", content="Body")

        response = self.client.post(
            "/api/v1/talent-reach/send",
            {
                "draft_id": draft.id,
                "tag_ids": ["repo:test/example"],
                "tag_names": ["test/example"],
                "point_type": "cash",
            },
            content_type="application/json",
            **poor_headers,
        )
        self.assertEqual(response.status_code, 409)

    def test_send_unauthenticated(self):
        """POST /talent-reach/send - returns 401 without auth."""
        response = self.client.post(
            "/api/v1/talent-reach/send",
            {
                "draft_id": self.draft.id,
                "tag_ids": ["repo:test/example"],
                "tag_names": ["test/example"],
                "point_type": "cash",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    @patch("talent_reach.services.query_developers_for_outreach")
    def test_send_draft_not_found(self, mock_query):
        """POST /talent-reach/send - returns 404 when draft doesn't exist."""
        mock_query.return_value = [
            {"platform": "GitHub", "actor_id": "4001", "openrank_score": 8.0},
        ]

        response = self.client.post(
            "/api/v1/talent-reach/send",
            {
                "draft_id": 99999,
                "tag_ids": ["repo:test/example"],
                "tag_names": ["test/example"],
                "point_type": "cash",
            },
            content_type="application/json",
            **self.headers,
        )
        self.assertEqual(response.status_code, 404)


class TestCampaignAPI(TestCase):
    """Tests for campaign list and detail endpoints."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="campaign_user", email="camp@example.com", password="pass123"
        )
        self.other_user = User.objects.create_user(
            username="campaign_other", email="camp_o@example.com", password="pass123"
        )
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.user)}"
        }

        # Create campaigns
        self.campaign = OutreachCampaign.objects.create(
            author=self.user,
            title="My Campaign",
            content="Content",
            tag_ids=["repo:test/example"],
            tag_names=["test/example"],
            point_type=PointType.CASH,
            cost_per_user=5,
            total_cost=10,
            reward_ratio=0.5,
            reward_pool=5,
            reward_expiry_days=30,
            total_recipients=2,
            status=OutreachCampaign.Status.COMPLETED,
        )
        # Other user's campaign
        OutreachCampaign.objects.create(
            author=self.other_user,
            title="Other Campaign",
            content="Other",
            tag_ids=["repo:other/repo"],
            tag_names=["other/repo"],
            point_type=PointType.GIFT,
            cost_per_user=5,
            total_cost=5,
            reward_ratio=0.5,
            reward_pool=2,
            reward_expiry_days=30,
            total_recipients=1,
            status=OutreachCampaign.Status.COMPLETED,
        )

    def test_list_campaigns(self):
        """GET /talent-reach/campaigns - returns user's campaigns."""
        response = self.client.get("/api/v1/talent-reach/campaigns", **self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["title"], "My Campaign")

    def test_get_campaign_detail(self):
        """GET /talent-reach/campaigns/{id} - returns campaign with stats."""
        response = self.client.get(
            f"/api/v1/talent-reach/campaigns/{self.campaign.id}", **self.headers
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["title"], "My Campaign")
        self.assertIn("delivered_count", data)
        self.assertIn("read_count", data)
        self.assertIn("rewarded_count", data)

    def test_get_campaign_detail_not_owner(self):
        """GET /talent-reach/campaigns/{id} - returns 404 for other's campaign."""
        other_headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.other_user)}"
        }
        response = self.client.get(
            f"/api/v1/talent-reach/campaigns/{self.campaign.id}", **other_headers
        )
        self.assertEqual(response.status_code, 404)

    def test_list_campaigns_unauthenticated(self):
        """GET /talent-reach/campaigns - returns 401 without auth."""
        response = self.client.get("/api/v1/talent-reach/campaigns")
        self.assertEqual(response.status_code, 401)
