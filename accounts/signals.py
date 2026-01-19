"""Signals for accounts app."""

import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from social_django.models import UserSocialAuth

logger = logging.getLogger(__name__)


@receiver(post_save, sender=UserSocialAuth)
def claim_pending_points_on_login(sender, instance, created, **kwargs):
    """用户首次 OAuth 登录时自动领取待领取积分."""
    if created and instance.provider == "github":
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
