"""Signals for accounts app."""

import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from social_django.models import UserSocialAuth

from common.constants import CODE_HOSTING_PROVIDERS

logger = logging.getLogger(__name__)


@receiver(post_save, sender=UserSocialAuth)
def claim_pending_points_on_login(sender, instance, created, **kwargs):
    """用户首次 OAuth 登录时自动领取待领取积分."""
    from accounts.services.profile_completion_reward import invalidate_cached_reward

    invalidate_cached_reward(instance.user)

    if created and instance.provider in CODE_HOSTING_PROVIDERS:
        from points.allocation_services import AllocationService

        user = instance.user
        result = AllocationService.claim_pending_points(user)

        if result["claimed_count"] > 0:
            # 记录日志
            logger.info(
                "User %s claimed %d pending point grants totaling %d points",
                user.username,
                result["claimed_count"],
                result["total_amount"],
            )

            # Send in-app notification or email when messaging system is implemented
            # from messaging.services import send_notification
            # send_notification(
            #     user=user,
            #     title="积分领取成功",
            #     message="您已成功领取 %d 笔待领取积分，共 %d 点。"
            #             % (result['claimed_count'], result['total_amount'])
            # )


@receiver(post_delete, sender=UserSocialAuth)
def invalidate_developer_tier_on_disconnect(sender, instance, **kwargs):
    """Invalidate the highest-tier cache when a social account is disconnected."""
    from accounts.services.profile_completion_reward import invalidate_cached_reward

    invalidate_cached_reward(instance.user)
