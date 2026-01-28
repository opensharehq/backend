"""Tests for points models."""

from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from accounts.models import Organization, User
from points.models import (
    PointSource,
    PointTransaction,
    PointType,
    PointWallet,
    Tag,
    TransactionType,
    WithdrawalRequest,
    WithdrawalStatus,
)


class TagModelTests(TestCase):
    """Tests for Tag model."""

    def test_tag_creation(self):
        """Test creating a tag."""
        tag = Tag.objects.create(
            name="活动积分",
            slug="event",
            description="活动奖励积分",
        )
        self.assertEqual(tag.name, "活动积分")
        self.assertEqual(tag.slug, "event")
        self.assertEqual(str(tag), "活动积分")

    def test_tag_slug_unique(self):
        """Test that tag slug must be unique."""
        Tag.objects.create(name="测试", slug="test")
        with self.assertRaises(IntegrityError):
            Tag.objects.create(name="测试2", slug="test")


class PointWalletModelTests(TestCase):
    """Tests for PointWallet model."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.org = Organization.objects.create(name="Test Org", slug="test-org")

    def test_wallet_creation_for_user(self):
        """Test creating wallet for user."""
        ct = ContentType.objects.get_for_model(User)
        wallet = PointWallet.objects.create(content_type=ct, object_id=self.user.pk)

        self.assertEqual(wallet.owner, self.user)
        self.assertIn("testuser", str(wallet))

    def test_wallet_creation_for_organization(self):
        """Test creating wallet for organization."""
        ct = ContentType.objects.get_for_model(Organization)
        wallet = PointWallet.objects.create(content_type=ct, object_id=self.org.pk)

        self.assertEqual(wallet.owner, self.org)
        self.assertIn("Test Org", str(wallet))

    def test_wallet_unique_per_owner(self):
        """Test that each owner can only have one wallet."""
        ct = ContentType.objects.get_for_model(User)
        PointWallet.objects.create(content_type=ct, object_id=self.user.pk)

        with self.assertRaises(IntegrityError):
            PointWallet.objects.create(content_type=ct, object_id=self.user.pk)

    def test_get_cash_balance_empty(self):
        """Test getting cash balance when empty."""
        ct = ContentType.objects.get_for_model(User)
        wallet = PointWallet.objects.create(content_type=ct, object_id=self.user.pk)

        self.assertEqual(wallet.get_cash_balance(), 0)

    def test_get_gift_balance_empty(self):
        """Test getting gift balance when empty."""
        ct = ContentType.objects.get_for_model(User)
        wallet = PointWallet.objects.create(content_type=ct, object_id=self.user.pk)

        self.assertEqual(wallet.get_gift_balance(), 0)

    def test_get_total_balance_empty(self):
        """Test getting total balance when empty."""
        ct = ContentType.objects.get_for_model(User)
        wallet = PointWallet.objects.create(content_type=ct, object_id=self.user.pk)

        self.assertEqual(wallet.get_total_balance(), 0)

    def test_get_cash_balance_with_sources(self):
        """Test getting cash balance with point sources."""
        ct = ContentType.objects.get_for_model(User)
        wallet = PointWallet.objects.create(content_type=ct, object_id=self.user.pk)

        PointSource.objects.create(
            wallet=wallet,
            point_type=PointType.CASH,
            original_amount=100,
            remaining_amount=80,
            reason="Test",
        )
        PointSource.objects.create(
            wallet=wallet,
            point_type=PointType.CASH,
            original_amount=50,
            remaining_amount=50,
            reason="Test 2",
        )

        self.assertEqual(wallet.get_cash_balance(), 130)

    def test_get_gift_balance_with_tag_filter(self):
        """Test getting gift balance filtered by tag."""
        ct = ContentType.objects.get_for_model(User)
        wallet = PointWallet.objects.create(content_type=ct, object_id=self.user.pk)
        tag = Tag.objects.create(name="活动", slug="event")

        PointSource.objects.create(
            wallet=wallet,
            point_type=PointType.GIFT,
            tag=tag,
            original_amount=100,
            remaining_amount=100,
            reason="Event reward",
        )
        PointSource.objects.create(
            wallet=wallet,
            point_type=PointType.GIFT,
            original_amount=50,
            remaining_amount=50,
            reason="General gift",
        )

        self.assertEqual(wallet.get_gift_balance(), 150)
        self.assertEqual(wallet.get_gift_balance(tag_slug="event"), 100)


class PointSourceModelTests(TestCase):
    """Tests for PointSource model."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        ct = ContentType.objects.get_for_model(User)
        self.wallet = PointWallet.objects.create(
            content_type=ct, object_id=self.user.pk
        )

    def test_point_source_creation(self):
        """Test creating a point source."""
        source = PointSource.objects.create(
            wallet=self.wallet,
            point_type=PointType.CASH,
            original_amount=100,
            remaining_amount=100,
            reason="注册奖励",
        )

        self.assertEqual(source.point_type, PointType.CASH)
        self.assertEqual(source.original_amount, 100)
        self.assertEqual(source.remaining_amount, 100)
        self.assertIn("现金积分", str(source))

    def test_point_source_with_tag(self):
        """Test creating a point source with tag."""
        tag = Tag.objects.create(name="活动", slug="event")
        source = PointSource.objects.create(
            wallet=self.wallet,
            point_type=PointType.GIFT,
            tag=tag,
            original_amount=50,
            remaining_amount=50,
            reason="活动奖励",
        )

        self.assertEqual(source.tag, tag)
        self.assertIn("[活动]", str(source))

    def test_point_source_with_expiration(self):
        """Test point source with expiration date."""
        expires = timezone.now() + timezone.timedelta(days=30)
        source = PointSource.objects.create(
            wallet=self.wallet,
            point_type=PointType.GIFT,
            original_amount=100,
            remaining_amount=100,
            reason="限时奖励",
            expires_at=expires,
        )

        self.assertEqual(source.expires_at, expires)


