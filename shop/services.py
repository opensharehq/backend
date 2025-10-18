"""Service layer for shop application business logic."""

import logging

from django.db import transaction
from django.db.models import F

from points.services import spend_points

from .models import Redemption, ShopItem

logger = logging.getLogger(__name__)


class RedemptionError(Exception):
    """Exception raised when redemption fails."""


@transaction.atomic
def redeem_item(user_profile, item_id: int, shipping_address_id=None) -> Redemption:
    """
    执行商品兑换的核心业务逻辑.

    这是一个原子操作.

    Args:
        user_profile (UserProfile): 执行兑换的用户.
        item_id (int): 要兑换的商品 ID.
        shipping_address_id (int, optional): 收货地址 ID (需要线下发货的商品必须提供).

    Returns:
        Redemption: 成功创建的兑换记录.

    Raises:
        RedemptionError: 如果商品无效、下架、库存不足或缺少收货地址.
        InsufficientPointsError: 如果用户积分不足(由 points 服务层抛出).

    """
    try:
        # 使用 prefetch_related 优化查询，一次性获取商品及其关联的标签
        item = ShopItem.objects.prefetch_related("allowed_tags").get(id=item_id)
    except ShopItem.DoesNotExist as err:
        msg = "商品不存在。"
        raise RedemptionError(msg) from err

    # 1. 前置条件检查
    if not item.is_active:
        msg = "该商品已下架。"
        logger.warning(
            "兑换失败（商品已下架）: 用户=%s (ID=%s), 商品=%s (ID=%s)",
            user_profile.username,
            user_profile.id,
            item.name,
            item.id,
        )
        raise RedemptionError(msg)
    if item.stock is not None and item.stock <= 0:
        msg = "该商品已售罄。"
        logger.warning(
            "兑换失败（库存不足）: 用户=%s (ID=%s), 商品=%s (ID=%s), 当前库存=%s",
            user_profile.username,
            user_profile.id,
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
                user_profile.username,
                user_profile.id,
                item.name,
                item.id,
            )
            raise RedemptionError(msg)

        # 验证地址是否属于当前用户
        from accounts.models import ShippingAddress

        try:
            shipping_address = ShippingAddress.objects.get(
                id=shipping_address_id,
                user=user_profile,
            )
        except ShippingAddress.DoesNotExist as err:
            msg = "无效的收货地址。"
            raise RedemptionError(msg) from err

    # 2. 确定积分标签约束
    allowed_tags = list(item.allowed_tags.values_list("name", flat=True))

    # 3. 调用积分服务进行扣除 (核心交互)
    # InsufficientPointsError 会在这里被抛出并传递到上层
    # If there are allowed tags, use the first one as priority tag
    # Note: Future enhancement could support multiple allowed tags
    priority_tag = allowed_tags[0] if allowed_tags else None

    spend_transaction = spend_points(
        user_profile=user_profile,
        amount=item.cost,
        description=f"兑换商品: {item.name}",
        priority_tag_name=priority_tag,
    )

    # 4. 创建兑换记录
    redemption = Redemption.objects.create(
        user_profile=user_profile,
        item=item,
        points_cost_at_redemption=item.cost,  # 记录兑换时的价格
        transaction=spend_transaction,
        status=Redemption.StatusChoices.COMPLETED,  # 成功则直接完成
        shipping_address=shipping_address,  # 关联收货地址（如果需要）
    )

    # 5. 更新库存 (使用 F() 表达式防止并发问题)
    if item.stock is not None:
        item.stock = F("stock") - 1
        item.save(update_fields=["stock"])

    logger.info(
        "商品兑换成功: 用户=%s (ID=%s), 商品=%s (ID=%s), 消费积分=%s, 兑换记录ID=%s, 优先标签=%s",
        user_profile.username,
        user_profile.id,
        item.name,
        item.id,
        item.cost,
        redemption.id,
        priority_tag or "无",
    )

    return redemption
