"""Test cases for shop service layer."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from accounts.models import ShippingAddress
from points import services as points_services
from points.models import PointType, Tag
from shop.models import Redemption, ShopItem
from shop.services import RedemptionError, redeem_item


class RedeemItemServiceTests(TestCase):
    """Test cases for redeem_item service function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )
        # Grant gift points for redemption tests
        points_services.grant_points(self.user, 10000, PointType.GIFT, "Test points")

    def test_redeem_item_success(self):
        """Test successful item redemption."""
        item = ShopItem.objects.create(
            name_zh="Test Item",
            name_en="Test Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )

        result = redeem_item(user=self.user, item_id=item.id)
        redemption = result["redemption"]

        self.assertEqual(redemption.user_profile, self.user)
        self.assertEqual(redemption.item, item)
        self.assertEqual(redemption.points_cost_at_redemption, 100)
        self.assertEqual(redemption.status, Redemption.StatusChoices.COMPLETED)

        # Check stock was reduced
        item.refresh_from_db()
        self.assertEqual(item.stock, 4)

    def test_redeem_item_unlimited_stock(self):
        """Test redeeming item with unlimited stock."""
        item = ShopItem.objects.create(
            name_zh="Unlimited Item",
            name_en="Unlimited Item",
            description_zh="Test",
            cost=100,
            stock=None,
        )

        result = redeem_item(user=self.user, item_id=item.id)
        redemption = result["redemption"]

        self.assertIsNotNone(redemption)
        # Stock should remain None
        item.refresh_from_db()
        self.assertIsNone(item.stock)

    def test_redeem_item_nonexistent(self):
        """Test redeeming non-existent item raises error."""
        with self.assertRaisesMessage(RedemptionError, "商品不存在"):
            redeem_item(user=self.user, item_id=99999)

    def test_redeem_item_inactive(self):
        """Test redeeming inactive item raises error."""
        item = ShopItem.objects.create(
            name_zh="Inactive Item",
            name_en="Inactive Item",
            description_zh="Test",
            cost=100,
            is_active=False,
        )

        with self.assertRaisesMessage(RedemptionError, "该商品已下架"):
            redeem_item(user=self.user, item_id=item.id)

    def test_redeem_item_out_of_stock(self):
        """Test redeeming out of stock item raises error."""
        item = ShopItem.objects.create(
            name_zh="Out of Stock",
            name_en="Out of Stock",
            description_zh="Test",
            cost=100,
            stock=0,
        )

        with self.assertRaisesMessage(RedemptionError, "该商品已售罄"):
            redeem_item(user=self.user, item_id=item.id)

    def test_redeem_item_atomic_transaction(self):
        """Test that redemption is atomic - failures don't change state."""
        # Create item with 0 stock to trigger error
        item = ShopItem.objects.create(
            name_zh="No Stock",
            name_en="No Stock",
            description_zh="Test",
            cost=50,
            stock=0,
        )

        # Try to redeem - should fail
        with self.assertRaises(RedemptionError):
            redeem_item(user=self.user, item_id=item.id)

        # No redemption should be created
        self.assertEqual(Redemption.objects.count(), 0)

    def test_redeem_item_records_cost_at_redemption_time(self):
        """Test that redemption records the item cost at time of redemption."""
        item = ShopItem.objects.create(
            name_zh="Price Test", name_en="Price Test", description_zh="Test", cost=100
        )

        result = redeem_item(user=self.user, item_id=item.id)
        redemption = result["redemption"]

        # Record the cost
        original_cost = redemption.points_cost_at_redemption

        # Change item price
        item.cost = 150
        item.save()

        # Redemption should still show original cost
        redemption.refresh_from_db()
        self.assertEqual(redemption.points_cost_at_redemption, original_cost)
        self.assertEqual(redemption.points_cost_at_redemption, 100)

    def test_redeem_item_concurrent_stock_update(self):
        """Test that stock updates use F() expression to prevent race conditions."""
        item = ShopItem.objects.create(
            name_zh="Stock Test",
            name_en="Stock Test",
            description_zh="Test",
            cost=50,
            stock=10,
        )

        # Redeem item
        redeem_item(user=self.user, item_id=item.id)

        # Get fresh copy from DB
        item_from_db = ShopItem.objects.get(id=item.id)

        self.assertEqual(item_from_db.stock, 9)

    def test_redeem_item_rejects_second_stale_stock_snapshot(self):
        """A stale second stock snapshot should not be able to create another redemption."""
        item = ShopItem.objects.create(
            name_zh="Last Item",
            name_en="Last Item",
            description_zh="Test",
            cost=50,
            stock=1,
        )
        stale_item_1 = ShopItem.objects.get(id=item.id)
        stale_item_2 = ShopItem.objects.get(id=item.id)

        with patch(
            "shop.services.ShopItem.objects.get",
            side_effect=[stale_item_1, stale_item_2],
        ):
            redeem_item(user=self.user, item_id=item.id)
            try:
                redeem_item(user=self.user, item_id=item.id)
            except IntegrityError as exc:
                self.fail(
                    "Expected RedemptionError for stale stock, "
                    f"got {exc.__class__.__name__}"
                )
            except RedemptionError as exc:
                self.assertIn("该商品已售罄", str(exc))
            else:
                self.fail("Expected RedemptionError for stale stock snapshot")

    def test_redemption_error_exception_inheritance(self):
        """Test that RedemptionError is properly defined."""
        # Verify exception can be instantiated
        error = RedemptionError("Test error message")
        self.assertEqual(str(error), "Test error message")
        self.assertTrue(isinstance(error, Exception))

    def test_redeem_item_stock_exactly_one(self):
        """Test redeeming item when stock is exactly 1."""
        item = ShopItem.objects.create(
            name_zh="Last Item",
            name_en="Last Item",
            description_zh="Test",
            cost=50,
            stock=1,
        )

        result = redeem_item(user=self.user, item_id=item.id)
        redemption = result["redemption"]

        self.assertIsNotNone(redemption)

        # Stock should be 0 now
        item.refresh_from_db()
        self.assertEqual(item.stock, 0)

        # Try to redeem again - should fail
        with self.assertRaisesMessage(RedemptionError, "该商品已售罄"):
            redeem_item(user=self.user, item_id=item.id)

    def test_redeem_item_requires_shipping_without_address(self):
        """Test redeeming item that requires shipping without address fails."""
        item = ShopItem.objects.create(
            name_zh="Physical Item",
            name_en="Physical Item",
            description_zh="Test",
            cost=100,
            requires_shipping=True,
        )

        # Should raise error when no shipping address provided
        with self.assertRaisesMessage(RedemptionError, "此商品需要收货地址"):
            redeem_item(user=self.user, item_id=item.id)

    def test_redeem_item_requires_shipping_with_invalid_address(self):
        """Test redeeming with invalid shipping address ID fails."""
        item = ShopItem.objects.create(
            name_zh="Physical Item",
            name_en="Physical Item",
            description_zh="Test",
            cost=100,
            requires_shipping=True,
        )

        # Should raise error with invalid address ID
        with self.assertRaisesMessage(RedemptionError, "无效的收货地址"):
            redeem_item(
                user=self.user,
                item_id=item.id,
                shipping_address_id=99999,
            )

    def test_redeem_item_requires_shipping_with_other_user_address(self):
        """Test redeeming with another user's address fails."""
        # Create another user with an address
        other_user = get_user_model().objects.create_user(
            username="otheruser",
            email="other@example.com",
            password="password123",
        )
        other_address = ShippingAddress.objects.create(
            user=other_user,
            receiver_name="李四",
            phone="13900139000",
            province="上海",
            city="上海市",
            district="浦东新区",
            address="地址1",
            is_default=True,
        )

        item = ShopItem.objects.create(
            name_zh="Physical Item",
            name_en="Physical Item",
            description_zh="Test",
            cost=100,
            requires_shipping=True,
        )

        # Should raise error when using other user's address
        with self.assertRaisesMessage(RedemptionError, "无效的收货地址"):
            redeem_item(
                user=self.user,
                item_id=item.id,
                shipping_address_id=other_address.id,
            )

    @patch("shop.services.points_services.get_balance")
    @patch("shop.services.points_services.spend_points")
    def test_allowed_tags_selects_sufficient_tag(
        self, mock_spend_points, mock_get_balance
    ):
        """User can specify a tag with enough balance to redeem a tagged item."""
        tag_b = Tag.objects.create(name="Tag B", slug="tag-b")

        item = ShopItem.objects.create(
            name_zh="Tagged Item",
            name_en="Tagged Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )
        item.allowed_tags.set([tag_b])

        mock_get_balance.return_value = 200

        result = redeem_item(
            user=self.user,
            item_id=item.id,
            point_type="gift",
            tag_slug="tag-b",
        )
        redemption = result["redemption"]

        self.assertIsNotNone(redemption)
        self.assertIsInstance(redemption, Redemption)
        mock_spend_points.assert_called_once()
        _, kwargs = mock_spend_points.call_args
        self.assertEqual(kwargs["tag_slug"], tag_b.slug)
        item.refresh_from_db()
        self.assertEqual(item.stock, 4)

    @patch("shop.services.points_services.get_balance", return_value=0)
    def test_allowed_tags_insufficient_balance(self, _mock_get_balance):
        """Fail if the specified allowed tag lacks enough balance."""
        tag_a = Tag.objects.create(name="Tag A", slug="tag-a")

        item = ShopItem.objects.create(
            name_zh="Tagged Item",
            name_en="Tagged Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )
        item.allowed_tags.set([tag_a])

        with self.assertRaisesMessage(RedemptionError, "积分不足"):
            redeem_item(
                user=self.user,
                item_id=item.id,
                point_type="gift",
                tag_slug="tag-a",
            )

        self.assertEqual(Redemption.objects.count(), 0)
        item.refresh_from_db()
        self.assertEqual(item.stock, 5)

    @patch("shop.services.points_services.get_balance")
    @patch("shop.services.points_services.spend_points")
    def test_allowed_tags_prefers_first_sufficient_tag(
        self, mock_spend_points, mock_get_balance
    ):
        """User can specify which tag to use for redemption."""
        tag_a = Tag.objects.create(name="Alpha Tag", slug="alpha-tag")
        tag_b = Tag.objects.create(name="Beta Tag", slug="beta-tag")

        item = ShopItem.objects.create(
            name_zh="Priority Item",
            name_en="Priority Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )
        item.allowed_tags.set([tag_a, tag_b])
        mock_get_balance.return_value = 200

        # User explicitly picks tag_a
        redeem_item(
            user=self.user,
            item_id=item.id,
            point_type="gift",
            tag_slug="alpha-tag",
        )

        _, kwargs = mock_spend_points.call_args
        self.assertEqual(kwargs["tag_slug"], "alpha-tag")

    @patch("shop.services.points_services.get_balance")
    def test_allowed_tags_do_not_combine_partial_balances(self, mock_get_balance):
        """An insufficient tag bucket should not be combined with another."""
        tag_a = Tag.objects.create(name="Partial A", slug="partial-a")

        item = ShopItem.objects.create(
            name_zh="Split Balance Item",
            name_en="Split Balance Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )
        item.allowed_tags.set([tag_a])
        mock_get_balance.return_value = 60

        with self.assertRaisesMessage(RedemptionError, "积分不足"):
            redeem_item(
                user=self.user,
                item_id=item.id,
                point_type="gift",
                tag_slug="partial-a",
            )

        self.assertEqual(Redemption.objects.count(), 0)

    @patch("shop.services.points_services.spend_points")
    def test_spend_points_insufficient_points_wrapped(self, mock_spend_points):
        """Wrap spend_points errors in RedemptionError while keeping state unchanged."""
        mock_spend_points.side_effect = points_services.InsufficientPointsError("不足")
        item = ShopItem.objects.create(
            name_zh="Expensive Tag",
            name_en="Expensive Tag",
            description_zh="Test",
            cost=500,
            stock=10,
        )

        with self.assertRaisesMessage(RedemptionError, "积分不足"):
            redeem_item(user=self.user, item_id=item.id)

        self.assertEqual(Redemption.objects.count(), 0)
        item.refresh_from_db()
        self.assertEqual(item.stock, 10)

    def test_redeem_item_rolls_back_when_redemption_creation_fails(self):
        """Late failures while creating the redemption should restore points and stock."""
        item = ShopItem.objects.create(
            name_zh="Creation Failure",
            name_en="Creation Failure",
            description_zh="Test",
            cost=120,
            stock=3,
        )
        initial_balance = points_services.get_balance(self.user, PointType.GIFT)

        with patch(
            "shop.services.Redemption.objects.create",
            side_effect=RuntimeError("create failed"),
        ):
            with self.assertRaises(RuntimeError):
                redeem_item(user=self.user, item_id=item.id)

        self.assertEqual(Redemption.objects.count(), 0)
        self.assertEqual(
            points_services.get_balance(self.user, PointType.GIFT),
            initial_balance,
        )
        item.refresh_from_db()
        self.assertEqual(item.stock, 3)

    def test_redeem_item_rolls_back_when_stock_update_fails(self):
        """Stock persistence failures should roll back the spent points and redemption row."""
        item = ShopItem.objects.create(
            name_zh="Save Failure",
            name_en="Save Failure",
            description_zh="Test",
            cost=150,
            stock=4,
        )
        initial_balance = points_services.get_balance(self.user, PointType.GIFT)

        with patch(
            "django.db.models.query.QuerySet.update",
            side_effect=RuntimeError("save failed"),
        ):
            with self.assertRaises(RuntimeError):
                redeem_item(user=self.user, item_id=item.id)

        self.assertEqual(Redemption.objects.count(), 0)
        self.assertEqual(
            points_services.get_balance(self.user, PointType.GIFT),
            initial_balance,
        )
        item.refresh_from_db()
        self.assertEqual(item.stock, 4)

    def test_redeem_item_requires_shipping_success(self):
        """Test successful redemption of item requiring shipping."""
        # Create shipping address
        address = ShippingAddress.objects.create(
            user=self.user,
            receiver_name="张三",
            phone="13800138000",
            province="北京",
            city="北京市",
            district="朝阳区",
            address="某某街道123号",
            is_default=True,
        )

        item = ShopItem.objects.create(
            name_zh="Physical Item",
            name_en="Physical Item",
            description_zh="Test",
            cost=100,
            requires_shipping=True,
        )

        # Should succeed with valid address
        result = redeem_item(
            user=self.user,
            item_id=item.id,
            shipping_address_id=address.id,
        )
        redemption = result["redemption"]

        self.assertIsNotNone(redemption)
        self.assertEqual(redemption.shipping_address, address)

    def test_redeem_item_not_requiring_shipping(self):
        """Test redeeming virtual item without shipping address."""
        item = ShopItem.objects.create(
            name_zh="Virtual Item",
            name_en="Virtual Item",
            description_zh="Test",
            cost=100,
            requires_shipping=False,
        )

        # Should succeed without shipping address
        result = redeem_item(user=self.user, item_id=item.id)
        redemption = result["redemption"]

        self.assertIsNotNone(redemption)
        self.assertIsNone(redemption.shipping_address)

    def test_redeem_item_insufficient_points(self):
        """Test redeeming item when user has insufficient points."""
        # Create a new user without any points
        poor_user = get_user_model().objects.create_user(
            username="pooruser", email="poor@example.com", password="password123"
        )
        item = ShopItem.objects.create(
            name_zh="Expensive Item",
            name_en="Expensive Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )

        with self.assertRaisesMessage(RedemptionError, "积分不足"):
            redeem_item(user=poor_user, item_id=item.id)

    # ==================== Cash 支付测试 ====================

    def test_redeem_with_cash_success(self):
        """User can redeem an item with cash points."""
        points_services.grant_points(
            self.user,
            500,
            PointType.CASH,
            "Cash test points",
        )
        item = ShopItem.objects.create(
            name_zh="Cash Item",
            name_en="Cash Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )

        result = redeem_item(user=self.user, item_id=item.id, point_type="cash")
        redemption = result["redemption"]

        self.assertEqual(redemption.point_type, PointType.CASH)
        self.assertIsNone(redemption.point_tag_slug)
        item.refresh_from_db()
        self.assertEqual(item.stock, 4)

    def test_redeem_with_cash_insufficient(self):
        """Cash redemption fails when cash balance is insufficient."""
        # Only grant gift points, no cash
        item = ShopItem.objects.create(
            name_zh="Cash Item",
            name_en="Cash Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )

        with self.assertRaisesMessage(RedemptionError, "积分不足"):
            redeem_item(user=self.user, item_id=item.id, point_type="cash")

        self.assertEqual(Redemption.objects.count(), 0)
        item.refresh_from_db()
        self.assertEqual(item.stock, 5)

    def test_redeem_with_cash_on_tagged_item(self):
        """Cash can redeem tagged items without tag restriction."""
        points_services.grant_points(
            self.user,
            500,
            PointType.CASH,
            "Cash test points",
        )
        tag = Tag.objects.create(name="Tag X", slug="tag-x")
        item = ShopItem.objects.create(
            name_zh="Tagged Item",
            name_en="Tagged Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )
        item.allowed_tags.set([tag])

        result = redeem_item(user=self.user, item_id=item.id, point_type="cash")
        redemption = result["redemption"]

        self.assertEqual(redemption.point_type, PointType.CASH)
        self.assertIsNone(redemption.point_tag_slug)

    def test_redeem_with_cash_rollback_on_failure(self):
        """Cash redemption rolls back when downstream fails."""
        points_services.grant_points(
            self.user,
            500,
            PointType.CASH,
            "Cash test points",
        )
        item = ShopItem.objects.create(
            name_zh="Cash Rollback",
            name_en="Cash Rollback",
            description_zh="Test",
            cost=100,
            stock=5,
        )
        initial_cash = points_services.get_balance(self.user, PointType.CASH)

        with patch(
            "shop.services.Redemption.objects.create",
            side_effect=RuntimeError("create failed"),
        ):
            with self.assertRaises(RuntimeError):
                redeem_item(user=self.user, item_id=item.id, point_type="cash")

        self.assertEqual(Redemption.objects.count(), 0)
        self.assertEqual(
            points_services.get_balance(self.user, PointType.CASH),
            initial_cash,
        )
        item.refresh_from_db()
        self.assertEqual(item.stock, 5)

    # ==================== Gift + 标签支付测试 ====================

    def test_redeem_with_tagged_gift_success(self):
        """User can redeem with a specific tagged gift points."""
        tag = Tag.objects.create(name="Tag A", slug="tag-a")
        points_services.grant_points(
            self.user,
            500,
            PointType.GIFT,
            "Tagged gift",
            tag_slug="tag-a",
        )
        item = ShopItem.objects.create(
            name_zh="Tagged Item",
            name_en="Tagged Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )
        item.allowed_tags.set([tag])

        result = redeem_item(
            user=self.user,
            item_id=item.id,
            point_type="gift",
            tag_slug="tag-a",
        )
        redemption = result["redemption"]

        self.assertEqual(redemption.point_type, PointType.GIFT)
        self.assertEqual(redemption.point_tag_slug, "tag-a")
        item.refresh_from_db()
        self.assertEqual(item.stock, 4)

    def test_redeem_with_tagged_gift_wrong_tag(self):
        """Tagged gift with tag not in allowed_tags fails."""
        tag_a = Tag.objects.create(name="Tag A", slug="tag-a")
        Tag.objects.create(name="Tag B", slug="tag-b")
        points_services.grant_points(
            self.user,
            500,
            PointType.GIFT,
            "Tag B gift",
            tag_slug="tag-b",
        )
        item = ShopItem.objects.create(
            name_zh="Tagged Item",
            name_en="Tagged Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )
        item.allowed_tags.set([tag_a])

        with self.assertRaisesMessage(
            RedemptionError, "您没有足够的符合条件的积分来兑换此商品"
        ):
            redeem_item(
                user=self.user,
                item_id=item.id,
                point_type="gift",
                tag_slug="tag-b",
            )

        self.assertEqual(Redemption.objects.count(), 0)
        item.refresh_from_db()
        self.assertEqual(item.stock, 5)

    def test_redeem_with_tagged_gift_insufficient(self):
        """Tagged gift with insufficient balance fails."""
        tag = Tag.objects.create(name="Tag A", slug="tag-a")
        points_services.grant_points(
            self.user,
            50,
            PointType.GIFT,
            "Small gift",
            tag_slug="tag-a",
        )
        item = ShopItem.objects.create(
            name_zh="Expensive Tagged Item",
            name_en="Expensive Tagged Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )
        item.allowed_tags.set([tag])

        with self.assertRaisesMessage(RedemptionError, "积分不足"):
            redeem_item(
                user=self.user,
                item_id=item.id,
                point_type="gift",
                tag_slug="tag-a",
            )

        self.assertEqual(Redemption.objects.count(), 0)

    def test_redeem_with_tagged_gift_on_tagless_item(self):
        """Tagged gift on item without allowed_tags fails."""
        Tag.objects.create(name="Tag A", slug="tag-a")
        points_services.grant_points(
            self.user,
            500,
            PointType.GIFT,
            "Tagged gift",
            tag_slug="tag-a",
        )
        item = ShopItem.objects.create(
            name_zh="No Tag Item",
            name_en="No Tag Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )
        # Item has no allowed_tags

        with self.assertRaisesMessage(
            RedemptionError, "您没有足够的符合条件的积分来兑换此商品"
        ):
            redeem_item(
                user=self.user,
                item_id=item.id,
                point_type="gift",
                tag_slug="tag-a",
            )

        self.assertEqual(Redemption.objects.count(), 0)

    # ==================== Gift + 无标签支付测试 ====================

    def test_redeem_with_untagged_gift_success(self):
        """User can redeem with universal gift points (no tag)."""
        item = ShopItem.objects.create(
            name_zh="Untagged Gift Item",
            name_en="Untagged Gift Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )

        result = redeem_item(user=self.user, item_id=item.id, point_type="gift")
        redemption = result["redemption"]

        self.assertEqual(redemption.point_type, PointType.GIFT)
        self.assertIsNone(redemption.point_tag_slug)
        item.refresh_from_db()
        self.assertEqual(item.stock, 4)

    def test_redeem_with_untagged_gift_insufficient(self):
        """Universal gift redemption fails when balance insufficient."""
        poor_user = get_user_model().objects.create_user(
            username="pooruser2", email="poor2@example.com", password="password123"
        )
        item = ShopItem.objects.create(
            name_zh="Expensive Item",
            name_en="Expensive Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )

        with self.assertRaisesMessage(RedemptionError, "积分不足"):
            redeem_item(user=poor_user, item_id=item.id, point_type="gift")

        self.assertEqual(Redemption.objects.count(), 0)

    def test_redeem_without_tag_does_not_spend_tagged_balance(self):
        """Untagged redemption must fail and never drain tagged gift pools."""
        tagged_user = get_user_model().objects.create_user(
            username="taggedonly",
            email="taggedonly@example.com",
            password="password123",
        )
        tag = Tag.objects.create(name="Tag A", slug="tag-a")
        points_services.grant_points(
            tagged_user,
            500,
            PointType.GIFT,
            "Tagged gift only",
            tag_slug=tag.slug,
        )
        item = ShopItem.objects.create(
            name_zh="Tagged-Only Item",
            name_en="Tagged-Only Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )
        item.allowed_tags.set([tag])

        # No tag_slug selected: tagged pools must not be spendable implicitly
        with self.assertRaisesMessage(RedemptionError, "此商品需要使用指定标签的积分兑换"):
            redeem_item(user=tagged_user, item_id=item.id, point_type="gift")

        self.assertEqual(Redemption.objects.count(), 0)
        self.assertEqual(
            points_services.get_balance(tagged_user, PointType.GIFT, tag_slug=tag.slug),
            500,
        )

    def test_redeem_without_tag_keeps_tagged_balance_intact(self):
        """Untagged redemption must fail when item has allowed_tags, leaving tagged pool intact."""
        tag = Tag.objects.create(name="Tag B", slug="tag-b")
        points_services.grant_points(
            self.user,
            500,
            PointType.GIFT,
            "Tagged gift",
            tag_slug=tag.slug,
        )
        item = ShopItem.objects.create(
            name_zh="Mixed Pool Item",
            name_en="Mixed Pool Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )
        item.allowed_tags.set([tag])

        with self.assertRaisesMessage(RedemptionError, "此商品需要使用指定标签的积分兑换"):
            redeem_item(user=self.user, item_id=item.id, point_type="gift")

        self.assertEqual(Redemption.objects.count(), 0)
        # Tagged pool must remain untouched
        self.assertEqual(
            points_services.get_balance(self.user, PointType.GIFT, tag_slug=tag.slug),
            500,
        )

    def test_redeem_with_empty_tag_slug_does_not_spend_tagged_balance(self):
        """Empty-string tag_slug must behave like no tag and never drain tagged pool."""
        tagged_user = get_user_model().objects.create_user(
            username="taggedempty",
            email="taggedempty@example.com",
            password="password123",
        )
        tag = Tag.objects.create(name="Tag C", slug="tag-c")
        points_services.grant_points(
            tagged_user,
            500,
            PointType.GIFT,
            "Tagged gift only",
            tag_slug=tag.slug,
        )
        item = ShopItem.objects.create(
            name_zh="Tagged-Only Item",
            name_en="Tagged-Only Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )
        item.allowed_tags.set([tag])

        with self.assertRaisesMessage(RedemptionError, "此商品需要使用指定标签的积分兑换"):
            redeem_item(
                user=tagged_user, item_id=item.id, point_type="gift", tag_slug=""
            )

        self.assertEqual(Redemption.objects.count(), 0)
        self.assertEqual(
            points_services.get_balance(tagged_user, PointType.GIFT, tag_slug=tag.slug),
            500,
        )

    def test_redeem_with_empty_tag_slug_equals_no_tag(self):
        """Empty-string tag_slug must fail when item has allowed_tags, like tag_slug=None."""
        tag = Tag.objects.create(name="Tag D", slug="tag-d")
        points_services.grant_points(
            self.user,
            500,
            PointType.GIFT,
            "Tagged gift",
            tag_slug=tag.slug,
        )
        item = ShopItem.objects.create(
            name_zh="Empty Slug Item",
            name_en="Empty Slug Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )
        item.allowed_tags.set([tag])

        with self.assertRaisesMessage(RedemptionError, "此商品需要使用指定标签的积分兑换"):
            redeem_item(
                user=self.user, item_id=item.id, point_type="gift", tag_slug=""
            )

        self.assertEqual(Redemption.objects.count(), 0)
        # Tagged pool must remain untouched
        self.assertEqual(
            points_services.get_balance(self.user, PointType.GIFT, tag_slug=tag.slug),
            500,
        )

    # ==================== 参数校验 ====================

    def test_redeem_invalid_point_type(self):
        """Invalid point_type raises error."""
        item = ShopItem.objects.create(
            name_zh="Test Item",
            name_en="Test Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )

        with self.assertRaisesMessage(RedemptionError, "无效的积分类型"):
            redeem_item(user=self.user, item_id=item.id, point_type="invalid")

        self.assertEqual(Redemption.objects.count(), 0)

    def test_redeem_cash_with_tag_fails(self):
        """Cash point_type with tag_slug raises error."""
        item = ShopItem.objects.create(
            name_zh="Test Item",
            name_en="Test Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )

        with self.assertRaisesMessage(RedemptionError, "只有礼物积分可以设置标签"):
            redeem_item(
                user=self.user,
                item_id=item.id,
                point_type="cash",
                tag_slug="some-tag",
            )

        self.assertEqual(Redemption.objects.count(), 0)
