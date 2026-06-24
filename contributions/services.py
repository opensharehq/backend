"""贡献度查询服务."""

import logging
from decimal import Decimal

from social_django.models import UserSocialAuth

logger = logging.getLogger(__name__)

# SQLite 单条 SQL 中 ? 占位符的默认上限为 999 (旧版) / 32766 (新版),
# 这里取保守值, 避免 uid__in=[...] 触发 "too many SQL variables".
_SQL_IN_BATCH_SIZE = 900


class ContributionDataUnavailableError(RuntimeError):
    """Raised when contribution data cannot be fetched from the backend."""


class ContributionService:
    """贡献度查询服务."""

    @staticmethod
    def _validate_platform_present(contributions: list[dict]) -> None:
        """
        Require every ClickHouse contribution row to include a platform.

        Contributor identity is keyed by (platform, actor_id). Missing platform
        values would make downstream pending-grant storage and claim flows lose
        identity boundaries. This only validates presence and does not restrict
        specific platform values.
        """
        for index, contrib in enumerate(contributions):
            platform = contrib.get("platform") if isinstance(contrib, dict) else None
            if not isinstance(platform, str) or not platform.strip():
                msg = f"ClickHouse 贡献数据第 {index} 条缺失 platform 字段,拒绝进入后续流程"
                logger.error(msg)
                raise ContributionDataUnavailableError(msg)

    @staticmethod
    def _enrich_with_registration_status(contributions: list[dict]) -> list[dict]:
        """
        为贡献者数据添加注册状态信息.

        Args:
            contributions: 来自 ClickHouse 的贡献度数据

        Returns:
            添加了注册状态的贡献者列表

        """
        # 收集所有平台用户 ID
        platform_user_map = {}  # {platform: {actor_id: actor_login}}
        for contrib in contributions:
            platform = contrib["platform"].lower()
            actor_id = str(contrib["actor_id"])
            actor_login = contrib["actor_login"]

            if platform not in platform_user_map:
                platform_user_map[platform] = {}
            platform_user_map[platform][actor_id] = actor_login

        # 查询已注册用户 (分批, 避免 SQLite "too many SQL variables" 限制)
        registered_users = {}  # {(platform, uid): user_id}
        for platform, actor_map in platform_user_map.items():
            actor_ids = list(actor_map.keys())
            for start in range(0, len(actor_ids), _SQL_IN_BATCH_SIZE):
                batch = actor_ids[start : start + _SQL_IN_BATCH_SIZE]
                social_auths = UserSocialAuth.objects.filter(
                    provider=platform, uid__in=batch
                ).select_related("user")

                for social_auth in social_auths:
                    key = (platform, social_auth.uid)
                    registered_users[key] = social_auth.user.id

        # 构建结果
        results = []
        for contrib in contributions:
            platform = contrib["platform"].lower()
            actor_id = contrib["actor_id"]
            normalized_actor_id = str(actor_id)
            actor_login = contrib["actor_login"]
            contribution_score = contrib["contribution_score"]
            details = contrib.get("details")

            # 检查是否已注册
            key = (platform, normalized_actor_id)
            user_id = registered_users.get(key)
            is_registered = user_id is not None

            payload = {
                "platform": contrib["platform"],
                "actor_id": str(actor_id),
                "actor_login": actor_login,
                f"{platform}_id": actor_id,
                f"{platform}_login": actor_login,
                "email": "",  # ClickHouse 中没有 email
                "contribution_score": Decimal(str(contribution_score)),
                "is_registered": is_registered,
                "user_id": user_id,
            }
            if details is not None:
                payload["details"] = details

            top_repos = contrib.get("top_repos")
            if top_repos is not None:
                payload["top_repos"] = top_repos

            results.append(payload)

        return results