class PointTransactionModelTests(TestCase):
    """Tests for PointTransaction model."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        ct = ContentType.objects.get_for_model(User)
        self.wallet = PointWallet.objects.create(
            content_type=ct, object_id=self.user.pk
        )

    def test_earn_transaction(self):
        """Test creating an earn transaction."""
        txn = PointTransaction.objects.create(
            wallet=self.wallet,
            transaction_type=TransactionType.EARN,
            point_type=PointType.CASH,
            amount=100,
            balance_after=100,
            description="注册奖励",
        )

        self.assertEqual(txn.transaction_type, TransactionType.EARN)
        self.assertEqual(txn.amount, 100)
        self.assertIn("+100", str(txn))

    def test_spend_transaction(self):
        """Test creating a spend transaction."""
        txn = PointTransaction.objects.create(
            wallet=self.wallet,
            transaction_type=TransactionType.SPEND,
            point_type=PointType.GIFT,
            amount=-50,
            balance_after=50,
            description="兑换商品",
        )

        self.assertEqual(txn.transaction_type, TransactionType.SPEND)
        self.assertEqual(txn.amount, -50)
        self.assertIn("-50", str(txn))


class WithdrawalRequestModelTests(TestCase):
    """Tests for WithdrawalRequest model."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        ct = ContentType.objects.get_for_model(User)
        self.wallet = PointWallet.objects.create(
            content_type=ct, object_id=self.user.pk
        )

    def test_withdrawal_request_creation(self):
        """Test creating a withdrawal request."""
        withdrawal = WithdrawalRequest.objects.create(
            wallet=self.wallet,
            amount=100,
            real_name="张三",
            phone="13800138000",
            id_card="11010519491231002X",
            bank_name="中国银行",
            bank_account="6222000000000000000",
        )

        self.assertEqual(withdrawal.amount, 100)
        self.assertEqual(withdrawal.status, WithdrawalStatus.PENDING)
        self.assertEqual(withdrawal.real_name, "张三")
        self.assertIn("100", str(withdrawal))

    def test_withdrawal_request_status_choices(self):
        """Test all status choices work correctly."""
        withdrawal = WithdrawalRequest.objects.create(
            wallet=self.wallet,
            amount=100,
            real_name="张三",
            phone="13800138000",
            id_card="11010519491231002X",
            bank_name="中国银行",
            bank_account="6222000000000000000",
        )

        for status, _label in WithdrawalStatus.choices:
            withdrawal.status = status
            withdrawal.save()
            self.assertEqual(withdrawal.status, status)


class UserPointWalletPropertyTests(TestCase):
    """Tests for User.point_wallet property."""

    def test_user_point_wallet_creates_wallet(self):
        """Test that accessing point_wallet creates wallet if not exists."""
        user = User.objects.create_user(username="testuser", password="testpass")

        # First access should create wallet
        wallet = user.point_wallet
        self.assertIsNotNone(wallet)
        self.assertEqual(wallet.owner, user)

        # Second access should return same wallet
        wallet2 = user.point_wallet
        self.assertEqual(wallet.id, wallet2.id)


class OrganizationPointWalletPropertyTests(TestCase):
    """Tests for Organization.point_wallet property."""

    def test_org_point_wallet_creates_wallet(self):
        """Test that accessing point_wallet creates wallet if not exists."""
        org = Organization.objects.create(name="Test Org", slug="test-org")

        # First access should create wallet
        wallet = org.point_wallet
        self.assertIsNotNone(wallet)
        self.assertEqual(wallet.owner, org)

        # Second access should return same wallet
        wallet2 = org.point_wallet
        self.assertEqual(wallet.id, wallet2.id)
