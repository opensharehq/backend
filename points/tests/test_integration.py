"""Integration tests for points app workflows."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from points.models import PointTransaction, Tag
from points.services import InsufficientPointsError, grant_points, spend_points


@pytest.mark.integration
class PointsGrantingFlowTests(TestCase):
    """Test complete points granting workflow."""

    def setUp(self):
        """Set up test fixtures."""
        User = get_user_model()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.tag = Tag.objects.create(name="sign-up-bonus", description="注册奖励")

    def test_grant_points_creates_source_and_transaction(self):
        """Test granting points creates both source and transaction."""
        # Grant points to user
        source = grant_points(
            user_profile=self.user,
            points=100,
            tag_names=[self.tag.name],
            description="用户注册奖励",
        )

        # Verify PointSource was created
        assert source.user_profile == self.user
        assert source.initial_points == 100
        assert source.remaining_points == 100
        assert self.tag in source.tags.all()

        # Verify PointTransaction was created
        transaction = PointTransaction.objects.filter(
            user_profile=self.user, transaction_type="EARN"
        ).first()
        assert transaction is not None
        assert transaction.points == 100
        assert transaction.description == "用户注册奖励"

        # Verify user's total points
        assert self.user.total_points == 100

    def test_grant_multiple_points_from_different_sources(self):
        """Test user can receive points from multiple sources."""
        tag1 = Tag.objects.create(name="welcome", description="欢迎奖励")
        tag2 = Tag.objects.create(name="referral", description="推荐奖励")

        # Grant welcome bonus
        grant_points(
            user_profile=self.user,
            points=50,
            tag_names=[tag1.name],
            description="欢迎奖励",
        )

        # Grant referral bonus
        grant_points(
            user_profile=self.user,
            points=30,
            tag_names=[tag2.name],
            description="推荐好友奖励",
        )

        # Verify total points
        assert self.user.total_points == 80

        # Verify two sources exist
        assert self.user.point_sources.count() == 2

        # Verify transactions
        assert PointTransaction.objects.filter(user_profile=self.user).count() == 2


@pytest.mark.integration
class PointsSpendingFlowTests(TestCase):
    """Test complete points spending workflow."""

    def setUp(self):
        """Set up test fixtures."""
        User = get_user_model()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.tag = Tag.objects.create(
            name="general", description="通用积分", is_default=True
        )

        # Grant initial points
        grant_points(
            user_profile=self.user,
            points=200,
            tag_names=[self.tag.name],
            description="初始积分",
        )

    def test_spend_points_with_fifo_consumption(self):
        """Test spending points uses FIFO (oldest first) consumption."""
        # Create multiple point sources
        tag = Tag.objects.create(name="test", description="测试", is_default=True)

        # First source: 100 points
        grant_points(
            user_profile=self.user,
            points=100,
            tag_names=[tag.name],
            description="第一笔",
        )

        # Second source: 50 points
        grant_points(
            user_profile=self.user,
            points=50,
            tag_names=[tag.name],
            description="第二笔",
        )

        # User should have 350 total (200 from setUp + 100 + 50)
        assert self.user.total_points == 350

        # Spend 120 points (should consume from oldest first)
        transaction = spend_points(
            user_profile=self.user,
            amount=120,
            description="测试消费",
        )

        # Verify transaction was created
        assert transaction is not None

        # Verify remaining points: 350 - 120 = 230
        assert self.user.total_points == 230

        # Verify FIFO consumption - oldest source should be consumed first
        sources = self.user.point_sources.order_by("created_at")
        # The setUp creates 200 points (oldest)
        # Then we grant 100 more
        # Then we grant 50 more
        # Spend 120: takes from oldest (setUp source)
        # setUp source: 200 - 120 = 80 remaining

        oldest_source = sources.first()
        assert oldest_source.remaining_points == 80

    def test_spend_points_with_insufficient_balance_raises_error(self):
        """Test spending more points than available raises error."""
        # User has 200 points from setUp
        with pytest.raises(InsufficientPointsError) as exc_info:
            spend_points(
                user_profile=self.user,
                amount=300,  # More than available
                description="尝试超支",
            )

        assert (
            "积分不足" in str(exc_info.value)
            or "Insufficient" in str(exc_info.value).lower()
        )

        # Points should remain unchanged
        assert self.user.total_points == 200

    def test_spend_points_with_tag_filter(self):
        """Test spending points with priority tag."""
        # Create different types of points
        event_tag = Tag.objects.create(name="event", description="活动积分")
        Tag.objects.create(name="general2", description="通用积分2", is_default=True)

        # Grant event-specific points
        grant_points(
            user_profile=self.user,
            points=50,
            tag_names=[event_tag.name],
            description="活动奖励",
        )

        # User now has 200 (general from setUp) + 50 (event) = 250 total
        assert self.user.total_points == 250

        # Spend with priority on event tag
        # This will consume 50 from event tag first, then 50 from default tag
        transaction = spend_points(
            user_profile=self.user,
            amount=100,
            description="活动兑换",
            priority_tag_name=event_tag.name,
        )

        assert transaction is not None
        # Total should be 150 (250 - 100)
        assert self.user.total_points == 150

        # Verify event points are fully consumed
        event_sources = self.user.point_sources.filter(tags__name=event_tag.name)
        total_event_points = sum(s.remaining_points for s in event_sources)
        assert total_event_points == 0


@pytest.mark.integration
class PointsViewFlowTests(TestCase):
    """Test points viewing workflow through web interface."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(self.user)

    def test_view_points_page_with_transactions(self):
        """Test user can view their points and transaction history."""
        # Grant some points
        tag = Tag.objects.create(
            name="welcome", description="欢迎积分", is_default=True
        )
        grant_points(
            user_profile=self.user,
            points=100,
            tag_names=[tag.name],
            description="欢迎奖励",
        )

        # Spend some points
        spend_points(
            user_profile=self.user,
            amount=30,
            description="兑换商品",
        )

        # Access my points page
        my_points_url = reverse("points:my_points")
        response = self.client.get(my_points_url)

        assert response.status_code == 200
        content = response.content.decode()

        # Should show current balance (100 - 30 = 70)
        assert "70" in content

        # Should show transaction history
        assert "欢迎奖励" in content
        assert "兑换商品" in content

    def test_unauthorized_access_to_points_page_redirects(self):
        """Test non-logged-in user cannot access points page."""
        self.client.logout()

        my_points_url = reverse("points:my_points")
        response = self.client.get(my_points_url)

        # Should redirect to login
        assert response.status_code == 302
        assert "sign_in" in response.url or "login" in response.url


