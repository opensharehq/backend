"""Service layer for shop application business logic."""

import logging
from collections import defaultdict

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from points import services as points_services
from points.models import PointType

from .models import Redemption, RedemptionPaymentLine, ShopItem

logger = logging.getLogger(__name__)


class RedemptionError(Exception):
    """Exception raised when redemption fails."""


def claim_coupon(code_type: str, user_profile) -> "CouponCode":  # noqa: F821
    """
    Atomically claim a coupon code.

    Uses select_for_update(skip_locked=True) to prevent concurrent duplicate claims.
    In SQLite environments, select_for_update is a no-op without affecting functionality.
    """
    from .models import CouponCode

    coupon = (
        CouponCode.objects.select_for_update(skip_locked=True)
        .filter(code_type=code_type, status=CouponCode.Status.AVAILABLE)
        .order_by("id")
        .first()
    )
    if coupon is None:
        msg = "该商品已售罄。"
        raise RedemptionError(msg)

    coupon.status = CouponCode.Status.USED
    coupon.redeemed_by = user_profile
    coupon.redeemed_at = timezone.now()
    coupon.save(update_fields=["status", "redeemed_by", "redeemed_at"])
    return coupon


def send_redemption_message(item, user, coupon, lang="zh"):
    """Send redemption success notification based on item's message template."""
    from messages.models import Message
    from messages.services import send_message

    params = {
        "timestamp": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
        "coupon_code": coupon.code if coupon else "",
        "item_name": getattr(item, f"name_{lang}", None) or item.name_zh,
    }

    # 选择对应语言的模板，回退到中文
    title_template = (
        getattr(item, f"message_title_template_{lang}", "")
        or item.message_title_template_zh
    )
    content_template = (
        getattr(item, f"message_content_template_{lang}", "")
        or item.message_content_template_zh
    )

    if not title_template and not content_template:
        return  # 无模板则不发送

    try:
        title = title_template.format(**params) if title_template else ""
        content = content_template.format(**params) if content_template else ""
    except (KeyError, ValueError, IndexError) as err:
        logger.error(
            "Message template format error for item %s (ID=%s): %s",
            item.name_zh,
            item.id,
            err,
        )
        msg = f"站内信模板格式错误: {err}"
        raise RedemptionError(msg) from err

    send_message(
        title=title,
        content=content,
        message_type=Message.MessageType.ORDER,
        recipients=[user],
    )


