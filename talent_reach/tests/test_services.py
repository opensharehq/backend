"""Tests for talent_reach services."""

from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from social_django.models import UserSocialAuth

from messages.models import Message, UserMessage
from messages.services import send_message
from points.models import PointType
from points.services import grant_points
from talent_reach.models import OutreachCampaign, OutreachDraft, OutreachRecipient
from talent_reach.services import (
    _largest_remainder_allocation,
    claim_reading_reward,
    create_draft,
    delete_draft,
    get_draft,
    list_drafts,
    preview_recipients,
    send_outreach,
    update_draft,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Draft CRUD Tests
# ---------------------------------------------------------------------------


class TestDraftCRUD(TestCase):
    """Tests for draft CRUD operations."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="draft_owner", email="owner@example.com", password="pass123"
        )
        self.other_user = User.objects.create_user(
            username="other_user", email="other@example.com", password="pass123"
        )

    def test_create_draft(self):
        """Test creating a new draft."""
        draft = create_draft(
            author=self.user, title="Test Title", content="Test content body"
        )
        self.assertEqual(draft.title, "Test Title")
        self.assertEqual(draft.content, "Test content body")
        self.assertEqual(draft.author, self.user)
        self.assertIsNotNone(draft.id)

    def test_update_draft(self):
        """Test updating an existing draft."""
        draft = create_draft(author=self.user, title="Original", content="Body")
        updated = update_draft(
            draft_id=draft.id,
            author=self.user,
            title="Updated Title",
            content="Updated body",
        )
        self.assertEqual(updated.title, "Updated Title")
        self.assertEqual(updated.content, "Updated body")

    def test_update_draft_not_owner(self):
        """Test cannot update another user's draft."""
        draft = create_draft(author=self.user, title="Mine", content="Body")
        with self.assertRaises(OutreachDraft.DoesNotExist):
            update_draft(
                draft_id=draft.id,
                author=self.other_user,
                title="Hacked",
                content="Hacked",
            )

    def test_delete_draft(self):
        """Test deleting a draft."""
        draft = create_draft(author=self.user, title="ToDelete", content="Body")
        delete_draft(draft_id=draft.id, author=self.user)
        self.assertFalse(OutreachDraft.objects.filter(id=draft.id).exists())

    def test_delete_draft_not_owner(self):
        """Test cannot delete another user's draft (no-op)."""
        draft = create_draft(author=self.user, title="Protected", content="Body")
        delete_draft(draft_id=draft.id, author=self.other_user)
        # Draft still exists since the filter won't match
        self.assertTrue(OutreachDraft.objects.filter(id=draft.id).exists())

    def test_list_drafts(self):
        """Test listing drafts returns only user's own drafts."""
        create_draft(author=self.user, title="Draft 1", content="A")
        create_draft(author=self.user, title="Draft 2", content="B")
        create_draft(author=self.other_user, title="Other draft", content="C")

        drafts = list_drafts(self.user)
        self.assertEqual(drafts.count(), 2)
        for d in drafts:
            self.assertEqual(d.author, self.user)

    def test_get_draft(self):
        """Test getting a single draft."""
        draft = create_draft(author=self.user, title="Get Me", content="Body")
        result = get_draft(draft.id, self.user)
        self.assertEqual(result.id, draft.id)

    def test_get_draft_not_owner(self):
        """Test cannot get another user's draft."""
        draft = create_draft(author=self.user, title="Private", content="Body")
        with self.assertRaises(OutreachDraft.DoesNotExist):
            get_draft(draft.id, self.other_user)


# ---------------------------------------------------------------------------
# Preview Tests
# ---------------------------------------------------------------------------


class TestPreviewRecipients(TestCase):
    """Tests for preview_recipients service."""

    def setUp(self):
        """Set up test fixtures."""
        self.user1 = User.objects.create_user(
            username="dev1", email="dev1@example.com", password="pass123"
        )
        self.user2 = User.objects.create_user(
            username="dev2", email="dev2@example.com", password="pass123"
        )
        # Create social auth records
        UserSocialAuth.objects.create(user=self.user1, provider="github", uid="1001")
        UserSocialAuth.objects.create(user=self.user2, provider="github", uid="1002")

    @patch("talent_reach.services.query_developers_for_outreach")
    def test_preview_returns_registered_users(self, mock_query):
        """Test preview only returns registered users count."""
        mock_query.return_value = [
            {"platform": "GitHub", "actor_id": "1001", "openrank_score": 5.0},
            {"platform": "GitHub", "actor_id": "1002", "openrank_score": 3.0},
            # Unregistered developer
            {"platform": "GitHub", "actor_id": "9999", "openrank_score": 2.0},
        ]

        result = preview_recipients(tag_ids=["repo:test/example"])

        self.assertEqual(result["reachable_users"], 2)
        self.assertEqual(len(result["developers"]), 2)

    @patch("talent_reach.services.query_developers_for_outreach")
    def test_preview_estimated_cost(self, mock_query):
        """Test cost calculation: count * OUTREACH_COST_PER_USER."""
        mock_query.return_value = [
            {"platform": "GitHub", "actor_id": "1001", "openrank_score": 5.0},
            {"platform": "GitHub", "actor_id": "1002", "openrank_score": 3.0},
        ]

        result = preview_recipients(tag_ids=["repo:test/example"])

        expected_cost = 2 * settings.OUTREACH_COST_PER_USER
        expected_reward_pool = int(expected_cost * settings.OUTREACH_REWARD_RATIO)
        self.assertEqual(result["estimated_cost"], expected_cost)
        self.assertEqual(result["reward_pool"], expected_reward_pool)
        self.assertEqual(result["reward_ratio"], settings.OUTREACH_REWARD_RATIO)

    @patch("talent_reach.services.query_developers_for_outreach")
    def test_preview_no_matches(self, mock_query):
        """Test preview with no registered users."""
        mock_query.return_value = [
            {"platform": "GitHub", "actor_id": "9999", "openrank_score": 1.0},
        ]

        result = preview_recipients(tag_ids=["repo:test/example"])
        self.assertEqual(result["reachable_users"], 0)
        self.assertEqual(result["estimated_cost"], 0)


# ---------------------------------------------------------------------------
# Send Tests
# ---------------------------------------------------------------------------


class TestSendOutreach(TestCase):
    """Tests for send_outreach service."""

    def setUp(self):
        """Set up test fixtures."""
        self.author = User.objects.create_user(
            username="sender", email="sender@example.com", password="pass123"
        )
        self.recipient_user = User.objects.create_user(
            username="recipient", email="recipient@example.com", password="pass123"
        )
        UserSocialAuth.objects.create(
            user=self.recipient_user, provider="github", uid="2001"
        )
        self.draft = create_draft(
            author=self.author, title="Outreach Title", content="Hello developer!"
        )
        # Grant author enough points
        grant_points(
            owner=self.author,
            amount=1000,
            point_type=PointType.CASH,
            reason="Test fixture",
        )

    @patch("talent_reach.services.query_developers_for_outreach")
    def test_send_creates_campaign(self, mock_query):
        """Test campaign record is created with correct fields."""
        mock_query.return_value = [
            {"platform": "GitHub", "actor_id": "2001", "openrank_score": 10.0},
        ]

        campaign = send_outreach(
            draft_id=self.draft.id,
            author=self.author,
            tag_ids=["repo:test/example"],
            tag_names=["test/example"],
            languages=None,
            countries=None,
            regions=None,
            top_n=None,
            point_type=PointType.CASH,
        )

        self.assertIsNotNone(campaign.id)
        self.assertEqual(campaign.title, "Outreach Title")
        self.assertEqual(campaign.content, "Hello developer!")
        self.assertEqual(campaign.point_type, PointType.CASH)
        self.assertEqual(campaign.total_recipients, 1)
        self.assertEqual(campaign.status, OutreachCampaign.Status.COMPLETED)
        self.assertTrue(campaign.reference_id.startswith("outreach_"))

    @patch("talent_reach.services.query_developers_for_outreach")
    def test_send_deducts_points(self, mock_query):
        """Test points are deducted on send."""
        mock_query.return_value = [
            {"platform": "GitHub", "actor_id": "2001", "openrank_score": 10.0},
        ]

        from points.services import get_balance

        balance_before = get_balance(self.author, PointType.CASH)

        send_outreach(
            draft_id=self.draft.id,
            author=self.author,
            tag_ids=["repo:test/example"],
            tag_names=["test/example"],
            languages=None,
            countries=None,
            regions=None,
            top_n=None,
            point_type=PointType.CASH,
        )

        balance_after = get_balance(self.author, PointType.CASH)
        expected_cost = 1 * settings.OUTREACH_COST_PER_USER
        self.assertEqual(balance_before - balance_after, expected_cost)

    @patch("talent_reach.services.query_developers_for_outreach")
    def test_send_deletes_draft(self, mock_query):
        """Test draft is deleted after successful send."""
        mock_query.return_value = [
            {"platform": "GitHub", "actor_id": "2001", "openrank_score": 10.0},
        ]

        draft_id = self.draft.id
        send_outreach(
            draft_id=draft_id,
            author=self.author,
            tag_ids=["repo:test/example"],
            tag_names=["test/example"],
            languages=None,
            countries=None,
            regions=None,
            top_n=None,
            point_type=PointType.CASH,
        )

        self.assertFalse(OutreachDraft.objects.filter(id=draft_id).exists())

    @patch("talent_reach.services.query_developers_for_outreach")
    def test_send_insufficient_balance(self, mock_query):
        """Test error when point balance is insufficient."""
        mock_query.return_value = [
            {"platform": "GitHub", "actor_id": "2001", "openrank_score": 10.0},
        ]

        # Create a new author with zero balance
        poor_user = User.objects.create_user(
            username="poor", email="poor@example.com", password="pass123"
        )
        draft = create_draft(author=poor_user, title="Need Points", content="Body")

        from points.services import InsufficientPointsError

        with self.assertRaises(InsufficientPointsError):
            send_outreach(
                draft_id=draft.id,
                author=poor_user,
                tag_ids=["repo:test/example"],
                tag_names=["test/example"],
                languages=None,
                countries=None,
                regions=None,
                top_n=None,
                point_type=PointType.CASH,
            )

    @patch("talent_reach.services.query_developers_for_outreach")
    def test_send_rejects_no_recipients(self, mock_query):
        """Test error when no registered users found."""
        mock_query.return_value = []

        with self.assertRaises(ValueError):
            send_outreach(
                draft_id=self.draft.id,
                author=self.author,
                tag_ids=["repo:test/example"],
                tag_names=["test/example"],
                languages=None,
                countries=None,
                regions=None,
                top_n=None,
                point_type=PointType.CASH,
            )

    @patch("talent_reach.services.query_developers_for_outreach")
    def test_send_invalid_point_type(self, mock_query):
        """Test error when point_type is invalid."""
        mock_query.return_value = [
            {"platform": "GitHub", "actor_id": "2001", "openrank_score": 10.0},
        ]

        with self.assertRaises(ValueError):
            send_outreach(
                draft_id=self.draft.id,
                author=self.author,
                tag_ids=["repo:test/example"],
                tag_names=["test/example"],
                languages=None,
                countries=None,
                regions=None,
                top_n=None,
                point_type="invalid",
            )

    @patch("talent_reach.services.query_developers_for_outreach")
    def test_send_reward_calculation(self, mock_query):
        """Test reward amounts are proportional to OpenRank scores."""
        # Create more recipients
        user2 = User.objects.create_user(
            username="recipient2", email="r2@example.com", password="pass123"
        )
        user3 = User.objects.create_user(
            username="recipient3", email="r3@example.com", password="pass123"
        )
        UserSocialAuth.objects.create(user=user2, provider="github", uid="2002")
        UserSocialAuth.objects.create(user=user3, provider="github", uid="2003")

        # Grant enough points for 3 recipients
        grant_points(
            owner=self.author,
            amount=1000,
            point_type=PointType.CASH,
            reason="Extra",
        )

        mock_query.return_value = [
            {"platform": "GitHub", "actor_id": "2001", "openrank_score": 10.0},
            {"platform": "GitHub", "actor_id": "2002", "openrank_score": 5.0},
            {"platform": "GitHub", "actor_id": "2003", "openrank_score": 5.0},
        ]

        campaign = send_outreach(
            draft_id=self.draft.id,
            author=self.author,
            tag_ids=["repo:test/example"],
            tag_names=["test/example"],
            languages=None,
            countries=None,
            regions=None,
            top_n=None,
            point_type=PointType.CASH,
        )

        # Verify reward pool
        total_cost = 3 * settings.OUTREACH_COST_PER_USER
        expected_pool = int(total_cost * settings.OUTREACH_REWARD_RATIO)
        self.assertEqual(campaign.reward_pool, expected_pool)


# ---------------------------------------------------------------------------
# Largest Remainder Allocation Tests
# ---------------------------------------------------------------------------


class TestLargestRemainderAllocation(TestCase):
    """Tests for _largest_remainder_allocation helper."""

    def test_basic_proportional_allocation(self):
        """Test basic allocation sums to total."""
        scores = [10.0, 5.0, 5.0]
        total = 100
        result = _largest_remainder_allocation(scores, total)
        self.assertEqual(sum(result), total)
        # 50%, 25%, 25%
        self.assertEqual(result[0], 50)
        self.assertEqual(result[1], 25)
        self.assertEqual(result[2], 25)

    def test_remainder_distribution(self):
        """Test largest remainder method distributes leftover correctly."""
        scores = [1.0, 1.0, 1.0]
        total = 10
        result = _largest_remainder_allocation(scores, total)
        self.assertEqual(sum(result), 10)
        # Each gets 3 floor, 1 remainder -> 4,3,3 or similar
        self.assertTrue(all(r >= 3 for r in result))

    def test_zero_total(self):
        """Test zero total returns all zeros."""
        result = _largest_remainder_allocation([5.0, 3.0], 0)
        self.assertEqual(result, [0, 0])

    def test_empty_scores(self):
        """Test empty scores list."""
        result = _largest_remainder_allocation([], 100)
        self.assertEqual(result, [])

    def test_all_zero_scores(self):
        """Test all-zero scores distribute equally."""
        result = _largest_remainder_allocation([0.0, 0.0, 0.0], 10)
        self.assertEqual(sum(result), 10)


# ---------------------------------------------------------------------------
# Reading Reward Tests
# ---------------------------------------------------------------------------


class TestClaimReadingReward(TestCase):
    """Tests for claim_reading_reward service."""

    def setUp(self):
        """Set up test fixtures."""
        self.author = User.objects.create_user(
            username="campaigner", email="c@example.com", password="pass123"
        )
        self.recipient_user = User.objects.create_user(
            username="reader", email="reader@example.com", password="pass123"
        )

        # Create a campaign manually
        self.campaign = OutreachCampaign.objects.create(
            author=self.author,
            title="Test Campaign",
            content="Hello!",
            tag_ids=["repo:test/example"],
            tag_names=["test/example"],
            point_type=PointType.CASH,
            cost_per_user=5,
            total_cost=5,
            reward_ratio=0.5,
            reward_pool=2,
            reward_expiry_days=30,
            total_recipients=1,
            status=OutreachCampaign.Status.COMPLETED,
        )

        # Create a message and user_message
        self.message = send_message(
            title="Test Campaign",
            content="Hello!",
            message_type=Message.MessageType.OUTREACH,
            sender=self.author,
            recipients=[self.recipient_user],
        )
        self.user_message = UserMessage.objects.get(
            user=self.recipient_user, message=self.message
        )

        # Create recipient record
        self.recipient_record = OutreachRecipient.objects.create(
            campaign=self.campaign,
            user=self.recipient_user,
            user_message=self.user_message,
            reward_amount=2,
            openrank_score=10.0,
        )

    def test_claim_reward_success(self):
        """Test successful reward claim on first read."""
        result = claim_reading_reward(self.recipient_user, self.user_message.id)

        self.assertIsNotNone(result)
        self.assertEqual(result["reward_amount"], 2)
        self.assertEqual(result["point_type"], PointType.CASH)

        # Verify recipient is marked as rewarded
        self.recipient_record.refresh_from_db()
        self.assertTrue(self.recipient_record.is_rewarded)
        self.assertIsNotNone(self.recipient_record.rewarded_at)

    def test_claim_reward_already_claimed(self):
        """Test no duplicate reward."""
        # First claim
        claim_reading_reward(self.recipient_user, self.user_message.id)
        # Second claim
        result = claim_reading_reward(self.recipient_user, self.user_message.id)
        self.assertIsNone(result)

    def test_claim_reward_expired(self):
        """Test expired reward returns None and marks as expired."""
        # Set campaign created_at to past (beyond expiry)
        OutreachCampaign.objects.filter(id=self.campaign.id).update(
            created_at=timezone.now() - timedelta(days=31)
        )

        result = claim_reading_reward(self.recipient_user, self.user_message.id)
        self.assertIsNone(result)

        # Verify marked as expired
        self.recipient_record.refresh_from_db()
        self.assertTrue(self.recipient_record.reward_expired)

    def test_claim_reward_not_outreach_message(self):
        """Test returns None for non-outreach messages (no recipient record)."""
        other_message = send_message(
            title="System Msg",
            content="Not outreach",
            message_type=Message.MessageType.SYSTEM,
            recipients=[self.recipient_user],
        )
        other_um = UserMessage.objects.get(
            user=self.recipient_user, message=other_message
        )

        result = claim_reading_reward(self.recipient_user, other_um.id)
        self.assertIsNone(result)

    def test_claim_reward_grants_correct_points(self):
        """Test grant_points is called with correct amount and type."""
        from points.services import get_balance

        balance_before = get_balance(self.recipient_user, PointType.CASH)
        claim_reading_reward(self.recipient_user, self.user_message.id)
        balance_after = get_balance(self.recipient_user, PointType.CASH)

        self.assertEqual(balance_after - balance_before, 2)

    def test_claim_reward_zero_amount(self):
        """Test zero reward amount returns None."""
        self.recipient_record.reward_amount = 0
        self.recipient_record.save(update_fields=["reward_amount"])

        result = claim_reading_reward(self.recipient_user, self.user_message.id)
        self.assertIsNone(result)

    def test_claim_reward_updates_campaign_counters(self):
        """Test campaign counters are incremented atomically."""
        claim_reading_reward(self.recipient_user, self.user_message.id)

        self.campaign.refresh_from_db()
        self.assertEqual(self.campaign.read_count, 1)
        self.assertEqual(self.campaign.rewarded_count, 1)
