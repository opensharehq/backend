"""Service layer for shop application business logic."""

import logging

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from points import services as points_services
from points.models import PointType

from .models import Redemption, ShopItem

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
def redeem_item(user, item_id: int, shipping_address_id=None, lang="zh") -> dict:  # noqa: PLR0912, PLR0915
    """
    执行商品兑换的核心业务逻辑.

    这是一个原子操作.

    Args:
        user (User): 执行兑换的用户.
        item_id (int): 要兑换的商品 ID.
        shipping_address_id (int, optional): 收货地址 ID (需要线下发货的商品必须提供).
        lang (str): 站内信语言, 默认 "zh".

    Returns:
        dict: 包含 redemption 和 coupon_code 的字典.

    Raises:
        RedemptionError: 如果商品无效、下架、库存不足或缺少收货地址.

    """
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

    # 2. 积分验证和扣除
    tag_slug = None
    allowed_tags = list(item.allowed_tags.all())

    if allowed_tags:
        # 商品有标签限制，查找用户拥有的、商品允许的标签积分
        for tag in allowed_tags:
            balance = points_services.get_balance(user, PointType.GIFT, tag.slug)
            if balance >= item.cost:
                tag_slug = tag.slug
                break

        if tag_slug is None:
            msg = "您没有足够的符合条件的积分来兑换此商品"
            logger.warning(
                "兑换失败（标签积分不足）: 用户=%s (ID=%s), 商品=%s (ID=%s), 需要标签=%s",
                user.username,
                user.id,
                item.name_zh,
                item.id,
                [t.slug for t in allowed_tags],
            )
            raise RedemptionError(msg)
    else:
        # 无标签限制，使用任意礼物积分
        balance = points_services.get_balance(user, PointType.GIFT)
        if balance < item.cost:
            msg = f"积分不足：需要 {item.cost}，当前可用 {balance}"
            logger.warning(
                "兑换失败（积分不足）: 用户=%s (ID=%s), 商品=%s (ID=%s), 需要=%s, 可用=%s",
                user.username,
                user.id,
                item.name_zh,
                item.id,
                item.cost,
                balance,
            )
            raise RedemptionError(msg)

    # 扣除积分
    try:
        points_services.spend_points(
            owner=user,
            amount=item.cost,
            point_type=PointType.GIFT,
            description=f"兑换商品: {item.name_zh}",
            tag_slug=tag_slug,
            reference_id=f"shop:item:{item.id}",
            created_by=user,
        )
    except points_services.InsufficientPointsError as err:
        msg = f"积分不足：{err}"
        raise RedemptionError(msg) from err

    # 3. 创建兑换记录
    redemption = Redemption.objects.create(
        user_profile=user,
        item=item,
        points_cost_at_redemption=item.cost,
        status=Redemption.StatusChoices.COMPLETED,
        shipping_address=shipping_address,
    )

    # 4. 更新库存 (仅非 coupon_type 商品，使用 F() 表达式防止并发问题)
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

    # 5. 发送站内信（在事务内部，失败则整体回滚）
    if item.has_message_template():
        send_redemption_message(item, user, coupon, lang)

    logger.info(
        "商品兑换成功: 用户=%s (ID=%s), 商品=%s (ID=%s), 消费积分=%s, 兑换记录ID=%s",
        user.username,
        user.id,
        item.name_zh,
        item.id,
        item.cost,
        redemption.id,
    )

    return {"redemption": redemption, "coupon_code": coupon.code if coupon else None}
