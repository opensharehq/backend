"""ClickHouse 服务层: 标签搜索和用户信息查询."""

import json
import logging
from datetime import date, timedelta
from typing import Any

from django.core.cache import cache, caches

from chdb.clickhousedb import ClickHouseDB

logger = logging.getLogger(__name__)


OPENRANK_KEYS = ("openrank", "open_rank", "openRank")

# ClickHouse 搜索接口 Redis 缓存策略：
# - key 以小写、去空后的 query 作为主要变量，避免大小写与多余空格导致 key 分裂
# - 数据来自外部同步作业，更新频率低，选择 TTL 过期策略而非总条数限制
# - 仅缓存非空结果，避免 ClickHouse 短暂故障期间把空列表包裹进缓存
# - 使用独立的 ``search_results`` cache alias，避开本地 ``default`` 为 DummyCache
#   （防止全站 cache middleware 在 DEBUG 下缓存 GET 响应）导致应用层缓存失效
SEARCH_CACHE_TTL_SECONDS = 1800  # 30 分钟
SEARCH_TAGS_CACHE_PREFIX = "chdb:search_tags"
SEARCH_NAME_INFO_CACHE_PREFIX = "chdb:search_name_info"
SEARCH_CACHE_ALIAS = "search_results"


def _get_search_cache():
    """
    返回专用的搜索缓存后端, 避开本地 default DummyCache.

    如果运行环境未配置 ``search_results`` alias (如部分测试下的
    override_settings), 则回退到默认 ``cache``.
    """
    try:
        return caches[SEARCH_CACHE_ALIAS]
    except Exception:  # pragma: no cover - 防御式分支
        return cache


def _build_search_cache_key(prefix: str, keyword: str, *parts: Any) -> str:
    """构造搜索缓存 key, keyword 统一 lower() 归一化."""
    normalized = keyword.strip().lower()
    suffix = ":".join(str(part) for part in parts)
    if suffix:
        return f"{prefix}:{normalized}:{suffix}"
    return f"{prefix}:{normalized}"


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

