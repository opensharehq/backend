"""ClickHouse 服务层: 标签搜索和用户信息查询."""

import json
import logging
from typing import Any

from chdb.clickhousedb import ClickHouseDB

logger = logging.getLogger(__name__)


def _get_result_rows(result: Any) -> list[Any]:
    """兼容 clickhouse-connect 不同结果对象的行访问方式."""
    if result is None:
        return []

    for attr in ("result_rows", "data", "rows"):
        if hasattr(result, attr):
            rows = getattr(result, attr)
            return rows or []

    return []


def _normalize_label_ids(label_ids: list[Any]) -> list[str]:
    """规范化标签 ID 列表."""
    normalized_ids = []
    for label_id in label_ids:
        if label_id is None:
            continue
        label_id_str = str(label_id).strip()
        if label_id_str:
            normalized_ids.append(label_id_str)
    return normalized_ids


def _extract_openrank(raw_data: Any) -> float | None:
    """从 labels.data 中尝试解析 OpenRank."""
    openrank = None
    payload = None

    if isinstance(raw_data, (int, float)):
        openrank = float(raw_data)
    elif isinstance(raw_data, str):
        try:
            payload = json.loads(raw_data)
        except (TypeError, ValueError):
            payload = None

    if openrank is None and isinstance(payload, dict):
        for key in ("openrank", "open_rank", "openRank"):
            if key in payload:
                try:
                    openrank = float(payload[key])
                except (TypeError, ValueError):
                    openrank = None
                break

    return openrank


def search_tags(keyword: str, limit: int = 5) -> list[dict[str, Any]]:
    """
    搜索 opensource.labels 表中的标签.

    Args:
        keyword: 搜索关键词, 支持模糊匹配
        limit: 最大返回条数, 默认 5

    Returns:
        标签列表, 每个标签包含:
        - id: 标签 ID (将作为 Django Tag 的 slug)
        - type: 类型 (repo/org/user)
        - platform: 平台 (github/gitee/gitlab 等)
        - name: 名称
        - openrank: OpenRank 分数
        - name_display: 显示名称 (name + platform)
        - slug: slug 字段 (与 id 相同)

    """
    if not keyword or not keyword.strip():
        logger.warning("空关键词搜索被拒绝")
        return []

    keyword = keyword.strip()

    try:
        # 使用参数化查询防止 SQL 注入
        sql = """
            SELECT
                id,
                type,
                name,
                name_zh,
                `platforms.name`,
                data
            FROM opensource.labels
            WHERE name ILIKE {keyword:String}
               OR name_zh ILIKE {keyword:String}
               OR id ILIKE {keyword:String}
            ORDER BY name
            LIMIT {limit:UInt32}
        """

        result = ClickHouseDB.query(
            sql, parameters={"keyword": f"%{keyword}%", "limit": limit}
        )

        # 格式化结果
        tags = []
        for row in _get_result_rows(result):
            tag_id = row[0]
            tag_type = row[1]
            name = row[2] or ""
            name_zh = row[3] or ""
            platforms = [platform for platform in (row[4] or []) if platform]
            raw_data = row[5] if len(row) > 5 else None
            openrank = _extract_openrank(raw_data)

            display_name = name_zh or name or tag_id
            platform = "/".join(platforms) if platforms else "unknown"
            platform_display = (
                "/".join([platform.capitalize() for platform in platforms])
                if platforms
                else "Unknown"
            )

            tags.append(
                {
                    "id": tag_id,
                    "type": tag_type,
                    "platform": platform,
                    "platforms": platforms,
                    "name": display_name,
                    "openrank": openrank,
                    "name_display": f"{display_name} ({platform_display})",
                    "slug": tag_id,  # id 作为 Django Tag 的 slug
                }
            )

        logger.info("搜索关键词 '%s' 返回 %s 个标签", keyword, len(tags))
        return tags

    except Exception as e:
        logger.error("搜索标签失败 (关键词: %s): %s", keyword, e)
        return []


