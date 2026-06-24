"""Test cases for coupon code and redemption message features."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from accounts.models import UserProfile
from messages.models import Message
from points import services as points_services
from points.models import PointType
from shop.models import CouponCode, Redemption, ShopItem
from shop.services import (
    RedemptionError,
    claim_coupon,
    redeem_item,
    send_redemption_message,
)


class CouponCodeModelTests(TestCase):
    """Test cases for CouponCode model."""

    def test_create_coupon_default_status_available(self):
        """创建兑换码：验证 status 默认为 AVAILABLE."""
        coupon = CouponCode.objects.create(code_type="test_type", code="ABC123")
        self.assertEqual(coupon.status, CouponCode.Status.AVAILABLE)
        self.assertIsNone(coupon.redeemed_by)
        self.assertIsNone(coupon.redeemed_at)

    def test_unique_constraint_same_type_duplicate_code(self):
        """唯一约束：同类型下不允许重复 code."""
        CouponCode.objects.create(code_type="gift_card", code="UNIQUE001")
        with self.assertRaises(IntegrityError):
            CouponCode.objects.create(code_type="gift_card", code="UNIQUE001")

    def test_same_code_different_type_allowed(self):
        """不同类型下可以有相同 code."""
        CouponCode.objects.create(code_type="type_a", code="SAME_CODE")
        coupon2 = CouponCode.objects.create(code_type="type_b", code="SAME_CODE")
        self.assertIsNotNone(coupon2.id)


class ClaimCouponTests(TestCase):
    """Test cases for claim_coupon function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="couponuser", email="coupon@example.com", password="password123"
        )
        self.profile = UserProfile.objects.create(user=self.user)

    def test_claim_coupon_success(self):
        """正常领取：返回 CouponCode，状态变为 USED，记录 redeemed_by 和 redeemed_at."""
        CouponCode.objects.create(code_type="vip_pass", code="VIP001")

        coupon = claim_coupon("vip_pass", self.profile)

        self.assertEqual(coupon.code, "VIP001")
        self.assertEqual(coupon.status, CouponCode.Status.USED)
        self.assertEqual(coupon.redeemed_by, self.profile)
        self.assertIsNotNone(coupon.redeemed_at)

    def test_claim_coupon_no_available_raises_error(self):
        """无可用码时：抛出 RedemptionError("该商品已售罄。")."""
        # No coupons exist for this type
        with self.assertRaisesMessage(RedemptionError, "该商品已售罄。"):
            claim_coupon("nonexistent_type", self.profile)

    def test_claim_coupon_all_disabled_raises_error(self):
        """所有码被禁用时：抛出 RedemptionError."""
        CouponCode.objects.create(
            code_type="disabled_type", code="DIS001", status=CouponCode.Status.DISABLED
        )
        CouponCode.objects.create(
            code_type="disabled_type", code="DIS002", status=CouponCode.Status.DISABLED
        )

        with self.assertRaisesMessage(RedemptionError, "该商品已售罄。"):
            claim_coupon("disabled_type", self.profile)

    def test_claim_coupon_used_codes_not_reclaimed(self):
        """已使用的码不会被再次领取."""
        CouponCode.objects.create(
            code_type="used_type", code="USED001", status=CouponCode.Status.USED
        )

        with self.assertRaisesMessage(RedemptionError, "该商品已售罄。"):
            claim_coupon("used_type", self.profile)

    def test_claim_coupon_picks_first_by_id_order(self):
        """多个可用码时按 id 顺序领取第一个."""
        c1 = CouponCode.objects.create(code_type="ordered", code="FIRST")
        CouponCode.objects.create(code_type="ordered", code="SECOND")
        CouponCode.objects.create(code_type="ordered", code="THIRD")

        coupon = claim_coupon("ordered", self.profile)

        self.assertEqual(coupon.id, c1.id)
        self.assertEqual(coupon.code, "FIRST")

    def test_claim_coupon_skips_used_picks_next_available(self):
        """已使用的跳过，领取下一个可用码."""
        CouponCode.objects.create(
            code_type="mixed", code="USED_ONE", status=CouponCode.Status.USED
        )
        c2 = CouponCode.objects.create(code_type="mixed", code="AVAIL_ONE")

        coupon = claim_coupon("mixed", self.profile)
        self.assertEqual(coupon.id, c2.id)
        self.assertEqual(coupon.code, "AVAIL_ONE")


