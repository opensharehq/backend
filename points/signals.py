"""Signal handlers for points app to maintain cache consistency."""

import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import PointSource, PointTransaction, Tag

User = get_user_model()
logger = logging.getLogger(__name__)


@receiver(post_save, sender=PointSource)
@receiver(post_delete, sender=PointSource)
def clear_user_points_cache_on_source_change(sender, instance, **kwargs):
    """Clear user's cached total_points when PointSource is modified."""
    user = instance.user
    if user:
        user.clear_points_cache()


@receiver(post_save, sender=PointTransaction)
@receiver(post_delete, sender=PointTransaction)
def clear_user_points_cache_on_transaction_change(sender, instance, **kwargs):
    """Clear user's cached total_points when PointTransaction is modified."""
    user = instance.user
    if user:
        user.clear_points_cache()


@receiver(post_save, sender=User)
def create_default_point_source_for_new_user(sender, instance, created, **kwargs):
    """为新创建的用户自动创建带有 default 标签的初始积分池."""
    if not created:
        return

    try:
        # 使用 transaction.on_commit 确保在事务提交后执行
        # 避免在用户创建事务中出现问题
        transaction.on_commit(lambda: _create_default_point_source(instance))
    except Exception as e:
        logger.exception(
            "为新用户创建默认积分池失败: 用户=%s (ID=%s), 错误=%s",
            instance.username,
            instance.id,
            e,
        )


def _create_default_point_source(user):
    """为用户创建默认积分池的内部函数."""
    try:
        # 获取 default 标签
        default_tag = Tag.objects.filter(slug="default").first()

        if not default_tag:
            logger.warning(
                "未找到 default 标签，跳过为用户创建默认积分池: 用户=%s (ID=%s)",
                user.username,
                user.id,
            )
            return

        # 创建初始积分池（积分为 0）
        point_source = PointSource.objects.create(
            user=user,
            initial_points=0,
            remaining_points=0,
            allow_recharge=True,
            notes="用户注册时自动创建的默认积分池",
        )
        # 关联 default 标签
        point_source.tags.add(default_tag)

        logger.info(
            "为新用户创建默认积分池成功: 用户=%s (ID=%s), 积分池ID=%s",
            user.username,
            user.id,
            point_source.id,
        )
    except Exception as e:
        logger.exception(
            "创建默认积分池时发生异常: 用户=%s (ID=%s), 错误=%s",
            user.username,
            user.id,
            e,
        )
