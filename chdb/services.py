"""ClickHouse 服务层: 标签搜索和用户信息查询."""

import json
import logging
from typing import Any

from chdb.clickhousedb import ClickHouseDB

logger = logging.getLogger(__name__)


OPENRANK_KEYS = ("openrank", "open_rank", "openRank")

SEARCH_TAGS_SQL = """
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

LABEL_USERS_SQL = """
    SELECT
        id,
        `platforms.name`,
        `platforms.users`
    FROM opensource.labels
    WHERE id IN {label_ids:Array(String)}
"""

LABEL_ENTITIES_SQL = """
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

CONTRIBUTIONS_SQL = """
    SELECT
        actor_id,
        argMax(actor_login, created_at) AS login,
        SUM(openrank) AS or,
        groupArray((repo_name, openrank, yyyymm)) AS details
    FROM normalized_community_openrank
    WHERE (
        (platform, repo_id) IN (
            SELECT platform, entity_id
            FROM flatten_labels
            WHERE entity_type = 'Repo'
              AND id IN {label_ids:Array(String)}
        )
        OR (platform, org_id) IN (
            SELECT platform, entity_id
            FROM flatten_labels
            WHERE entity_type = 'Org'
              AND id IN {label_ids:Array(String)}
        )
    )
      AND toYear(created_at) = {year:UInt16}
    GROUP BY actor_id
    ORDER BY or DESC
    LIMIT 30
"""


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


def _normalize_keyword(keyword: str) -> str:
    """清理搜索关键词."""
    return (keyword or "").strip()


def _parse_openrank_payload(payload: dict[str, Any]) -> float | None:
    """从 JSON payload 中提取 OpenRank."""
    for key in OPENRANK_KEYS:
        if key in payload:
            try:
                return float(payload[key])
            except (TypeError, ValueError):
                return None
    return None


def _extract_openrank(raw_data: Any) -> float | None:
    """从 labels.data 中尝试解析 OpenRank."""
    if isinstance(raw_data, (int, float)):
        return float(raw_data)

    if not isinstance(raw_data, str):
        return None

    try:
        payload = json.loads(raw_data)
    except (TypeError, ValueError):
        return None

    if isinstance(payload, dict):
        return _parse_openrank_payload(payload)

    return None


def _parse_platforms(raw_platforms: Any) -> list[str]:
    """清理平台名称列表."""
    if not raw_platforms:
        return []
    return [platform for platform in raw_platforms if platform]


def _format_platform_display(platforms: list[str]) -> tuple[str, str]:
    """生成平台显示名称."""
    if not platforms:
        return "unknown", "Unknown"

    platform = "/".join(platforms)
    display = "/".join([name.capitalize() for name in platforms])
    return platform, display


def _choose_display_name(name: str, name_zh: str, fallback: str) -> str:
    """返回优先显示名称."""
    return name_zh or name or fallback


def _format_search_tag_row(row: Any) -> dict[str, Any]:
    """格式化搜索标签结果行."""
    tag_id = row[0]
    tag_type = row[1]
    name = row[2] or ""
    name_zh = row[3] or ""
    platforms = _parse_platforms(row[4] if len(row) > 4 else [])
    raw_data = row[5] if len(row) > 5 else None
    openrank = _extract_openrank(raw_data)

    display_name = _choose_display_name(name, name_zh, tag_id)
    platform, platform_display = _format_platform_display(platforms)

    return {
        "id": tag_id,
        "type": tag_type,
        "platform": platform,
        "platforms": platforms,
        "name": display_name,
        "openrank": openrank,
        "name_display": f"{display_name} ({platform_display})",
        "slug": tag_id,
    }


def _prepare_label_ids(label_ids: list[Any]) -> list[str]:
    """标准化标签 ID 列表并记录异常情况."""
    if not label_ids:
        logger.warning("空标签列表查询被拒绝")
        return []

    normalized_ids = _normalize_label_ids(label_ids)
    if not normalized_ids:
        logger.warning("标签列表去空后为空, 跳过查询")
    return normalized_ids


def _build_users_by_platform(
    platform_names: list[str], platform_users: list[Any]
) -> dict[str, Any]:
    """构建平台到用户列表的映射."""
    users_by_platform = {}
    for platform_name, users in zip(platform_names, platform_users, strict=False):
        users_by_platform[platform_name] = users
    return users_by_platform


def _map_platform_values(
    platform_names: list[str], platform_values: list[Any]
) -> dict[str, list[Any]]:
    """构建平台到数据列表的映射."""
    mapped = {}
    for platform_name, values in zip(platform_names, platform_values, strict=False):
        mapped[platform_name] = values or []
    return mapped


def _build_label_entity(row: Any) -> tuple[str, dict[str, Any]]:
    """解析标签实体行."""
    label_id = row[0]
    label_type = row[1]
    name = row[2]
    name_zh = row[3]
    children = row[4] or []
    platforms_names = row[5] or []
    platforms_orgs = row[6] or []
    platforms_repos = row[7] or []
    platforms_users = row[8] or []

    payload = {
        "id": label_id,
        "type": label_type,
        "name": name,
        "name_zh": name_zh,
        "children": list(children),
        "platforms": list(platforms_names),
        "orgs": _map_platform_values(platforms_names, platforms_orgs),
        "repos": _map_platform_values(platforms_names, platforms_repos),
        "users": _map_platform_values(platforms_names, platforms_users),
    }
    return label_id, payload


