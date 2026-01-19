"""标签运算逻辑."""

from .models import Tag


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
            项目标识集合 {"alibaba/dubbo", "apache/kafka", ...}

        """
        if not tag_slugs:
            return set()

        # 获取每个标签对应的项目集合
        project_sets = []
        for slug in tag_slugs:
            try:
                tag = Tag.objects.get(slug=slug)
                projects = TagOperation._get_projects_for_tag(tag)
                project_sets.append(projects)
            except Tag.DoesNotExist:
                # 如果标签不存在，使用空集合
                project_sets.append(set())

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
    def _get_projects_for_tag(tag: Tag) -> set[str]:
        """
        获取标签对应的项目列表.

        对于组织标签, 返回该组织下的所有项目(fake数据)
        对于仓库标签, 直接返回该仓库
        """
        if tag.tag_type == "org":
            # 组织标签: 返回该组织下的所有项目(fake数据)
            # Future enhancement: fetch real project list from OpenDigger or cache.
            org_name = tag.entity_identifier
            return {
                f"{org_name}/project1",
                f"{org_name}/project2",
                f"{org_name}/project3",
            }
        elif tag.tag_type == "repo":
            # 仓库标签：直接返回该仓库
            return {tag.entity_identifier}
        else:
            # 通用标签或用户标签：返回空集合
            return set()

    @staticmethod
    def evaluate_user_tags(tag_slugs: list[str], operation: str = "AND") -> set[str]:
        """
        计算用户标签运算, 返回 GitHub login 集合.

        Args:
            tag_slugs: 标签 slug 列表
            operation: 运算符 (AND/OR/NOT/XOR)

        Returns:
            GitHub login 集合 {"alice", "bob", ...}

        """
        if not tag_slugs:
            return set()

        # 获取每个标签对应的用户集合
        user_sets = []
        for slug in tag_slugs:
            try:
                tag = Tag.objects.get(slug=slug)
                users = TagOperation._get_users_for_tag(tag)
                user_sets.append(users)
            except Tag.DoesNotExist:
                user_sets.append(set())

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
    def _get_users_for_tag(tag: Tag) -> set[str]:
        """
        获取标签对应的用户列表.

        对于用户标签, 返回标记的用户列表(fake数据)
        """
        if tag.tag_type == "user":
            # 用户标签: 返回该标签标记的用户(fake数据)
            # Future enhancement: fetch real users from database or cache.
            return {"user1", "user2", "user3"}
        else:
            return set()
