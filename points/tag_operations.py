"""标签运算逻辑."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class TagOperation:
    """标签运算逻辑."""

    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    XOR = "XOR"

    @staticmethod
    def evaluate_project_tags(tag_slugs: list[str], operation: str = "AND") -> set[str]:
        """
        计算项目标签运算, 返回项目标识集合.

        Args:
            tag_slugs: 标签 slug 列表
            operation: 运算符 (AND/OR/NOT/XOR)

        Returns:
            项目标识集合 {"repo:github:123", "org:gitee:456", ...}

        """
        normalized_slugs = TagOperation._normalize_tag_ids(tag_slugs)
        if not normalized_slugs:
            return set()

        label_info = TagOperation._fetch_label_entities(normalized_slugs)

        # 获取每个标签对应的项目集合
        project_sets = []
        for slug in normalized_slugs:
            label = label_info.get(slug)
            if not label:
                project_sets.append(set())
                continue
            projects = TagOperation._get_projects_for_label(label)
            project_sets.append(projects)

        if not project_sets:
            return set()

        # 执行集合运算
        result = project_sets[0]
        for i in range(1, len(project_sets)):
            if operation == TagOperation.AND:
                result = result & project_sets[i]
            elif operation == TagOperation.OR:
                result = result | project_sets[i]
            elif operation == TagOperation.NOT:
                result = result - project_sets[i]
            elif operation == TagOperation.XOR:
                result = result ^ project_sets[i]

        return result

    @staticmethod
    def _get_projects_for_label(label: dict[str, Any]) -> set[str]:
        """从 opensource.labels 信息提取项目标识集合."""
        projects: set[str] = set()
        repos_by_platform = label.get("repos", {}) or {}
        orgs_by_platform = label.get("orgs", {}) or {}
        children = label.get("children") or []

        for platform, repo_ids in repos_by_platform.items():
            for repo_id in repo_ids:
                projects.add(f"repo:{platform}:{repo_id}")

        if not projects:
            for platform, org_ids in orgs_by_platform.items():
                for org_id in org_ids:
                    projects.add(f"org:{platform}:{org_id}")

        if not projects and children:
            projects.update({str(child) for child in children if child})

        if not projects:
            name = label.get("name") or label.get("name_zh") or label.get("id")
            if name:
                projects.add(str(name))

        return projects

    @staticmethod
    def evaluate_user_tags(tag_slugs: list[str], operation: str = "AND") -> set[str]:
        """
        计算用户标签运算, 返回 GitHub user id 集合.

        Args:
            tag_slugs: 标签 slug 列表
            operation: 运算符 (AND/OR/NOT/XOR)

        Returns:
            GitHub user id 集合 {"123", "456", ...}

        """
        normalized_slugs = TagOperation._normalize_tag_ids(tag_slugs)
        if not normalized_slugs:
            return set()

        label_info = TagOperation._fetch_label_entities(normalized_slugs)

        # 获取每个标签对应的用户集合
        user_sets = []
        for slug in normalized_slugs:
            label = label_info.get(slug)
            if not label:
                user_sets.append(set())
                continue
            users = TagOperation._get_users_for_label(label)
            user_sets.append(users)

        if not user_sets:
            return set()

        # 执行集合运算
        result = user_sets[0]
        for i in range(1, len(user_sets)):
            if operation == TagOperation.AND:
                result = result & user_sets[i]
            elif operation == TagOperation.OR:
                result = result | user_sets[i]
            elif operation == TagOperation.NOT:
                result = result - user_sets[i]
            elif operation == TagOperation.XOR:
                result = result ^ user_sets[i]

        return result

    @staticmethod
    def _get_users_for_label(label: dict[str, Any]) -> set[str]:
        """从 opensource.labels 信息提取用户集合."""
        users: set[str] = set()
        users_by_platform = label.get("users", {}) or {}
        for _, user_ids in users_by_platform.items():
            for user_id in user_ids:
                users.add(str(user_id))
        return users

    @staticmethod
    def _fetch_label_entities(tag_slugs: list[str]) -> dict[str, dict[str, Any]]:
        from chdb import services as chdb_services

        try:
            return chdb_services.get_label_entities(tag_slugs)
        except Exception as exc:
            logger.warning("读取标签实体失败: %s", exc)
            return {}

    @staticmethod
    def _normalize_tag_ids(tag_slugs: list[str]) -> list[str]:
        normalized = []
        for slug in tag_slugs:
            if slug is None:
                continue
            slug_str = str(slug).strip()
            if slug_str:
                normalized.append(slug_str)
        return normalized