@transaction.atomic
def redeem_item(  # noqa: PLR0912, PLR0913, PLR0915
    user,
    item_id: int,
    shipping_address_id=None,
    lang="zh",
    point_type="gift",
    tag_slug=None,
    use_untagged_gift=False,
    use_cash=False,
) -> dict:
    """
    执行商品兑换的核心业务逻辑.

    这是一个原子操作.

    Args:
        user (User): 执行兑换的用户.
        item_id (int): 要兑换的商品 ID.
        shipping_address_id (int, optional): 收货地址 ID (需要线下发货的商品必须提供).
        lang (str): 站内信语言, 默认 "zh".
        point_type (str): 支付积分类型, "gift" 或 "cash", 默认 "gift".
        tag_slug (str, optional): 指定使用的标签积分 slug (仅 point_type="gift" 时有效).
        use_untagged_gift (bool): 标签积分不足时是否使用无标签礼物积分补足.
        use_cash (bool): 礼物积分不足时是否使用现金积分补足.

    Returns:
        dict: 包含 redemption 和 coupon_code 的字典.

    Raises:
        RedemptionError: 如果商品无效、下架、库存不足、积分不足或参数无效.

    """
    # 0. Normalize empty-string tag_slug (e.g. JSON "") to None so that
    #    validation/branching and spending always use a single "no tag" form.
    if tag_slug == "":
        tag_slug = None

    # 1. 校验 point_type 参数
    if point_type not in [PointType.CASH, PointType.GIFT]:
        msg = f"无效的积分类型: {point_type}"
        raise RedemptionError(msg)

    if tag_slug and point_type != PointType.GIFT:
        msg = "只有礼物积分可以设置标签"
        raise RedemptionError(msg)
    if point_type == PointType.CASH and use_untagged_gift:
        msg = "现金积分支付不能使用通用礼物积分补足"
        raise RedemptionError(msg)

    try:
        item = ShopItem.objects.get(id=item_id)
    except ShopItem.DoesNotExist as err:
        msg = "商品不存在。"
        raise RedemptionError(msg) from err

    # 1. 前置条件检查
    if not item.is_active:
        msg = "该商品已下架。"
        logger.warning(
            "兑换失败（商品已下架）: 用户=%s (ID=%s), 商品=%s (ID=%s)",
            user.username,
            user.id,
            item.name_zh,
            item.id,
        )
        raise RedemptionError(msg)

    # 兑换码领取
    coupon = None

    if item.coupon_type:
        # 非实物商品（兑换码类型）：通过 claim_coupon 领取
        # 不再检查 item.stock，库存由兑换码可用数量决定
        coupon = claim_coupon(item.coupon_type, user.profile)
    # 实物/普通商品：保持现有库存检查
    elif item.stock is not None and item.stock <= 0:
        msg = "该商品已售罄。"
        logger.warning(
            "兑换失败（库存不足）: 用户=%s (ID=%s), 商品=%s (ID=%s), 当前库存=%s",
            user.username,
            user.id,
            item.name_zh,
            item.id,
            item.stock,
        )
        raise RedemptionError(msg)

    # 检查是否需要收货地址
    shipping_address = None
    if item.requires_shipping:
        if not shipping_address_id:
            msg = "此商品需要收货地址。"
            logger.warning(
                "兑换失败（缺少收货地址）: 用户=%s (ID=%s), 商品=%s (ID=%s)",
                user.username,
                user.id,
                item.name_zh,
                item.id,
            )
            raise RedemptionError(msg)

        # 验证地址是否属于当前用户
        from accounts.models import ShippingAddress

        try:
            shipping_address = ShippingAddress.objects.get(
                id=shipping_address_id,
                user=user,
            )
        except ShippingAddress.DoesNotExist as err:
            msg = "无效的收货地址。"
            raise RedemptionError(msg) from err

    # 2. 校验商品允许的主积分池
    allowed_tags = list(item.allowed_tags.all())
    resolved_tag_slug = tag_slug

    if point_type == PointType.GIFT:
        if tag_slug:
            # 使用指定标签的礼物积分
            # 带标签的 gift 积分只能用于有匹配 allowed_tags 的商品
            if not allowed_tags or tag_slug not in [t.slug for t in allowed_tags]:
                msg = "您没有足够的符合条件的积分来兑换此商品"
                logger.warning(
                    "兑换失败（标签不匹配）: 用户=%s (ID=%s), 商品=%s (ID=%s), 指定标签=%s, 允许标签=%s",
                    user.username,
                    user.id,
                    item.name_zh,
                    item.id,
                    tag_slug,
                    [t.slug for t in allowed_tags],
                )
                raise RedemptionError(msg)
        # 无标签礼物积分是通用积分，对有标签限制的商品也可直接兑换。

    # 3. 先创建待处理兑换，以便所有积分流水使用唯一兑换 reference_id。
    redemption = Redemption.objects.create(
        user_profile=user,
        item=item,
        points_cost_at_redemption=item.cost,
        status=Redemption.StatusChoices.PENDING,
        shipping_address=shipping_address,
        point_type=point_type,
        point_tag_slug=resolved_tag_slug,
    )

    # 4. 在用户明确授权的积分池中按优先级原子扣款。
    try:
        point_transactions = points_services.spend_points_with_fallback(
            owner=user,
            amount=item.cost,
            primary_point_type=point_type,
            description=f"兑换商品: {item.name_zh}",
            tag_slug=resolved_tag_slug,
            use_untagged_gift=use_untagged_gift,
            use_cash=use_cash,
            reference_id=f"shop:redemption:{redemption.id}",
            created_by=user,
        )
    except points_services.InsufficientPointsError as err:
        error_message = str(err)
        msg = (
            error_message
            if error_message.startswith("积分不足")
            else f"积分不足：{error_message}"
        )
        raise RedemptionError(msg) from err

    payment_amounts: dict[tuple[str, str | None], int] = defaultdict(int)
    for point_transaction in point_transactions:
        transaction_tag_slug = (
            point_transaction.tag.slug if point_transaction.tag else None
        )
        payment_amounts[(point_transaction.point_type, transaction_tag_slug)] += abs(
            point_transaction.amount
        )
    RedemptionPaymentLine.objects.bulk_create(
        [
            RedemptionPaymentLine(
                redemption=redemption,
                point_type=line_point_type,
                tag_slug=line_tag_slug,
                amount=line_amount,
            )
            for (line_point_type, line_tag_slug), line_amount in payment_amounts.items()
        ]
    )

    # 5. 更新库存 (仅非 coupon_type 商品，使用 F() 表达式防止并发问题)
    if not item.coupon_type and item.stock is not None:
        updated_rows = ShopItem.objects.filter(id=item.id, stock__gt=0).update(
            stock=F("stock") - 1
        )
        if updated_rows == 0:
            msg = "该商品已售罄。"
            logger.warning(
                "兑换失败（并发库存不足）: 用户=%s (ID=%s), 商品=%s (ID=%s)",
                user.username,
                user.id,
                item.name_zh,
                item.id,
            )
            raise RedemptionError(msg)

    redemption.status = Redemption.StatusChoices.COMPLETED
    redemption.save(update_fields=["status"])

    # 6. 发送站内信（在事务内部，失败则整体回滚）
    if item.has_message_template():
        send_redemption_message(item, user, coupon, lang)

    logger.info(
        "商品兑换成功: 用户=%s (ID=%s), 商品=%s (ID=%s), 消费积分=%s (type=%s), 兑换记录ID=%s",
        user.username,
        user.id,
        item.name_zh,
        item.id,
        item.cost,
        point_type,
        redemption.id,
    )

    return {"redemption": redemption, "coupon_code": coupon.code if coupon else None}
