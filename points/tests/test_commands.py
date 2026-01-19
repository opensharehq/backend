"""Tests for points management commands."""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from accounts.models import Organization, User
from points import services
from points.models import PointType, Tag


class GrantPointsCommandTests(TestCase):
    """Tests for grant_points management command."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.org = Organization.objects.create(name="Test Org", slug="test-org")
        self.tag = Tag.objects.create(name="活动", slug="event")

    def test_grant_cash_to_user_by_username(self):
        """Test granting cash points to user by username."""
        out = StringIO()
        call_command(
            "grant_points",
            user="testuser",
            amount=100,
            type="cash",
            reason="测试奖励",
            stdout=out,
        )

        balance = services.get_balance(self.user, PointType.CASH)
        self.assertEqual(balance, 100)
        self.assertIn("成功发放", out.getvalue())

    def test_grant_cash_to_user_by_id(self):
        """Test granting cash points to user by ID."""
        out = StringIO()
        call_command(
            "grant_points",
            user_id=self.user.id,
            amount=50,
            type="cash",
            reason="测试奖励",
            stdout=out,
        )

        balance = services.get_balance(self.user, PointType.CASH)
        self.assertEqual(balance, 50)

    def test_grant_gift_to_user(self):
        """Test granting gift points to user."""
        out = StringIO()
        call_command(
            "grant_points",
            user="testuser",
            amount=75,
            type="gift",
            reason="礼物",
            stdout=out,
        )

        balance = services.get_balance(self.user, PointType.GIFT)
        self.assertEqual(balance, 75)

    def test_grant_gift_with_tag(self):
        """Test granting gift points with tag."""
        out = StringIO()
        call_command(
            "grant_points",
            user="testuser",
            amount=100,
            type="gift",
            tag="event",
            reason="活动奖励",
            stdout=out,
        )

        balance = services.get_balance(self.user, PointType.GIFT, tag_slug="event")
        self.assertEqual(balance, 100)
        self.assertIn("标签: event", out.getvalue())

    def test_grant_to_org_by_slug(self):
        """Test granting points to organization by slug."""
        out = StringIO()
        call_command(
            "grant_points",
            org="test-org",
            amount=200,
            type="cash",
            reason="组织奖励",
            stdout=out,
        )

        balance = services.get_balance(self.org, PointType.CASH)
        self.assertEqual(balance, 200)
        self.assertIn("组织", out.getvalue())

    def test_grant_to_org_by_id(self):
        """Test granting points to organization by ID."""
        out = StringIO()
        call_command(
            "grant_points",
            org_id=self.org.id,
            amount=150,
            type="cash",
            reason="组织奖励",
            stdout=out,
        )

        balance = services.get_balance(self.org, PointType.CASH)
        self.assertEqual(balance, 150)

    def test_grant_with_reference_id(self):
        """Test granting points with reference ID."""
        out = StringIO()
        call_command(
            "grant_points",
            user="testuser",
            amount=100,
            type="cash",
            reason="外部系统",
            reference_id="ext:12345",
            stdout=out,
        )

        wallet = services.get_or_create_wallet(self.user)
        source = wallet.sources.first()
        self.assertEqual(source.reference_id, "ext:12345")

    def test_grant_with_expiration(self):
        """Test granting points with expiration date."""
        out = StringIO()
        call_command(
            "grant_points",
            user="testuser",
            amount=100,
            type="gift",
            reason="限时",
            expires="2025-12-31",
            stdout=out,
        )

        wallet = services.get_or_create_wallet(self.user)
        source = wallet.sources.first()
        self.assertIsNotNone(source.expires_at)
        self.assertIn("过期时间: 2025-12-31", out.getvalue())

    def test_user_not_found_fails(self):
        """Test that non-existent user fails."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                "grant_points",
                user="nonexistent",
                amount=100,
                type="cash",
                reason="测试",
            )
        self.assertIn("用户不存在", str(cm.exception))

    def test_org_not_found_fails(self):
        """Test that non-existent org fails."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                "grant_points",
                org="nonexistent",
                amount=100,
                type="cash",
                reason="测试",
            )
        self.assertIn("组织不存在", str(cm.exception))

    def test_zero_amount_fails(self):
        """Test that zero amount fails."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                "grant_points",
                user="testuser",
                amount=0,
                type="cash",
                reason="测试",
            )
        self.assertIn("大于 0", str(cm.exception))

    def test_tag_on_cash_fails(self):
        """Test that tag on cash points fails."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                "grant_points",
                user="testuser",
                amount=100,
                type="cash",
                tag="event",
                reason="测试",
            )
        self.assertIn("只有礼物积分可以设置标签", str(cm.exception))

    def test_invalid_tag_fails(self):
        """Test that invalid tag fails."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                "grant_points",
                user="testuser",
                amount=100,
                type="gift",
                tag="nonexistent",
                reason="测试",
            )
        self.assertIn("标签不存在", str(cm.exception))

    def test_invalid_date_format_fails(self):
        """Test that invalid date format fails."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                "grant_points",
                user="testuser",
                amount=100,
                type="gift",
                expires="invalid-date",
                reason="测试",
            )
        self.assertIn("无效的日期格式", str(cm.exception))

    def test_user_id_not_found_fails(self):
        """Test that non-existent user ID fails."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                "grant_points",
                user_id=99999,
                amount=100,
                type="cash",
                reason="测试",
            )
        self.assertIn("用户不存在", str(cm.exception))

    def test_org_id_not_found_fails(self):
        """Test that non-existent org ID fails."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                "grant_points",
                org_id=99999,
                amount=100,
                type="cash",
                reason="测试",
            )
        self.assertIn("组织不存在", str(cm.exception))

    def test_no_target_specified_fails(self):
        """Test that no target specified fails."""
        with self.assertRaises(CommandError) as cm:
            call_command(
                "grant_points",
                amount=100,
                type="cash",
                reason="测试",
            )
        # Django argparse returns English error for missing arguments
        self.assertIn("required", str(cm.exception).lower())
