"""Reading messages must tolerate unreconciled outreach funding without minting points."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.services.jwt_tokens import create_access_token
from messages.models import Message, UserMessage
from messages.services import send_message
from points.models import PointType
from points.services import get_balance, grant_points, spend_points
from talent_reach.models import OutreachCampaign, OutreachRecipient


class OutreachRewardReadTests(TestCase):
    """Exercise both read endpoints with real funding and recipient records."""

    def setUp(self):
        self.author = get_user_model().objects.create_user(username="outreach_author")
        self.reader = get_user_model().objects.create_user(username="outreach_reader")
        self.headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(self.reader)}"
        }

    def campaign(self, *, funded):
        campaign = OutreachCampaign.objects.create(
            author=self.author,
            title="Reading reward",
            content="Read this message",
            point_type=PointType.CASH,
            cost_per_user=2,
            total_cost=2,
            reward_ratio=0.5,
            reward_pool=1,
            reward_expiry_days=30,
            total_recipients=1,
            status=OutreachCampaign.Status.COMPLETED,
        )
        campaign.reference_id = f"outreach_{campaign.pk}"
        campaign.save(update_fields=["reference_id"])
        if funded:
            self.fund(campaign)
        message = send_message(
            title=campaign.title,
            content=campaign.content,
            message_type=Message.MessageType.OUTREACH,
            recipients=[self.reader],
        )
        recipient = OutreachRecipient.objects.create(
            campaign=campaign,
            user=self.reader,
            user_message=UserMessage.objects.get(message=message, user=self.reader),
            reward_amount=1,
        )
        return campaign, recipient

    def fund(self, campaign):
        grant_points(self.author, 2, PointType.CASH, "test funding")
        spend_points(
            self.author,
            2,
            PointType.CASH,
            "test debit",
            reference_id=campaign.reference_id,
        )

    def test_single_read_skips_unfunded_reward_and_allows_reconciled_retry(self):
        campaign, recipient = self.campaign(funded=False)
        url = f"/api/v1/messages/{recipient.user_message.message_id}/mark-read"
        with self.assertLogs("talent_reach.services", level="ERROR"):
            response = self.client.post(url, **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"updated": 1})
        recipient.refresh_from_db()
        self.assertTrue(recipient.user_message.is_read)
        self.assertFalse(recipient.is_rewarded)
        self.assertFalse(recipient.reward_expired)
        self.assertEqual(get_balance(self.reader), 0)

        self.fund(campaign)
        response = self.client.post(url, **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "updated": 0,
                "reward": {"reward_amount": 1, "point_type": PointType.CASH},
            },
        )
        replay = self.client.post(url, **self.headers)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json(), {"updated": 0})
        self.assertEqual(get_balance(self.reader), 1)

    def test_bulk_read_continues_after_unfunded_campaign(self):
        valid_campaign, valid = self.campaign(funded=True)
        invalid_campaign, invalid = self.campaign(funded=False)
        # Newest messages are visited first, so the invalid campaign precedes the valid one.
        self.assertEqual(
            UserMessage.objects.filter(user=self.reader).first(), invalid.user_message
        )
        normal = send_message(
            title="Notice", content="Ordinary message", recipients=[self.reader]
        )
        message_ids = [
            normal.pk,
            invalid.user_message.message_id,
            valid.user_message.message_id,
        ]
        with self.assertLogs("talent_reach.services", level="ERROR"):
            response = self.client.post(
                "/api/v1/messages/mark-read",
                {"message_ids": message_ids},
                content_type="application/json",
                **self.headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "updated": 3,
                "rewards": [{"reward_amount": 1, "point_type": PointType.CASH}],
            },
        )
        self.assertFalse(
            UserMessage.objects.filter(user=self.reader, is_read=False).exists()
        )
        valid.refresh_from_db()
        invalid.refresh_from_db()
        valid_campaign.refresh_from_db()
        invalid_campaign.refresh_from_db()
        self.assertTrue(valid.is_rewarded)
        self.assertFalse(invalid.is_rewarded)
        self.assertFalse(invalid.reward_expired)
        self.assertEqual(valid_campaign.rewarded_count, 1)
        self.assertEqual(invalid_campaign.rewarded_count, 0)
        self.assertEqual(get_balance(self.reader), 1)