SEARCH_NAME_INFO_SQL = """
    (SELECT lower(platform) AS platform, toString(id) AS id, name, name AS name_zh, type
    FROM name_info
    WHERE name ILIKE {keyword:String}
    ORDER BY openrank DESC
    LIMIT 5 BY platform, type)
    UNION ALL
    (SELECT l.type AS platform, id, name, name_zh, 'Label' AS type
    FROM labels l WHERE l.type IN ('Company', 'Division-0', 'Foundation', 'Project', 'Agency-0', 'University-0', 'Institution-0', 'Community')
    AND (name ILIKE {keyword:String} OR name_zh ILIKE {keyword:String}))
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
    """
    Parse contribution query result rows.

    Expected column order: platform, actor_id, actor_login,
    contribution_score, details, top_repos.
    """
    contributions = []
    for row in rows:
        platform = row[0] or "GitHub"
        actor_id = row[1]
        actor_login = row[2]
        contribution_score = row[3]
        details = row[4]
        top_repos_raw = row[5] if len(row) > 5 else None

        payload = {
            "platform": platform,
            "actor_id": str(actor_id),
            "actor_login": actor_login,
            "contribution_score": float(contribution_score),
        }
        if details is not None:
            payload["details"] = details

        # Parse top_repos: array of tuples (repo_name, openrank)
        if top_repos_raw is not None:
            payload["top_repos"] = [
                {
                    "platform": platform,
                    "repo_name": item[0],
                    "openrank": round(float(item[1]), 2),
                }
                for item in top_repos_raw
            ]

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

    cache_key = _build_search_cache_key(SEARCH_TAGS_CACHE_PREFIX, keyword, limit)
    search_cache = _get_search_cache()
    cached = search_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        result = ClickHouseDB.query(
            SEARCH_TAGS_SQL, parameters={"keyword": f"%{keyword}%", "limit": limit}
        )
        tags = [_format_search_tag_row(row) for row in _get_result_rows(result)]
        logger.info("搜索关键词 '%s' 返回 %s 个标签", keyword, len(tags))
        if tags:
            search_cache.set(cache_key, tags, SEARCH_CACHE_TTL_SECONDS)
        return tags

    except Exception as e:
        logger.error("搜索标签失败 (关键词: %s): %s", keyword, e)
        return []


def search_name_info(keyword: str) -> list[dict[str, Any]]:
    """
    Search repositories and developers in the name_info table.

    Args:
        keyword: Search keyword using case-insensitive containment matching.

    Returns:
        Result list where each item includes platform, id, name, and type.

    """
    keyword = _normalize_keyword(keyword)
    if not keyword:
        return []

    cache_key = _build_search_cache_key(SEARCH_NAME_INFO_CACHE_PREFIX, keyword)
    search_cache = _get_search_cache()
    cached = search_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        result = ClickHouseDB.query(
            SEARCH_NAME_INFO_SQL,
            parameters={"keyword": f"%{keyword}%"},
        )
        rows = _get_result_rows(result)
        items: list[dict[str, Any]] = []
        for row in rows:
            raw_id = row[1]
            # name_info.id is numeric (toString'ed in SQL), flatten_labels.id
            # carries the canonical ':companies/...' form. Coerce numeric
            # strings back to int so existing repo/user consumers stay
            # backward-compatible while label rows keep the string id.
            item_id: Any = raw_id
            if isinstance(raw_id, str) and raw_id.isdigit():
                item_id = int(raw_id)
            items.append(
                {
                    "platform": row[0],
                    "id": item_id,
                    "name": row[2],
                    "name_zh": row[3],
                    "type": row[4],
                }
            )
        if items:
            search_cache.set(cache_key, items, SEARCH_CACHE_TTL_SECONDS)
        return items
    except Exception as e:
        logger.error("搜索name_info失败 (关键词: %s): %s", keyword, e)
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


def _build_tag_expression_sql(tag_ids: list[str], operators: list[str]) -> str:
    """
    构建标签运算 WHERE 子句.

    左到右累积拼接:
    tag_ids=['A','B','C'], operators=['OR','NOT']
    → ((condition_A OR condition_B) AND NOT condition_C)
    """

    def tag_condition(tag_id: str) -> str:
        escaped = tag_id.replace("'", "\\'")
        return (
            f"((platform, repo_id) IN "  # noqa: S608
            f"(SELECT platform, entity_id FROM flatten_labels "
            f"WHERE entity_type='Repo' AND id = '{escaped}') "
            f"OR (platform, org_id) IN "
            f"(SELECT platform, entity_id FROM flatten_labels "
            f"WHERE entity_type='Org' AND id = '{escaped}'))"
        )

    result = tag_condition(tag_ids[0])
    for i, op in enumerate(operators):
        next_cond = tag_condition(tag_ids[i + 1])
        if op == "OR":
            result = f"({result} OR {next_cond})"
        elif op == "AND":
            result = f"({result} AND {next_cond})"
        elif op == "NOT":
            result = f"({result} AND NOT {next_cond})"
    return result


def query_contributions_with_operators(
    tag_ids: list[str],
    operators: list[str],
    start_month: int,
    end_month: int,
) -> list[dict[str, Any]]:
    """
    使用标签运算符查询贡献度数据.

    通过动态构建 SQL WHERE 子句实现标签间的集合运算:
    - AND → 交集
    - OR  → 并集
    - NOT → 差集 (AND NOT)

    Args:
        tag_ids: 标签 ID 列表
        operators: 运算符列表, 长度为 len(tag_ids) - 1
        start_month: 起始月份 (格式: 202401)
        end_month: 结束月份 (格式: 202412)

    Returns:
        贡献者列表, 每个贡献者包含 platform, actor_id, actor_login,
        contribution_score, details, top_repos

    """
    if not tag_ids:
        return []

    where_clause = _build_tag_expression_sql(tag_ids, operators)
    sql = f"""
        SELECT
            platform,
            actor_id,
            argMax(actor_login, created_at) AS login,
            SUM(openrank) AS total_or,
            groupArray((repo_name, openrank, yyyymm)) AS details,
            arraySlice(
                arrayReverseSort(
                    x -> x.2,
                    arrayZip(
                        mapKeys(sumMap(map(repo_name, toFloat64(openrank)))),
                        mapValues(sumMap(map(repo_name, toFloat64(openrank))))
                    )
                ),
                1, 3
            ) AS top_repos
        FROM normalized_community_openrank
        WHERE {where_clause}
          AND toYYYYMM(created_at) >= {{start_month:UInt32}}
          AND toYYYYMM(created_at) <= {{end_month:UInt32}}
          AND (platform, actor_id) NOT IN (SELECT platform, entity_id FROM flatten_labels WHERE entity_type='User' AND id=':bot')
        GROUP BY platform, actor_id
        ORDER BY total_or DESC
        LIMIT 300000
    """  # noqa: S608

    try:
        result = ClickHouseDB.query(
            sql,
            parameters={
                "start_month": start_month,
                "end_month": end_month,
            },
        )
        logger.info(
            "标签运算查询贡献度: %s 个标签, 运算符 %s, 月份 %s-%s",
            len(tag_ids),
            operators,
            start_month,
            end_month,
        )
        contributions = _parse_contribution_rows(_get_result_rows(result))
        logger.info("查询到 %s 个贡献者", len(contributions))
        return contributions
    except Exception as e:
        logger.error("标签运算查询贡献度失败: %s", e)
        return []


# ---------------------------------------------------------------------------
# Developer outreach queries
# ---------------------------------------------------------------------------

LANGUAGE_LIST_CACHE_TTL = 28800  # 8 hours
LANGUAGE_LIST_CACHE_KEY = "outreach:languages"

# TODO(team): Confirm the actual table name; it might be  # noqa: TD003, FIX002
# `opensource.gh_repo_info` or `default.repo_info` depending on the schema.
AVAILABLE_LANGUAGES_SQL = """
    SELECT DISTINCT language
    FROM opensource.gh_repo_info
    WHERE language IS NOT NULL AND language != ''
    ORDER BY language
