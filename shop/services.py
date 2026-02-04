"""Service layer for shop application business logic."""

import logging

from django.db import transaction
from django.db.models import F

from points import services as points_services
from points.models import PointType

from .models import Redemption, ShopItem

logger = logging.getLogger(__name__)


class RedemptionError(Exception):
    """Exception raised when redemption fails."""


@transaction.atomic
def redeem_item(user, item_id: int, shipping_address_id=None) -> Redemption:  # noqa: PLR0912, PLR0915
    """
    执行商品兑换的核心业务逻辑.

    这是一个原子操作.

    Args:
        user (User): 执行兑换的用户.
        item_id (int): 要兑换的商品 ID.
        shipping_address_id (int, optional): 收货地址 ID (需要线下发货的商品必须提供).

    Returns:
        Redemption: 成功创建的兑换记录.

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
            item.name,
            item.id,
        )
        raise RedemptionError(msg)
    if item.stock is not None and item.stock <= 0:
        msg = "该商品已售罄。"
        logger.warning(
            "兑换失败（库存不足）: 用户=%s (ID=%s), 商品=%s (ID=%s), 当前库存=%s",
            user.username,
            user.id,
            item.name,
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
                item.name,
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
                item.name,
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
                item.name,
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
            description=f"兑换商品: {item.name}",
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

    # 4. 更新库存 (使用 F() 表达式防止并发问题)
    if item.stock is not None:
        item.stock = F("stock") - 1
        item.save(update_fields=["stock"])

    logger.info(
        "商品兑换成功: 用户=%s (ID=%s), 商品=%s (ID=%s), 消费积分=%s, 兑换记录ID=%s",
        user.username,
        user.id,
        item.name,
        item.id,
        item.cost,
        redemption.id,
    )

    return redemption
