"""Tests for points services."""

from django.test import TestCase
from django.utils import timezone

from accounts.models import Organization, OrganizationMembership, User
from points import services
from points.models import (
    PointTransaction,
    PointType,
    Tag,
    TransactionType,
    WithdrawalStatus,
)


class GetOrCreateWalletTests(TestCase):
    """Tests for get_or_create_wallet function."""

    def test_creates_wallet_for_user(self):
        """Test creating wallet for user."""
        user = User.objects.create_user(username="testuser", password="testpass")
        wallet = services.get_or_create_wallet(user)

        self.assertIsNotNone(wallet)
        self.assertEqual(wallet.owner, user)

    def test_creates_wallet_for_organization(self):
        """Test creating wallet for organization."""
        org = Organization.objects.create(name="Test Org", slug="test-org")
        wallet = services.get_or_create_wallet(org)

        self.assertIsNotNone(wallet)
        self.assertEqual(wallet.owner, org)

    def test_returns_existing_wallet(self):
        """Test that existing wallet is returned."""
        user = User.objects.create_user(username="testuser", password="testpass")
        wallet1 = services.get_or_create_wallet(user)
        wallet2 = services.get_or_create_wallet(user)

        self.assertEqual(wallet1.id, wallet2.id)


class GetBalanceTests(TestCase):
    """Tests for get_balance function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.tag = Tag.objects.create(name="活动", slug="event")

    def test_get_total_balance_empty(self):
        """Test getting total balance when empty."""
        balance = services.get_balance(self.user)
        self.assertEqual(balance, 0)

    def test_get_cash_balance(self):
        """Test getting cash balance."""
        services.grant_points(self.user, 100, PointType.CASH, "Test")
        balance = services.get_balance(self.user, PointType.CASH)
        self.assertEqual(balance, 100)

    def test_get_gift_balance(self):
        """Test getting gift balance."""
        services.grant_points(self.user, 50, PointType.GIFT, "Test")
        balance = services.get_balance(self.user, PointType.GIFT)
        self.assertEqual(balance, 50)

    def test_get_gift_balance_with_tag(self):
        """Test getting gift balance filtered by tag."""
        services.grant_points(
            self.user, 100, PointType.GIFT, "Event reward", tag_slug="event"
        )
        services.grant_points(self.user, 50, PointType.GIFT, "General")

        total_gift = services.get_balance(self.user, PointType.GIFT)
        event_gift = services.get_balance(self.user, PointType.GIFT, tag_slug="event")

        self.assertEqual(total_gift, 150)
        self.assertEqual(event_gift, 100)

    def test_get_balance_invalid_type(self):
        """Test that invalid point type raises error."""
        with self.assertRaises(services.InvalidPointOperationError):
            services.get_balance(self.user, "invalid")


class GetDetailedBalanceTests(TestCase):
    """Tests for get_detailed_balance function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.tag = Tag.objects.create(name="活动", slug="event")

    def test_detailed_balance_empty(self):
        """Test detailed balance when empty."""
        balance = services.get_detailed_balance(self.user)

        self.assertEqual(balance["total"], 0)
        self.assertEqual(balance["cash"], 0)
        self.assertEqual(balance["gift"], 0)
        self.assertEqual(balance["by_tag"], {})

    def test_detailed_balance_with_points(self):
        """Test detailed balance with various points."""
        services.grant_points(self.user, 100, PointType.CASH, "Cash")
        services.grant_points(self.user, 50, PointType.GIFT, "Gift no tag")
        services.grant_points(self.user, 30, PointType.GIFT, "Event", tag_slug="event")

        balance = services.get_detailed_balance(self.user)

        self.assertEqual(balance["total"], 180)
        self.assertEqual(balance["cash"], 100)
        self.assertEqual(balance["gift"], 80)
        self.assertEqual(balance["gift_no_tag"], 50)
        self.assertEqual(balance["by_tag"]["event"], 30)