"""


def get_available_languages() -> list[str]:
    """
    Query all available programming languages from ClickHouse repo_info table.

    Results are cached for 8 hours.

    Returns:
        A sorted list of distinct programming language names.

    """
    search_cache = _get_search_cache()
    cached = search_cache.get(LANGUAGE_LIST_CACHE_KEY)
    if cached is not None:
        return cached

    try:
        result = ClickHouseDB.query(AVAILABLE_LANGUAGES_SQL)
        rows = _get_result_rows(result)
        languages = sorted([row[0] for row in rows if row[0]])
        logger.info("Fetched %d available languages from ClickHouse", len(languages))
        if languages:
            search_cache.set(
                LANGUAGE_LIST_CACHE_KEY, languages, LANGUAGE_LIST_CACHE_TTL
            )
        return languages
    except Exception as e:
        logger.error("Failed to fetch available languages: %s", e)
        return []


def _compute_outreach_date_range() -> tuple[int, int]:
    """
    Compute start_month and end_month for the last 24 months.

    Returns:
        (start_month, end_month) as integers in YYYYMM format.

    """
    today = date.today()
    end_month = today.year * 100 + today.month
    # Go back 24 months
    start_date = today - timedelta(days=730)  # ~24 months
    start_month = start_date.year * 100 + start_date.month
    return start_month, end_month


def query_developers_for_outreach(
    tag_ids: list[str],
    languages: list[str] | None = None,
    countries: list[str] | None = None,
    regions: list[str] | None = None,
    top_n: int | None = None,
) -> list[dict]:
    """
    Query developers matching the given criteria for talent outreach.

    Steps:
        1. Expand tag_ids to get associated repos (via flatten_labels table)
        2. (Optional) Filter repos by programming languages (via repo_info table)
        3. Query contributors of these repos (using last 2 years of OpenRank data)
        4. (Optional) Filter by countries/regions (if data available)
        5. Sort by global OpenRank contribution score (descending, last 2 years cumulative)
        6. (Optional) Apply top_n limit

    Args:
        tag_ids: List of label IDs to expand into repos.
        languages: Optional list of programming languages to filter repos.
        countries: Optional list of countries to filter developers.
        regions: Optional list of regions to filter developers.
        top_n: Optional limit on number of results returned.

    Returns:
        List of dicts with keys: platform, actor_id, actor_login, openrank_score.

    """
    if not tag_ids:
        return []

    normalized_ids = _normalize_label_ids(tag_ids)
    if not normalized_ids:
        return []

    start_month, end_month = _compute_outreach_date_range()

    # Build repo subquery from flatten_labels
    tag_placeholders = ", ".join(
        f"'{tid.replace(chr(39), '')}'" for tid in normalized_ids
    )
    repo_subquery = (
        f"SELECT platform, entity_id FROM flatten_labels "  # noqa: S608
        f"WHERE entity_type = 'Repo' AND id IN ({tag_placeholders})"
    )

    # Optional: filter by programming languages via repo_info JOIN
    language_filter = ""
    if languages:
        escaped_langs = ", ".join(
            f"'{lang.replace(chr(39), '')}'" for lang in languages
        )
        # TODO(team): Confirm gh_repo_info table name and that it has  # noqa: TD003, FIX002
        # columns (platform, repo_id, language) matching normalized_community_openrank.
        language_filter = (
            f"AND (platform, repo_id) IN ("  # noqa: S608
            f"SELECT platform, repo_id FROM opensource.gh_repo_info "
            f"WHERE language IN ({escaped_langs})"
            f")"
        )

    # TODO(team): countries/regions filtering is not yet supported because  # noqa: TD003, FIX002
    # the developer location table/field is not confirmed in the current schema.
    # When available, add a JOIN or subquery filter here.
    if countries or regions:
        logger.info(
            "countries/regions filter requested but not yet implemented; ignoring. "
            "countries=%s, regions=%s",
            countries,
            regions,
        )

    limit_clause = f"LIMIT {int(top_n)}" if top_n and int(top_n) > 0 else ""

    sql = f"""
        SELECT
            platform,
            actor_id,
            argMax(actor_login, created_at) AS login,
            SUM(openrank) AS openrank_score
        FROM normalized_community_openrank
        WHERE (platform, repo_id) IN ({repo_subquery})
          {language_filter}
          AND toYYYYMM(created_at) >= {{start_month:UInt32}}
          AND toYYYYMM(created_at) <= {{end_month:UInt32}}
          AND (platform, actor_id) NOT IN (
              SELECT platform, entity_id FROM flatten_labels
              WHERE entity_type='User' AND id=':bot'
          )
        GROUP BY platform, actor_id
        ORDER BY openrank_score DESC
        {limit_clause}
    """  # noqa: S608

    try:
        result = ClickHouseDB.query(
            sql,
            parameters={
                "start_month": start_month,
                "end_month": end_month,
            },
        )
        rows = _get_result_rows(result)
        developers = [
            {
                "platform": row[0] or "GitHub",
                "actor_id": str(row[1]),
                "actor_login": row[2],
                "openrank_score": float(row[3]),
            }
            for row in rows
        ]
        logger.info(
            "Outreach query: %d tag(s), languages=%s, returned %d developers",
            len(normalized_ids),
            languages,
            len(developers),
        )
        return developers
    except Exception as e:
        logger.error("Failed to query developers for outreach: %s", e)
        return []