def _collect_repo_ids(label_entities: dict[str, dict[str, Any]]) -> list[int]:
    """收集 GitHub 仓库 ID."""
    repo_ids: list[int] = []
    for label_info in label_entities.values():
        repos_by_platform = label_info.get("repos", {})
        for platform, repos in repos_by_platform.items():
            if platform and platform.lower() == "github":
                repo_ids.extend(repos)
    return repo_ids


def _collect_user_ids(label_entities: dict[str, dict[str, Any]]) -> list[int]:
    """收集 GitHub 用户 ID."""
    user_ids: list[int] = []
    for label_info in label_entities.values():
        users_by_platform = label_info.get("users", {})
        for platform, users in users_by_platform.items():
            if platform and platform.lower() == "github":
                user_ids.extend(users)
    return user_ids


def _parse_contribution_rows(rows: list[Any]) -> list[dict[str, Any]]:
    """解析贡献度查询结果."""
    contributions = []
    for row in rows:
        platform = "GitHub"
        details = None

        if len(row) >= 4 and isinstance(row[0], str) and isinstance(row[2], str):
            platform = row[0]
            actor_id = row[1]
            actor_login = row[2]
            contribution_score = row[3]
            if len(row) > 4:
                details = row[4]
        else:
            actor_id = row[0]
            actor_login = row[1]
            contribution_score = row[2]
            if len(row) > 3:
                details = row[3]

        payload = {
            "platform": platform,
            "actor_id": str(actor_id),
            "actor_login": actor_login,
            "contribution_score": float(contribution_score),
        }
        if details is not None:
            payload["details"] = details

        contributions.append(payload)

    return contributions


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
    keyword = _normalize_keyword(keyword)
    if not keyword:
        logger.warning("空关键词搜索被拒绝")
        return []

    try:
        result = ClickHouseDB.query(
            SEARCH_TAGS_SQL, parameters={"keyword": f"%{keyword}%", "limit": limit}
        )
        tags = [_format_search_tag_row(row) for row in _get_result_rows(result)]
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
    normalized_ids = _prepare_label_ids(label_ids)
    if not normalized_ids:
        return {}

    try:
        result = ClickHouseDB.query(
            LABEL_USERS_SQL, parameters={"label_ids": normalized_ids}
        )
        label_info = {}
        for row in _get_result_rows(result):
            label_id = row[0]
            platforms_names = row[1] or []
            platforms_users = row[2] or []
            users_by_platform = _build_users_by_platform(
                platforms_names, platforms_users
            )

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
    normalized_ids = _prepare_label_ids(label_ids)
    if not normalized_ids:
        return {}

    try:
        result = ClickHouseDB.query(
            LABEL_ENTITIES_SQL, parameters={"label_ids": normalized_ids}
        )

        label_info = {}
        for row in _get_result_rows(result):
            label_id, payload = _build_label_entity(row)
            label_info[label_id] = payload

        logger.info(
            "查询 %s 个标签实体, 返回 %s 个结果",
            len(normalized_ids),
            len(label_info),
        )
        return label_info
    except Exception as e:
        logger.error("查询标签实体失败 (标签数: %s): %s", len(label_ids), e)
        return {}


def query_contributions(
    label_ids: list[str], start_month: int, end_month: int
) -> list[dict[str, Any]]:
    """
    查询标签关联项目的贡献度数据.

    Args:
    label_ids: 标签 ID 列表 (来自 opensource.labels.id)
    start_month: 起始月份 (格式: 202401)
    end_month: 结束月份 (格式: 202412)

    Returns:
        贡献者列表, 每个贡献者包含:
        - platform: 平台 (GitHub/Gitee 等)
        - actor_id: 贡献者平台 ID
        - actor_login: 贡献者登录名
        - contribution_score: 贡献度分数 (sum of openrank)
        - details: 贡献度明细 (repo_name, openrank, yyyymm)

    """
    normalized_ids = _prepare_label_ids(label_ids)
    if not normalized_ids:
        return []

    start_year = start_month // 100
    end_year = end_month // 100
    year = end_year
    if start_year != end_year:
        logger.warning(
            "起止月份跨年: %s - %s, 使用结束年份 %s 查询",
            start_month,
            end_month,
            end_year,
        )

    try:
        result = ClickHouseDB.query(
            CONTRIBUTIONS_SQL,
            parameters={
                "label_ids": normalized_ids,
                "year": year,
            },
        )
        logger.info("查询贡献度数据: %s 个标签, 年份 %s", len(normalized_ids), year)

        contributions = _parse_contribution_rows(_get_result_rows(result))
        logger.info("查询到 %s 个贡献者", len(contributions))
        return contributions

    except Exception as e:
        logger.error("查询贡献度数据失败: %s", e)
        return []
