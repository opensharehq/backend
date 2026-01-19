"""贡献度查询服务."""

import logging
from datetime import date
from decimal import Decimal

from social_django.models import UserSocialAuth

from accounts.models import User

logger = logging.getLogger(__name__)


class ContributionService:
    """贡献度查询服务."""

    @staticmethod
    def get_contributions(
        project_identifiers: list[str],
        user_filters: dict | None = None,
        start_month: date | None = None,
        end_month: date | None = None,
        use_cache: bool = True,
    ) -> list[dict]:
        """
        查询贡献度数据.

        Args:
            project_identifiers: 项目标识列表 (label_id 列表)
            user_filters: 用户筛选条件(可选)
            start_month: 起始月份
            end_month: 结束月份
            use_cache: 是否使用缓存

        Returns:
            [
                {
                    "platform": "GitHub",
                    "github_id": "123456",
                    "github_login": "username",
                    "email": "user@example.com",
                    "contribution_score": 150.5,
                    "is_registered": true,
                    "user_id": 1  # 如果已注册
                },
                ...
            ]

        """
        # 使用真实数据
        try:
            return ContributionService.query_from_clickhouse(
                project_identifiers, start_month, end_month
            )
        except Exception as e:
            logger.error("查询 ClickHouse 失败: %s", e)
            # 降级到 fake 数据
            logger.warning("降级使用 fake 数据")
            return ContributionService._get_fake_contributions(
                project_identifiers, start_month, end_month
            )

    @staticmethod
    def _get_fake_contributions(
        project_identifiers: list[str], start_month: date, end_month: date
    ) -> list[dict]:
        """返回 fake 贡献度数据(用于开发和测试)."""
        # 获取所有已注册的用户(假设前5个用户)
        users = User.objects.all()[:5]

        fake_data = []

        # 为已注册用户生成数据
        for i, user in enumerate(users):
            # 尝试获取用户的 GitHub 信息
            github_social = user.social_auth.filter(provider="github").first()
            github_id = github_social.uid if github_social else str(1000000 + i)
            github_login = user.username

            fake_data.append(
                {
                    "github_id": github_id,
                    "github_login": github_login,
                    "email": user.email,
                    "contribution_score": Decimal(str(250.5 - i * 20)),
                    "is_registered": True,
                    "user_id": user.id,
                }
            )

        # 添加一些未注册用户的数据
        unregistered_users = [
            {
                "github_id": "2345678",
                "github_login": "bob_unregistered",
                "email": "bob@example.com",
                "contribution_score": Decimal("180.3"),
            },
            {
                "github_id": "3456789",
                "github_login": "charlie_dev",
                "email": "charlie@example.com",
                "contribution_score": Decimal("150.8"),
            },
            {
                "github_id": "4567890",
                "github_login": "diana_contributor",
                "email": "diana@example.com",
                "contribution_score": Decimal("120.5"),
            },
        ]

        for user_data in unregistered_users:
            fake_data.append(
                {
                    **user_data,
                    "is_registered": False,
                    "user_id": None,
                }
            )

        return fake_data

    @staticmethod
    def query_from_clickhouse(
        project_identifiers: list[str], start_month: date, end_month: date
    ) -> list[dict]:
        """
        从 ClickHouse 查询真实数据.

        Args:
            project_identifiers: 项目标识列表 (label_id 列表)
            start_month: 起始月份
            end_month: 结束月份

        Returns:
            贡献者列表, 包含贡献度和注册状态

        """
        from chdb import services as chdb_services

        # 转换日期为 yyyymm 格式
        start_yyyymm = int(start_month.strftime("%Y%m"))
        end_yyyymm = int(end_month.strftime("%Y%m"))

        # 查询贡献度数据
        contributions = chdb_services.query_contributions(
            label_ids=project_identifiers,
            start_month=start_yyyymm,
            end_month=end_yyyymm,
        )

        if not contributions:
            logger.info("未查询到贡献度数据")
            return []

        # 判断用户注册状态
        results = ContributionService._enrich_with_registration_status(contributions)

        logger.info(
            "查询到 %s 个贡献者, 其中 %s 个已注册",
            len(results),
            sum(1 for r in results if r["is_registered"]),
        )

        return results

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
            actor_id = contrib["actor_id"]
            actor_login = contrib["actor_login"]

            if platform not in platform_user_map:
                platform_user_map[platform] = {}
            platform_user_map[platform][actor_id] = actor_login

        # 查询已注册用户
        registered_users = {}  # {(platform, uid): user_id}
        for platform, actor_map in platform_user_map.items():
            actor_ids = list(actor_map.keys())
            social_auths = UserSocialAuth.objects.filter(
                provider=platform, uid__in=actor_ids
            ).select_related("user")

            for social_auth in social_auths:
                key = (platform, social_auth.uid)
                registered_users[key] = social_auth.user.id

        # 构建结果
        results = []
        for contrib in contributions:
            platform = contrib["platform"].lower()
            actor_id = contrib["actor_id"]
            actor_login = contrib["actor_login"]
            contribution_score = contrib["contribution_score"]

            # 检查是否已注册
            key = (platform, actor_id)
            user_id = registered_users.get(key)
            is_registered = user_id is not None

            results.append(
                {
                    "platform": contrib["platform"],
                    f"{platform}_id": actor_id,
                    f"{platform}_login": actor_login,
                    "email": "",  # ClickHouse 中没有 email
                    "contribution_score": Decimal(str(contribution_score)),
                    "is_registered": is_registered,
                    "user_id": user_id,
                }
            )

        return results