def get_label_users(label_ids: list[Any]) -> dict[str, dict[str, Any]]:
    """
    查询 opensource.labels 表获取标签的平台和用户信息.

    Args:
        label_ids: 标签 ID 列表 (来自 opensource.labels.id, 支持 str 或 int)

    Returns:
        字典映射, 格式: {label_id: {"platforms": [...], "users": {...}}}

        platforms: 平台名称列表 (platforms.name)
        users: 平台到用户 ID 数组的映射 (platforms.users 是嵌套数组)

    Example:
        >>> get_label_users(["github-microsoft-vscode"])
        {
            "github-microsoft-vscode": {
                "platforms": ["github", "gitee"],
                "users": {
                    "github": [[123, 456]],
                    "gitee": [[789]]
                }
            }
        }

    """
    if not label_ids:
        logger.warning("空标签列表查询被拒绝")
        return {}

    normalized_ids = _normalize_label_ids(label_ids)

    if not normalized_ids:
        logger.warning("标签列表去空后为空, 跳过查询")
        return {}

    try:
        # 查询 opensource.labels 表
        # 注意：platforms.name 和 platforms.users 是数组字段
        sql = """
            SELECT
                id,
                `platforms.name`,
                `platforms.users`
            FROM opensource.labels
            WHERE id IN {label_ids:Array(String)}
        """

        result = ClickHouseDB.query(sql, parameters={"label_ids": normalized_ids})

        # 构建结果映射
        label_info = {}
        for row in _get_result_rows(result):
            label_id = row[0]
            platforms_names = row[1]  # Array
            platforms_users = row[2]  # Array(Array(UInt64))

            # 构建平台到用户的映射
            users_by_platform = {}
            for i, platform_name in enumerate(platforms_names):
                if i < len(platforms_users):
                    users_by_platform[platform_name] = platforms_users[i]

            label_info[label_id] = {
                "platforms": list(platforms_names),
                "users": users_by_platform,
            }

        logger.info(
            "查询 %s 个标签, 返回 %s 个结果", len(normalized_ids), len(label_info)
        )
        return label_info

    except Exception as e:
        logger.error("查询标签用户信息失败 (标签数: %s): %s", len(label_ids), e)
        return {}


def get_label_entities(label_ids: list[Any]) -> dict[str, dict[str, Any]]:
    """
    查询 opensource.labels 表获取标签关联实体信息.

    Args:
        label_ids: 标签 ID 列表 (来自 opensource.labels.id, 支持 str 或 int)

    Returns:
        字典映射, 格式:
        {
            label_id: {
                "id": label_id,
                "type": label_type,
                "name": name,
                "name_zh": name_zh,
                "children": [...],
                "platforms": [...],
                "orgs": {platform: [org_ids]},
                "repos": {platform: [repo_ids]},
                "users": {platform: [user_ids]},
            }
        }

    """
    if not label_ids:
        logger.warning("空标签列表查询被拒绝")
        return {}

    normalized_ids = _normalize_label_ids(label_ids)
    if not normalized_ids:
        logger.warning("标签列表去空后为空, 跳过查询")
        return {}

    try:
        sql = """
            SELECT
                id,
                type,
                name,
                name_zh,
                children,
                `platforms.name`,
                `platforms.orgs`,
                `platforms.repos`,
                `platforms.users`
            FROM opensource.labels
            WHERE id IN {label_ids:Array(String)}
        """

        result = ClickHouseDB.query(sql, parameters={"label_ids": normalized_ids})

        label_info = {}
        for row in _get_result_rows(result):
            label_id = row[0]
            label_type = row[1]
            name = row[2]
            name_zh = row[3]
            children = row[4] or []
            platforms_names = row[5] or []
            platforms_orgs = row[6] or []
            platforms_repos = row[7] or []
            platforms_users = row[8] or []

            orgs_by_platform = {}
            repos_by_platform = {}
            users_by_platform = {}

            for i, platform_name in enumerate(platforms_names):
                if i < len(platforms_orgs):
                    orgs_by_platform[platform_name] = platforms_orgs[i] or []
                if i < len(platforms_repos):
                    repos_by_platform[platform_name] = platforms_repos[i] or []
                if i < len(platforms_users):
                    users_by_platform[platform_name] = platforms_users[i] or []

            label_info[label_id] = {
                "id": label_id,
                "type": label_type,
                "name": name,
                "name_zh": name_zh,
                "children": list(children),
                "platforms": list(platforms_names),
                "orgs": orgs_by_platform,
                "repos": repos_by_platform,
                "users": users_by_platform,
            }

        logger.info(
            "查询 %s 个标签实体, 返回 %s 个结果",
            len(normalized_ids),
            len(label_info),
        )
        return label_info
    except Exception as e:
        logger.error("查询标签实体失败 (标签数: %s): %s", len(label_ids), e)
        return {}