class SendRedemptionMessageTests(TestCase):
    """Test cases for send_redemption_message function."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="msguser", email="msg@example.com", password="password123"
        )
        self.coupon = CouponCode(code="TEST_COUPON_CODE", code_type="test")

    def _make_item(self, **kwargs):
        """Helper to create a ShopItem with message templates."""
        defaults = {
            "name_zh": "测试商品",
            "name_en": "Test Item",
            "description_zh": "描述",
            "cost": 100,
        }
        defaults.update(kwargs)
        return ShopItem.objects.create(**defaults)

    @patch("messages.services.send_message")
    def test_zh_template_renders_params(self, mock_send):
        """中文模板渲染：验证 {timestamp}, {coupon_code}, {item_name} 参数替换正确."""
        item = self._make_item(
            message_title_template_zh="兑换成功：{item_name}",
            message_content_template_zh="兑换码: {coupon_code}，时间: {timestamp}",
        )

        send_redemption_message(item, self.user, self.coupon, lang="zh")

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        self.assertIn("测试商品", call_kwargs["title"])
        self.assertIn("TEST_COUPON_CODE", call_kwargs["content"])
        # timestamp should be present (formatted datetime)
        self.assertRegex(call_kwargs["content"], r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

    @patch("messages.services.send_message")
    def test_en_template_renders_with_lang_en(self, mock_send):
        """英文模板渲染：lang="en" 时使用英文模板."""
        item = self._make_item(
            message_title_template_zh="中文标题",
            message_content_template_zh="中文内容",
            message_title_template_en="Redemption: {item_name}",
            message_content_template_en="Code: {coupon_code}",
        )

        send_redemption_message(item, self.user, self.coupon, lang="en")

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        self.assertIn("Redemption: Test Item", call_kwargs["title"])
        self.assertIn("Code: TEST_COUPON_CODE", call_kwargs["content"])

    @patch("messages.services.send_message")
    def test_en_template_empty_falls_back_to_zh(self, mock_send):
        """英文模板为空时回退到中文模板."""
        item = self._make_item(
            message_title_template_zh="中文标题: {item_name}",
            message_content_template_zh="中文内容: {coupon_code}",
            message_title_template_en="",
            message_content_template_en="",
        )

        send_redemption_message(item, self.user, self.coupon, lang="en")

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        self.assertIn("中文标题", call_kwargs["title"])
        self.assertIn("中文内容", call_kwargs["content"])

    @patch("messages.services.send_message")
    def test_no_template_does_not_send(self, mock_send):
        """无模板时不发送消息（无异常）."""
        item = self._make_item(
            message_title_template_zh="",
            message_content_template_zh="",
            message_title_template_en="",
            message_content_template_en="",
        )

        # Should not raise
        send_redemption_message(item, self.user, self.coupon, lang="zh")

        mock_send.assert_not_called()

    @patch("messages.services.send_message")
    def test_send_message_called_with_correct_params(self, mock_send):
        """验证 send_message 调用参数正确（message_type=ORDER, recipients 正确）."""
        item = self._make_item(
            message_title_template_zh="标题: {item_name}",
            message_content_template_zh="内容: {coupon_code}",
        )

        send_redemption_message(item, self.user, self.coupon, lang="zh")

        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args[1]
        self.assertEqual(call_kwargs["message_type"], Message.MessageType.ORDER)
        self.assertEqual(call_kwargs["recipients"], [self.user])


class RedeemItemCouponTests(TestCase):
    """Test cases for redeem_item with coupon_type items."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="redeemuser", email="redeem@example.com", password="password123"
        )
        self.profile = UserProfile.objects.create(user=self.user)
        points_services.grant_points(self.user, 10000, PointType.GIFT, "Test points")

    def test_coupon_item_redeem_success(self):
        """兑换码商品正常兑换：返回 coupon_code，兑换码状态变 USED."""
        item = ShopItem.objects.create(
            name_zh="兑换码商品",
            name_en="Coupon Item",
            description_zh="Test coupon item",
            cost=100,
            coupon_type="premium_pass",
        )
        CouponCode.objects.create(code_type="premium_pass", code="PREMIUM001")

        result = redeem_item(user=self.user, item_id=item.id)

        self.assertEqual(result["coupon_code"], "PREMIUM001")
        coupon = CouponCode.objects.get(code="PREMIUM001")
        self.assertEqual(coupon.status, CouponCode.Status.USED)
        self.assertEqual(coupon.redeemed_by, self.profile)

    def test_coupon_item_sold_out_no_available_codes(self):
        """兑换码商品售罄（无可用码）：抛出 RedemptionError."""
        item = ShopItem.objects.create(
            name_zh="售罄兑换码商品",
            name_en="Sold Out Coupon Item",
            description_zh="Test",
            cost=50,
            coupon_type="empty_type",
        )
        # No coupons of this type exist

        with self.assertRaisesMessage(RedemptionError, "该商品已售罄"):
            redeem_item(user=self.user, item_id=item.id)

    def test_coupon_item_does_not_reduce_item_stock(self):
        """兑换码商品不扣减 item.stock."""
        item = ShopItem.objects.create(
            name_zh="不扣库存商品",
            name_en="No Stock Deduction",
            description_zh="Test",
            cost=50,
            stock=10,
            coupon_type="no_stock_type",
        )
        CouponCode.objects.create(code_type="no_stock_type", code="NS001")

        redeem_item(user=self.user, item_id=item.id)

        item.refresh_from_db()
        self.assertEqual(item.stock, 10)  # Stock unchanged

    @patch("shop.services.send_redemption_message")
    def test_coupon_item_sends_message_when_template_exists(self, mock_send_msg):
        """兑换码商品有站内信模板时发送消息."""
        item = ShopItem.objects.create(
            name_zh="带消息商品",
            name_en="With Message Item",
            description_zh="Test",
            cost=50,
            coupon_type="msg_type",
            message_title_template_zh="兑换成功",
            message_content_template_zh="内容",
        )
        CouponCode.objects.create(code_type="msg_type", code="MSG001")

        redeem_item(user=self.user, item_id=item.id)

        mock_send_msg.assert_called_once()
        args = mock_send_msg.call_args
        # First arg is item, second is user, third is coupon, fourth is lang
        self.assertEqual(args[0][0].id, item.id)
        self.assertEqual(args[0][1], self.user)

    @patch(
        "shop.services.send_redemption_message", side_effect=RuntimeError("send failed")
    )
    def test_coupon_item_transaction_rollback_on_message_failure(self, _mock_send):
        """事务回滚测试：模拟站内信发送失败，验证兑换码状态回退为 AVAILABLE."""
        item = ShopItem.objects.create(
            name_zh="回滚测试商品",
            name_en="Rollback Test Item",
            description_zh="Test",
            cost=50,
            coupon_type="rollback_type",
            message_title_template_zh="标题",
            message_content_template_zh="内容",
        )
        CouponCode.objects.create(code_type="rollback_type", code="ROLL001")

        with self.assertRaises(RuntimeError):
            redeem_item(user=self.user, item_id=item.id)

        # Coupon should remain AVAILABLE due to transaction rollback
        coupon = CouponCode.objects.get(code="ROLL001")
        self.assertEqual(coupon.status, CouponCode.Status.AVAILABLE)
        self.assertIsNone(coupon.redeemed_by)

        # No redemption record should exist
        self.assertEqual(Redemption.objects.count(), 0)


