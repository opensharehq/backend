"""测试 points app 的信号处理器."""

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase

from points.models import PointSource, Tag

User = get_user_model()


class CreateDefaultPointSourceSignalTests(TransactionTestCase):
    """测试用户创建时自动创建默认积分池的信号处理器."""

    def setUp(self):
        """设置测试环境."""
        # 确保 default 标签存在
        Tag.objects.get_or_create(
            slug="default",
            defaults={
                "name": "默认",
                "description": "用户默认积分池，支持充值和提现",
                "is_default": True,
                "withdrawable": True,
                "allow_recharge": True,
            },
        )

    def test_create_default_point_source_for_new_user(self):
        """测试新用户创建时自动创建默认积分池."""
        # 创建新用户
        user = User.objects.create_user(username="testuser", password="testpass123")

        # 验证自动创建了积分池
        point_sources = PointSource.objects.filter(user=user)
        self.assertEqual(point_sources.count(), 1)

        # 验证积分池的属性
        point_source = point_sources.first()
        self.assertEqual(point_source.initial_points, 0)
        self.assertEqual(point_source.remaining_points, 0)
        self.assertTrue(point_source.allow_recharge)
        self.assertEqual(point_source.notes, "用户注册时自动创建的默认积分池")

        # 验证关联了 default 标签
        self.assertTrue(point_source.tags.filter(slug="default").exists())

        # 验证积分池是可充值和可提现的
        self.assertTrue(point_source.is_rechargeable)
        self.assertTrue(point_source.is_withdrawable)

    def test_no_default_point_source_when_tag_missing(self):
        """测试当 default 标签不存在时不会创建默认积分池."""
        # 删除 default 标签
        Tag.objects.filter(slug="default").delete()

        # 创建新用户
        user = User.objects.create_user(username="testuser2", password="testpass123")

        # 验证没有创建积分池
        point_sources = PointSource.objects.filter(user=user)
        self.assertEqual(point_sources.count(), 0)

    def test_existing_user_update_does_not_create_point_source(self):
        """测试更新现有用户不会创建新的积分池."""
        # 创建用户
        user = User.objects.create_user(username="testuser3", password="testpass123")

        # 记录当前积分池数量
        initial_count = PointSource.objects.filter(user=user).count()

        # 更新用户信息
        user.email = "newemail@example.com"
        user.save()

        # 验证积分池数量没有变化
        final_count = PointSource.objects.filter(user=user).count()
        self.assertEqual(initial_count, final_count)


class DefaultTagMigrationTests(TestCase):
    """测试 default 标签的创建."""

    def test_default_tag_exists(self):
        """测试 default 标签已经通过 migration 创建."""
        # 尝试获取 default 标签
        default_tag = Tag.objects.filter(slug="default").first()

        # 验证标签存在
        self.assertIsNotNone(default_tag)

        # 验证标签属性
        self.assertEqual(default_tag.name, "默认")
        self.assertEqual(default_tag.slug, "default")
        self.assertTrue(default_tag.is_default)
        self.assertTrue(default_tag.withdrawable)
        self.assertTrue(default_tag.allow_recharge)
        self.assertIn("充值", default_tag.description)
        self.assertIn("提现", default_tag.description)

    def test_default_tag_uniqueness(self):
        """测试 default 标签的唯一性."""
        # 获取所有 slug 为 default 的标签
        default_tags = Tag.objects.filter(slug="default")

        # 验证只有一个
        self.assertEqual(default_tags.count(), 1)
