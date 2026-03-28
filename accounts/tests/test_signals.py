from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from social_django.models import UserSocialAuth

from accounts.signals import claim_pending_points_on_login

User = get_user_model()


class ClaimPendingPointsSignalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="signal-user", email="signal@example.com", password="testpass"
        )

    def _build_instance(self, provider="github"):
        return UserSocialAuth(user=self.user, provider=provider)

    @mock.patch("accounts.signals.logger.info")
    @mock.patch("points.allocation_services.AllocationService.claim_pending_points")
    def test_logs_claim_summary_when_grants_awarded(self, mock_claim, mock_logger):
        mock_claim.return_value = {"claimed_count": 2, "total_amount": 5000}
        social_auth = self._build_instance()

        claim_pending_points_on_login(UserSocialAuth, social_auth, created=True)

        mock_claim.assert_called_once_with(self.user)
        mock_logger.assert_called_once_with(
            "User %s claimed %d pending point grants totaling %d points",
            self.user.username,
            2,
            5000,
        )

    @mock.patch("accounts.signals.logger.info")
    @mock.patch("points.allocation_services.AllocationService.claim_pending_points")
    def test_skips_logging_when_no_grants(self, mock_claim, mock_logger):
        mock_claim.return_value = {"claimed_count": 0, "total_amount": 0}
        social_auth = self._build_instance()

        claim_pending_points_on_login(UserSocialAuth, social_auth, created=True)

        mock_logger.assert_not_called()