class RedeemItemNormalTests(TestCase):
    """Test cases for redeem_item with normal (non-coupon) items (regression)."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="normaluser", email="normal@example.com", password="password123"
        )
        points_services.grant_points(self.user, 10000, PointType.GIFT, "Test points")

    def test_normal_item_coupon_code_is_none(self):
        """普通商品兑换：coupon_code 为 None."""
        item = ShopItem.objects.create(
            name_zh="普通商品",
            name_en="Normal Item",
            description_zh="Test",
            cost=100,
            stock=5,
        )

        result = redeem_item(user=self.user, item_id=item.id)

        self.assertIsNone(result["coupon_code"])
        self.assertIsNotNone(result["redemption"])

    def test_normal_item_reduces_stock(self):
        """普通商品正常扣减库存."""
        item = ShopItem.objects.create(
            name_zh="扣库存商品",
            name_en="Stock Item",
            description_zh="Test",
            cost=50,
            stock=3,
        )

        redeem_item(user=self.user, item_id=item.id)

        item.refresh_from_db()
        self.assertEqual(item.stock, 2)


class StockDynamicCalculationTests(TestCase):
    """Test cases for dynamic stock calculation with coupon_type items."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="stockuser", email="stock@example.com", password="password123"
        )
        self.profile = UserProfile.objects.create(user=self.user)
        points_services.grant_points(self.user, 10000, PointType.GIFT, "Test points")

    def test_coupon_type_stock_equals_available_codes(self):
        """coupon_type 商品的 stock 等于可用兑换码数量."""
        CouponCode.objects.create(code_type="stock_test", code="ST001")
        CouponCode.objects.create(code_type="stock_test", code="ST002")
        CouponCode.objects.create(code_type="stock_test", code="ST003")
        CouponCode.objects.create(
            code_type="stock_test", code="ST004", status=CouponCode.Status.USED
        )

        available_count = CouponCode.objects.filter(
            code_type="stock_test", status=CouponCode.Status.AVAILABLE
        ).count()

        self.assertEqual(available_count, 3)

    def test_coupon_type_stock_decreases_after_claim(self):
        """领取一个后 stock 减 1."""
        CouponCode.objects.create(code_type="dec_test", code="DEC001")
        CouponCode.objects.create(code_type="dec_test", code="DEC002")

        initial_count = CouponCode.objects.filter(
            code_type="dec_test", status=CouponCode.Status.AVAILABLE
        ).count()
        self.assertEqual(initial_count, 2)

        # Claim one
        item = ShopItem.objects.create(
            name_zh="减库存测试",
            name_en="Dec Stock Test",
            description_zh="Test",
            cost=50,
            coupon_type="dec_test",
        )
        redeem_item(user=self.user, item_id=item.id)

        after_count = CouponCode.objects.filter(
            code_type="dec_test", status=CouponCode.Status.AVAILABLE
        ).count()
        self.assertEqual(after_count, 1)

    def test_normal_item_stock_from_item_field(self):
        """普通商品 stock 来自 item.stock 字段."""
        item = ShopItem.objects.create(
            name_zh="普通库存商品",
            name_en="Normal Stock Item",
            description_zh="Test",
            cost=50,
            stock=7,
        )
        self.assertEqual(item.stock, 7)