class GrantPointsTests(TestCase):
    """Tests for grant_points function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.admin = User.objects.create_user(username="admin", password="adminpass")
        self.tag = Tag.objects.create(name="活动", slug="event")

    def test_grant_cash_points(self):
        """Test granting cash points."""
        source = services.grant_points(self.user, 100, PointType.CASH, "注册奖励")

        self.assertEqual(source.point_type, PointType.CASH)
        self.assertEqual(source.original_amount, 100)
        self.assertEqual(source.remaining_amount, 100)

        # Check transaction was created
        txn = PointTransaction.objects.get(source=source)
        self.assertEqual(txn.transaction_type, TransactionType.EARN)
        self.assertEqual(txn.amount, 100)

    def test_grant_gift_points(self):
        """Test granting gift points."""
        source = services.grant_points(self.user, 50, PointType.GIFT, "活动奖励")

        self.assertEqual(source.point_type, PointType.GIFT)
        self.assertEqual(source.original_amount, 50)

    def test_grant_points_with_tag(self):
        """Test granting points with tag."""
        source = services.grant_points(
            self.user, 100, PointType.GIFT, "Event reward", tag_slug="event"
        )

        self.assertEqual(source.tag, self.tag)

    def test_grant_points_with_expiration(self):
        """Test granting points with expiration."""
        expires = timezone.now() + timezone.timedelta(days=30)
        source = services.grant_points(
            self.user, 100, PointType.GIFT, "Limited time", expires_at=expires
        )

        self.assertEqual(source.expires_at, expires)

    def test_grant_points_with_reference(self):
        """Test granting points with reference ID."""
        source = services.grant_points(
            self.user, 100, PointType.CASH, "External", reference_id="ext:123"
        )

        self.assertEqual(source.reference_id, "ext:123")

    def test_grant_points_with_creator(self):
        """Test granting points with creator."""
        source = services.grant_points(
            self.user, 100, PointType.CASH, "Admin grant", created_by=self.admin
        )

        self.assertEqual(source.created_by, self.admin)

    def test_grant_points_zero_amount_fails(self):
        """Test that granting zero points fails."""
        with self.assertRaises(services.InvalidPointOperationError):
            services.grant_points(self.user, 0, PointType.CASH, "Test")

    def test_grant_points_negative_amount_fails(self):
        """Test that granting negative points fails."""
        with self.assertRaises(services.InvalidPointOperationError):
            services.grant_points(self.user, -100, PointType.CASH, "Test")

    def test_grant_cash_with_tag_fails(self):
        """Test that granting cash points with tag fails."""
        with self.assertRaises(services.InvalidPointOperationError):
            services.grant_points(
                self.user, 100, PointType.CASH, "Test", tag_slug="event"
            )

    def test_grant_points_invalid_tag_fails(self):
        """Test that invalid tag slug fails."""
        with self.assertRaises(services.InvalidPointOperationError):
            services.grant_points(
                self.user, 100, PointType.GIFT, "Test", tag_slug="nonexistent"
            )


class SpendPointsTests(TestCase):
    """Tests for spend_points function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.tag = Tag.objects.create(name="活动", slug="event")
        # Grant some initial points
        services.grant_points(self.user, 100, PointType.CASH, "Initial cash")
        services.grant_points(self.user, 200, PointType.GIFT, "Initial gift")
        services.grant_points(
            self.user, 50, PointType.GIFT, "Event gift", tag_slug="event"
        )

    def test_spend_cash_points(self):
        """Test spending cash points."""
        transactions = services.spend_points(
            self.user, 50, PointType.CASH, "Withdrawal"
        )

        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].amount, -50)
        self.assertEqual(services.get_balance(self.user, PointType.CASH), 50)

    def test_spend_gift_points(self):
        """Test spending gift points."""
        transactions = services.spend_points(self.user, 100, PointType.GIFT, "Redeem")

        self.assertGreater(len(transactions), 0)
        total_spent = sum(abs(t.amount) for t in transactions)
        self.assertEqual(total_spent, 100)

    def test_spend_points_with_tag_filter(self):
        """Test spending points filtered by tag."""
        transactions = services.spend_points(
            self.user, 30, PointType.GIFT, "Event redeem", tag_slug="event"
        )

        self.assertGreater(len(transactions), 0)
        for txn in transactions:
            self.assertEqual(txn.tag, self.tag)

        # Check event balance reduced
        self.assertEqual(
            services.get_balance(self.user, PointType.GIFT, tag_slug="event"), 20
        )

    def test_spend_points_fifo(self):
        """Test that points are spent in FIFO order."""
        # Grant more points with delay (to ensure different created_at)
        services.grant_points(self.user, 50, PointType.CASH, "Second cash")

        # Spend more than first grant
        services.spend_points(self.user, 120, PointType.CASH, "Large spend")

        # Check remaining
        self.assertEqual(services.get_balance(self.user, PointType.CASH), 30)

    def test_spend_points_insufficient_fails(self):
        """Test that spending more than available fails."""
        with self.assertRaises(services.InsufficientPointsError):
            services.spend_points(self.user, 1000, PointType.CASH, "Too much")

    def test_spend_zero_amount_fails(self):
        """Test that spending zero fails."""
        with self.assertRaises(services.InvalidPointOperationError):
            services.spend_points(self.user, 0, PointType.CASH, "Zero")

    def test_spend_cash_with_tag_fails(self):
        """Test that spending cash with tag filter fails."""
        with self.assertRaises(services.InvalidPointOperationError):
            services.spend_points(
                self.user, 50, PointType.CASH, "Test", tag_slug="event"
            )


