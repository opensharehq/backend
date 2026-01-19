"""Tests for tag operations."""

from django.test import TestCase

from points.models import Tag, TagType
from points.tag_operations import TagOperation


class TagOperationTests(TestCase):
    """Tests for tag operations."""

    def setUp(self):
        """Set up test data."""
        # 创建组织标签
        self.tag_alibaba = Tag.objects.create(
            name="阿里巴巴",
            slug="alibaba-org",
            tag_type=TagType.ORG,
            entity_identifier="alibaba",
            is_official=True,
        )

        self.tag_apache = Tag.objects.create(
            name="Apache",
            slug="apache-org",
            tag_type=TagType.ORG,
            entity_identifier="apache",
            is_official=True,
        )

        # 创建仓库标签
        self.tag_dubbo = Tag.objects.create(
            name="Dubbo",
            slug="dubbo-repo",
            tag_type=TagType.REPO,
            entity_identifier="alibaba/dubbo",
            is_official=True,
        )

        self.tag_kafka = Tag.objects.create(
            name="Kafka",
            slug="kafka-repo",
            tag_type=TagType.REPO,
            entity_identifier="apache/kafka",
            is_official=True,
        )

    def test_evaluate_single_org_tag(self):
        """Test evaluating a single org tag."""
        result = TagOperation.evaluate_project_tags(["alibaba-org"])
        self.assertTrue(len(result) > 0)
        # 应该返回 alibaba 组织的项目
        for project in result:
            self.assertTrue(project.startswith("alibaba/"))

    def test_evaluate_single_repo_tag(self):
        """Test evaluating a single repo tag."""
        result = TagOperation.evaluate_project_tags(["dubbo-repo"])
        self.assertEqual(result, {"alibaba/dubbo"})

    def test_evaluate_and_operation(self):
        """Test AND operation on tags."""
        # 由于 fake 实现，alibaba-org 会返回 {alibaba/project1, alibaba/project2, alibaba/project3}
        # dubbo-repo 会返回 {alibaba/dubbo}
        # AND 运算结果应该是空集（因为它们没有交集）
        result = TagOperation.evaluate_project_tags(
            ["alibaba-org", "dubbo-repo"], operation=TagOperation.AND
        )
        # Fake 实现中没有交集
        self.assertEqual(len(result), 0)

    def test_evaluate_or_operation(self):
        """Test OR operation on tags."""
        result = TagOperation.evaluate_project_tags(
            ["dubbo-repo", "kafka-repo"], operation=TagOperation.OR
        )
        self.assertEqual(result, {"alibaba/dubbo", "apache/kafka"})

    def test_evaluate_not_operation(self):
        """Test NOT operation on tags."""
        result = TagOperation.evaluate_project_tags(
            ["alibaba-org", "dubbo-repo"], operation=TagOperation.NOT
        )
        # alibaba-org 的项目减去 dubbo-repo
        expected = {"alibaba/project1", "alibaba/project2", "alibaba/project3"}
        self.assertEqual(result, expected)

    def test_evaluate_empty_tags(self):
        """Test evaluating empty tag list."""
        result = TagOperation.evaluate_project_tags([])
        self.assertEqual(result, set())

    def test_evaluate_nonexistent_tag(self):
        """Test evaluating non-existent tag."""
        result = TagOperation.evaluate_project_tags(["nonexistent-tag"])
        self.assertEqual(result, set())

    def test_evaluate_user_tags(self):
        """Test evaluating user tags."""
        # 创建用户标签
        Tag.objects.create(
            name="核心贡献者",
            slug="core-contributors",
            tag_type=TagType.USER,
            is_official=True,
        )

        result = TagOperation.evaluate_user_tags(["core-contributors"])
        # Fake 实现返回固定的用户集合
        self.assertTrue(len(result) > 0)
