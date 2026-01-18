"""Service layer for shop application business logic."""

import logging

from django.db import transaction
from django.db.models import F

from .models import Redemption, ShopItem

logger = logging.getLogger(__name__)


class RedemptionError(Exception):
    """Exception raised when redemption fails."""


@transaction.atomic
def redeem_item(user, item_id: int, shipping_address_id=None) -> Redemption:
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

    # 2. 创建兑换记录
    redemption = Redemption.objects.create(
        user_profile=user,
        item=item,
        points_cost_at_redemption=item.cost,
        status=Redemption.StatusChoices.COMPLETED,
        shipping_address=shipping_address,
    )

    # 3. 更新库存 (使用 F() 表达式防止并发问题)
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
