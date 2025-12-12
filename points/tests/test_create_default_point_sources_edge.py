"""Edge-case coverage for create_default_point_sources management command."""

from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from points.management.commands.create_default_point_sources import Command
from points.models import PointSource, Tag

User = get_user_model()


class CreateDefaultPointSourcesEdgeCaseTests(TestCase):
    """Exercise error-handling and reporting branches explicitly."""

    def setUp(self):
        self.command = Command()
        self.command.stdout = StringIO()
        self.default_tag, _ = Tag.objects.get_or_create(
            slug="default", defaults={"name": "默认", "withdrawable": True}
        )
        self.user = User.objects.create_user(username="edge-user")

    def test_process_batch_collects_per_user_errors(self):
        """A per-user creation failure should be logged and returned."""
        with mock.patch.object(
            PointSource.objects, "create", side_effect=Exception("boom")
        ):
            created, errors = self.command._process_batch(
                [self.user], self.default_tag, created_count=0, total_users=1
            )

        self.assertEqual(created, 0)
        self.assertEqual(len(errors), 1)
        self.assertIn("boom", errors[0])
        self.assertIn("错误", self.command.stdout.getvalue())

    def test_process_batch_marks_batch_failure(self):
        """An exception from the transaction wrapper marks every user as failed."""

        class ExplodingContext:
            def __enter__(self):
                raise Exception("batch fail")

            def __exit__(self, exc_type, exc, tb):
                return False

        with mock.patch(
            "points.management.commands.create_default_point_sources.transaction.atomic",
            return_value=ExplodingContext(),
        ):
            created, errors = self.command._process_batch(
                [self.user], self.default_tag, created_count=0, total_users=1
            )

        self.assertEqual(created, 0)
        self.assertTrue(any("批次失败" in err or "batch fail" in err for err in errors))
        self.assertIn("批次处理失败", self.command.stdout.getvalue())

    def test_show_results_reports_errors_and_remaining_users(self):
        """_show_results should print detailed errors and remaining-user warning."""
        errors = [f"err {i}" for i in range(12)]
        with mock.patch(
            "points.management.commands.create_default_point_sources.User.objects.exclude"
        ) as exclude_mock:
            exclude_mock.return_value.count.return_value = 5
            self.command._show_results(created_count=3, errors=errors)

        output = self.command.stdout.getvalue()
        self.assertIn("失败: 12 个用户", output)
        self.assertIn("以及其他 2 个错误", output)
        self.assertIn("仍有 5 个用户没有默认积分池", output)
