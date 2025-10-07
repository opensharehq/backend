"""Tests for points management commands."""

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from points.models import PointSource, PointTransaction, Tag


class GrantPointsCommandTests(TestCase):
    """Test cases for grant_points management command."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )

    def test_command_grants_points_by_username(self):
        """Test granting points using username."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            stdout=out,
        )

        self.assertIn("Successfully granted 100 points to testuser", out.getvalue())
        self.assertEqual(self.user.total_points, 100)

    def test_command_grants_points_by_email(self):
        """Test granting points using email."""
        out = StringIO()
        call_command(
            "grant_points",
            "test@example.com",
            "50",
            stdout=out,
        )

        self.assertIn("Successfully granted 50 points to testuser", out.getvalue())
        self.assertEqual(self.user.total_points, 50)

    def test_command_with_tag_name(self):
        """Test granting points with tag name."""
        Tag.objects.create(name="Premium", slug="premium")

        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--tags=Premium",
            stdout=out,
        )

        self.assertEqual(self.user.total_points, 100)
        source = PointSource.objects.first()
        self.assertTrue(source.tags.filter(name="Premium").exists())
        # Ensure no duplicate tag was created
        self.assertEqual(Tag.objects.filter(name="Premium").count(), 1)

    def test_command_with_tag_slug(self):
        """Test granting points with tag slug."""
        Tag.objects.create(name="Premium", slug="premium")

        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--tags=premium",
            stdout=out,
        )

        self.assertEqual(self.user.total_points, 100)
        source = PointSource.objects.first()
        self.assertTrue(source.tags.filter(slug="premium").exists())
        # Ensure no duplicate tag was created
        self.assertEqual(Tag.objects.filter(slug="premium").count(), 1)

    def test_command_with_multiple_tags(self):
        """Test granting points with multiple tags (mix of name and slug)."""
        Tag.objects.create(name="Tag One", slug="tag-one")
        Tag.objects.create(name="Tag Two", slug="tag-two")

        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--tags=tag-one,Tag Two",
            stdout=out,
        )

        self.assertEqual(self.user.total_points, 100)
        source = PointSource.objects.first()
        self.assertEqual(source.tags.count(), 2)

    def test_command_with_description(self):
        """Test granting points with custom description."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--description=Custom description",
            stdout=out,
        )

        transaction = PointTransaction.objects.first()
        self.assertEqual(transaction.description, "Custom description")

    def test_command_user_not_found(self):
        """Test granting points to non-existent user."""
        from django.core.management.base import CommandError

        with self.assertRaisesMessage(CommandError, "User not found"):
            call_command(
                "grant_points",
                "nonexistent",
                "100",
            )

    def test_command_invalid_points(self):
        """Test granting invalid points amount."""
        from django.core.management.base import CommandError

        with self.assertRaisesMessage(CommandError, "发放的积分必须是正整数"):
            call_command(
                "grant_points",
                "testuser",
                "0",
            )

    def test_command_negative_points(self):
        """Test granting negative points raises error."""
        from django.core.management.base import CommandError

        with self.assertRaisesMessage(CommandError, "发放的积分必须是正整数"):
            call_command(
                "grant_points",
                "testuser",
                "-50",
            )

    def test_command_with_short_form_description_flag(self):
        """Test using -d short form for description."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "75",
            "-d",
            "Short form description",
            stdout=out,
        )

        transaction = PointTransaction.objects.first()
        self.assertEqual(transaction.description, "Short form description")
        self.assertIn("Description: Short form description", out.getvalue())

    def test_command_with_short_form_tags_flag(self):
        """Test using -t short form for tags."""
        Tag.objects.create(name="bonus", slug="bonus")

        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "60",
            "-t",
            "bonus",
            stdout=out,
        )

        source = PointSource.objects.first()
        self.assertTrue(source.tags.filter(name="bonus").exists())
        self.assertIn("Tags: bonus", out.getvalue())

    def test_command_default_description(self):
        """Test that default description is '管理员发放' when not provided."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            stdout=out,
        )

        transaction = PointTransaction.objects.first()
        self.assertEqual(transaction.description, "管理员发放")
        self.assertIn("Description: 管理员发放", out.getvalue())

    def test_command_default_tags(self):
        """Test that default tag is '默认' when not provided."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            stdout=out,
        )

        source = PointSource.objects.first()
        self.assertTrue(source.tags.filter(name="默认").exists())
        self.assertIn("Tags: 默认", out.getvalue())

    def test_command_tags_with_whitespace(self):
        """Test that tags with extra whitespace are properly stripped."""
        Tag.objects.create(name="tag1", slug="tag1")
        Tag.objects.create(name="tag2", slug="tag2")

        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--tags= tag1 , tag2 ",
            stdout=out,
        )

        source = PointSource.objects.first()
        self.assertEqual(source.tags.count(), 2)
        self.assertTrue(source.tags.filter(name="tag1").exists())
        self.assertTrue(source.tags.filter(name="tag2").exists())

    def test_command_empty_tags_in_list(self):
        """Test that empty strings in tag list are filtered out."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--tags=,,,valid-tag,,,",
            stdout=out,
        )

        source = PointSource.objects.first()
        # Should only have one tag (empty strings filtered out)
        self.assertEqual(source.tags.count(), 1)
        self.assertTrue(source.tags.filter(name="valid-tag").exists())

    def test_command_all_flags_combined(self):
        """Test command with all flags combined."""
        Tag.objects.create(name="special", slug="special")

        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "200",
            "--description=All flags test",
            "--tags=special",
            stdout=out,
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.total_points, 200)

        transaction = PointTransaction.objects.first()
        self.assertEqual(transaction.description, "All flags test")

        source = PointSource.objects.first()
        self.assertTrue(source.tags.filter(name="special").exists())

        output = out.getvalue()
        self.assertIn("Successfully granted 200 points to testuser", output)
        self.assertIn("Description: All flags test", output)
        self.assertIn("Tags: special", output)
        self.assertIn("User's total points: 200", output)

    def test_command_creates_new_tags_when_not_exists(self):
        """Test that command creates new tags when they don't exist."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--tags=brand-new-tag",
            stdout=out,
        )

        # Tag should be created
        self.assertTrue(Tag.objects.filter(name="brand-new-tag").exists())

        source = PointSource.objects.first()
        self.assertTrue(source.tags.filter(name="brand-new-tag").exists())

    def test_command_output_shows_total_points(self):
        """Test that command output includes user's total points."""
        # Grant points twice to test accumulation
        out1 = StringIO()
        call_command("grant_points", "testuser", "100", stdout=out1)

        out2 = StringIO()
        call_command("grant_points", "testuser", "50", stdout=out2)

        self.assertIn("User's total points: 100", out1.getvalue())
        self.assertIn("User's total points: 150", out2.getvalue())

    def test_command_with_chinese_tag_names(self):
        """Test command with Chinese characters in tag names."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "100",
            "--tags=签到奖励,推荐奖励",
            stdout=out,
        )

        source = PointSource.objects.first()
        self.assertEqual(source.tags.count(), 2)
        self.assertTrue(source.tags.filter(name="签到奖励").exists())
        self.assertTrue(source.tags.filter(name="推荐奖励").exists())

    def test_command_point_source_creation(self):
        """Test that PointSource is created correctly."""
        out = StringIO()
        call_command("grant_points", "testuser", "150", stdout=out)

        source = PointSource.objects.first()
        self.assertIsNotNone(source)
        self.assertEqual(source.user_profile, self.user)
        self.assertEqual(source.initial_points, 150)
        self.assertEqual(source.remaining_points, 150)

    def test_command_point_transaction_creation(self):
        """Test that PointTransaction is created correctly."""
        out = StringIO()
        call_command(
            "grant_points",
            "testuser",
            "250",
            "--description=测试积分",
            stdout=out,
        )

        transaction = PointTransaction.objects.first()
        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.user_profile, self.user)
        self.assertEqual(transaction.points, 250)
        self.assertEqual(
            transaction.transaction_type, PointTransaction.TransactionType.EARN
        )
        self.assertEqual(transaction.description, "测试积分")

    def test_command_user_not_found_by_username_or_email(self):
        """Test that CommandError is raised when user is not found by username or email."""
        from django.core.management.base import CommandError

        with self.assertRaisesMessage(CommandError, "User not found: nosuchuser"):
            call_command("grant_points", "nosuchuser", "100")