@pytest.mark.integration
class PointsManagementCommandFlowTests(TestCase):
    """Test points management command workflow."""

    def test_grant_points_via_management_command(self):
        """Test granting points through management command."""
        from io import StringIO

        from django.core.management import call_command

        # Create user and tag
        User = get_user_model()
        user = User.objects.create_user(
            username="cmduser",
            email="cmd@example.com",
            password="testpass123",
        )
        Tag.objects.create(name="admin-grant", description="管理员发放")

        # Call management command
        out = StringIO()
        call_command(
            "grant_points",
            "cmduser",
            500,
            description="管理员手动发放",
            tags="admin-grant",
            stdout=out,
        )

        # Verify points were granted
        user.refresh_from_db()
        assert user.total_points == 500

        # Verify output message
        output = out.getvalue()
        assert "成功" in output or "Successfully" in output

    def test_grant_points_to_nonexistent_user_shows_error(self):
        """Test granting points to non-existent user shows error."""
        from io import StringIO

        from django.core.management import call_command
        from django.core.management.base import CommandError

        Tag.objects.create(name="test", description="测试")

        out = StringIO()

        # Should raise error for non-existent user
        with pytest.raises(CommandError) as exc_info:
            call_command(
                "grant_points",
                "nonexistentuser",
                100,
                description="测试",
                tags="test",
                stdout=out,
            )

        assert (
            "不存在" in str(exc_info.value).lower()
            or "not found" in str(exc_info.value).lower()
        )