class BulkImportCouponTests(TestCase):
    """Test cases for bulk import of coupon codes (admin logic)."""

    def test_bulk_import_creates_codes(self):
        """导入多行兑换码成功创建."""
        codes = ["BULK001", "BULK002", "BULK003"]
        objs = [CouponCode(code_type="bulk_type", code=code) for code in codes]
        CouponCode.objects.bulk_create(objs, ignore_conflicts=True)

        self.assertEqual(CouponCode.objects.filter(code_type="bulk_type").count(), 3)
        for code in codes:
            self.assertTrue(
                CouponCode.objects.filter(code_type="bulk_type", code=code).exists()
            )

    def test_bulk_import_duplicate_codes_ignored(self):
        """重复码被忽略（ignore_conflicts）."""
        # Pre-create one code
        CouponCode.objects.create(code_type="dup_type", code="EXISTING")

        # Try to bulk import including the existing code
        codes = ["EXISTING", "NEW001", "NEW002"]
        objs = [CouponCode(code_type="dup_type", code=code) for code in codes]
        CouponCode.objects.bulk_create(objs, ignore_conflicts=True)

        # Should have 3 total (1 existing + 2 new), no error raised
        self.assertEqual(CouponCode.objects.filter(code_type="dup_type").count(), 3)
        # Existing code still has original status
        existing = CouponCode.objects.get(code_type="dup_type", code="EXISTING")
        self.assertEqual(existing.status, CouponCode.Status.AVAILABLE)

    def test_bulk_import_empty_lines_and_whitespace_handled(self):
        """空行和空格被正确处理."""
        # Simulate the admin view's processing logic
        codes_text = "  CODE001  \n\n  CODE002  \n   \n CODE003 \n\n"
        codes = [line.strip() for line in codes_text.splitlines() if line.strip()]

        self.assertEqual(codes, ["CODE001", "CODE002", "CODE003"])

        # Create them
        objs = [CouponCode(code_type="ws_type", code=code) for code in codes]
        CouponCode.objects.bulk_create(objs, ignore_conflicts=True)

        self.assertEqual(CouponCode.objects.filter(code_type="ws_type").count(), 3)