class WithdrawalRequestTests(TestCase):
    """Tests for withdrawal request functions."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.admin = User.objects.create_superuser(
            username="admin", password="adminpass", email="admin@test.com"
        )
        # Grant cash points
        services.grant_points(self.user, 1000, PointType.CASH, "Initial cash")

    def test_create_withdrawal_request(self):
        """Test creating withdrawal request."""
        withdrawal = services.create_withdrawal_request(
            self.user, 500, "张三", "13800138000", "中国银行", "6222000000000000000"
        )

        self.assertEqual(withdrawal.amount, 500)
        self.assertEqual(withdrawal.status, WithdrawalStatus.PENDING)
        self.assertEqual(withdrawal.real_name, "张三")

    def test_create_withdrawal_insufficient_balance_fails(self):
        """Test that creating withdrawal with insufficient balance fails."""
        with self.assertRaises(services.InsufficientPointsError):
            services.create_withdrawal_request(
                self.user, 2000, "张三", "13800138000", "中国银行", "6222"
            )

    def test_create_withdrawal_with_pending_fails(self):
        """Test that creating withdrawal when pending exists fails."""
        services.create_withdrawal_request(
            self.user, 100, "张三", "13800138000", "中国银行", "6222"
        )

        with self.assertRaises(services.WithdrawalError):
            services.create_withdrawal_request(
                self.user, 200, "张三", "13800138000", "中国银行", "6222"
            )

    def test_approve_withdrawal(self):
        """Test approving withdrawal request."""
        withdrawal = services.create_withdrawal_request(
            self.user, 500, "张三", "13800138000", "中国银行", "6222"
        )

        approved = services.approve_withdrawal(withdrawal.id, self.admin)

        self.assertEqual(approved.status, WithdrawalStatus.APPROVED)
        self.assertEqual(approved.processed_by, self.admin)
        self.assertIsNotNone(approved.processed_at)
        self.assertIsNotNone(approved.transaction)

        # Check balance deducted
        self.assertEqual(services.get_balance(self.user, PointType.CASH), 500)

    def test_approve_non_pending_fails(self):
        """Test that approving non-pending withdrawal fails."""
        withdrawal = services.create_withdrawal_request(
            self.user, 500, "张三", "13800138000", "中国银行", "6222"
        )
        services.approve_withdrawal(withdrawal.id, self.admin)

        with self.assertRaises(services.WithdrawalError):
            services.approve_withdrawal(withdrawal.id, self.admin)

    def test_complete_withdrawal(self):
        """Test completing withdrawal."""
        withdrawal = services.create_withdrawal_request(
            self.user, 500, "张三", "13800138000", "中国银行", "6222"
        )
        services.approve_withdrawal(withdrawal.id, self.admin)

        completed = services.complete_withdrawal(withdrawal.id, self.admin)

        self.assertEqual(completed.status, WithdrawalStatus.COMPLETED)

    def test_complete_non_approved_fails(self):
        """Test that completing non-approved withdrawal fails."""
        withdrawal = services.create_withdrawal_request(
            self.user, 500, "张三", "13800138000", "中国银行", "6222"
        )

        with self.assertRaises(services.WithdrawalError):
            services.complete_withdrawal(withdrawal.id, self.admin)

    def test_reject_withdrawal(self):
        """Test rejecting withdrawal."""
        withdrawal = services.create_withdrawal_request(
            self.user, 500, "张三", "13800138000", "中国银行", "6222"
        )

        rejected = services.reject_withdrawal(withdrawal.id, self.admin, "信息不完整")

        self.assertEqual(rejected.status, WithdrawalStatus.REJECTED)
        self.assertEqual(rejected.admin_note, "信息不完整")

        # Check balance NOT deducted
        self.assertEqual(services.get_balance(self.user, PointType.CASH), 1000)

    def test_cancel_withdrawal_by_user(self):
        """Test canceling withdrawal by user."""
        withdrawal = services.create_withdrawal_request(
            self.user, 500, "张三", "13800138000", "中国银行", "6222"
        )

        cancelled = services.cancel_withdrawal(withdrawal.id, self.user)

        self.assertEqual(cancelled.status, WithdrawalStatus.CANCELLED)

    def test_cancel_withdrawal_by_other_user_fails(self):
        """Test that other user cannot cancel withdrawal."""
        other_user = User.objects.create_user(username="other", password="pass")
        withdrawal = services.create_withdrawal_request(
            self.user, 500, "张三", "13800138000", "中国银行", "6222"
        )

        with self.assertRaises(services.WithdrawalError):
            services.cancel_withdrawal(withdrawal.id, other_user)

    def test_cancel_non_pending_fails(self):
        """Test that canceling non-pending withdrawal fails."""
        withdrawal = services.create_withdrawal_request(
            self.user, 500, "张三", "13800138000", "中国银行", "6222"
        )
        services.approve_withdrawal(withdrawal.id, self.admin)

        with self.assertRaises(services.WithdrawalError):
            services.cancel_withdrawal(withdrawal.id, self.user)


class OrganizationWithdrawalTests(TestCase):
    """Tests for organization withdrawal permissions."""

    def setUp(self):
        """Set up test fixtures."""
        self.org = Organization.objects.create(name="Test Org", slug="test-org")
        self.owner = User.objects.create_user(username="owner", password="pass")
        self.admin_user = User.objects.create_user(username="admin", password="pass")
        self.member = User.objects.create_user(username="member", password="pass")

        OrganizationMembership.objects.create(
            user=self.owner,
            organization=self.org,
            role=OrganizationMembership.Role.OWNER,
        )
        OrganizationMembership.objects.create(
            user=self.admin_user,
            organization=self.org,
            role=OrganizationMembership.Role.ADMIN,
        )
        OrganizationMembership.objects.create(
            user=self.member,
            organization=self.org,
            role=OrganizationMembership.Role.MEMBER,
        )

        services.grant_points(self.org, 1000, PointType.CASH, "Initial")

    def test_owner_can_cancel_org_withdrawal(self):
        """Test that owner can cancel org withdrawal."""
        withdrawal = services.create_withdrawal_request(
            self.org, 500, "张三", "13800138000", "中国银行", "6222"
        )

        cancelled = services.cancel_withdrawal(withdrawal.id, self.owner)
        self.assertEqual(cancelled.status, WithdrawalStatus.CANCELLED)

    def test_admin_can_cancel_org_withdrawal(self):
        """Test that admin can cancel org withdrawal."""
        withdrawal = services.create_withdrawal_request(
            self.org, 500, "张三", "13800138000", "中国银行", "6222"
        )

        cancelled = services.cancel_withdrawal(withdrawal.id, self.admin_user)
        self.assertEqual(cancelled.status, WithdrawalStatus.CANCELLED)

    def test_member_cannot_cancel_org_withdrawal(self):
        """Test that regular member cannot cancel org withdrawal."""
        withdrawal = services.create_withdrawal_request(
            self.org, 500, "张三", "13800138000", "中国银行", "6222"
        )

        with self.assertRaises(services.WithdrawalError):
            services.cancel_withdrawal(withdrawal.id, self.member)


class EdgeCaseTests(TestCase):
    """Tests for edge cases and error handling."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.admin = User.objects.create_user(
            username="admin", password="pass", is_staff=True
        )

    def test_grant_points_invalid_type(self):
        """Test that invalid point type fails."""
        with self.assertRaises(services.InvalidPointOperationError) as cm:
            services.grant_points(self.user, 100, "invalid", "Test")
        self.assertIn("无效的积分类型", str(cm.exception))

    def test_spend_points_invalid_type(self):
        """Test that invalid point type in spend fails."""
        services.grant_points(self.user, 100, PointType.CASH, "Initial")
        with self.assertRaises(services.InvalidPointOperationError) as cm:
            services.spend_points(self.user, 50, "invalid", "Test")
        self.assertIn("无效的积分类型", str(cm.exception))

    def test_create_withdrawal_zero_amount(self):
        """Test that zero amount withdrawal fails."""
        services.grant_points(self.user, 1000, PointType.CASH, "Initial")
        with self.assertRaises(services.WithdrawalError) as cm:
            services.create_withdrawal_request(
                self.user, 0, "张三", "13800138000", "中国银行", "6222"
            )
        self.assertIn("大于 0", str(cm.exception))

    def test_approve_nonexistent_withdrawal(self):
        """Test that approving nonexistent withdrawal fails."""
        with self.assertRaises(services.WithdrawalError) as cm:
            services.approve_withdrawal(99999, self.admin)
        self.assertIn("不存在", str(cm.exception))

    def test_reject_nonexistent_withdrawal(self):
        """Test that rejecting nonexistent withdrawal fails."""
        with self.assertRaises(services.WithdrawalError) as cm:
            services.reject_withdrawal(99999, self.admin, "No reason")
        self.assertIn("不存在", str(cm.exception))

    def test_complete_nonexistent_withdrawal(self):
        """Test that completing nonexistent withdrawal fails."""
        with self.assertRaises(services.WithdrawalError) as cm:
            services.complete_withdrawal(99999, self.admin)
        self.assertIn("不存在", str(cm.exception))

    def test_cancel_nonexistent_withdrawal(self):
        """Test that canceling nonexistent withdrawal fails."""
        with self.assertRaises(services.WithdrawalError) as cm:
            services.cancel_withdrawal(99999, self.user)
        self.assertIn("不存在", str(cm.exception))

    def test_approve_withdrawal_insufficient_balance(self):
        """Test that approving withdrawal with insufficient balance fails."""
        # Grant 1000 points, create withdrawal for 500
        services.grant_points(self.user, 1000, PointType.CASH, "Initial")
        withdrawal = services.create_withdrawal_request(
            self.user, 500, "张三", "13800138000", "中国银行", "6222"
        )

        # Spend points to reduce balance below withdrawal amount
        services.spend_points(self.user, 600, PointType.CASH, "Spend")

        # Now try to approve withdrawal - should fail due to insufficient balance
        with self.assertRaises(services.InsufficientPointsError) as cm:
            services.approve_withdrawal(withdrawal.id, self.admin)
        self.assertIn("不足", str(cm.exception))

    def test_complete_withdrawal_with_note(self):
        """Test completing withdrawal with admin note."""
        services.grant_points(self.user, 1000, PointType.CASH, "Initial")
        withdrawal = services.create_withdrawal_request(
            self.user, 500, "张三", "13800138000", "中国银行", "6222"
        )
        services.approve_withdrawal(withdrawal.id, self.admin)

        completed = services.complete_withdrawal(
            withdrawal.id, self.admin, note="已打款"
        )

        self.assertEqual(completed.status, WithdrawalStatus.COMPLETED)
        self.assertIn("已打款", completed.admin_note)

    def test_reject_non_pending_withdrawal(self):
        """Test that rejecting non-pending withdrawal fails."""
        services.grant_points(self.user, 1000, PointType.CASH, "Initial")
        withdrawal = services.create_withdrawal_request(
            self.user, 500, "张三", "13800138000", "中国银行", "6222"
        )
        # Approve first
        services.approve_withdrawal(withdrawal.id, self.admin)

        # Try to reject - should fail
        with self.assertRaises(services.WithdrawalError) as cm:
            services.reject_withdrawal(withdrawal.id, self.admin, "Changed mind")
        self.assertIn("状态无效", str(cm.exception))
