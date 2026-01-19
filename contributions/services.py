"""贡献度查询服务."""

from datetime import date
from decimal import Decimal

from accounts.models import User


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
            project_identifiers: 项目标识列表 ["alibaba/dubbo", ...]
            user_filters: 用户筛选条件(可选)
            start_month: 起始月份
            end_month: 结束月份
            use_cache: 是否使用缓存

        Returns:
            [
                {
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
        # 先实现 fake 数据
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
        从 ClickHouse 查询真实数据(预留接口).

        当前实现会直接抛出 NotImplementedError。
        """
        msg = "ClickHouse 集成尚未实现"
        raise NotImplementedError(msg)
