"""Tests for accounts management commands."""

from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from accounts.models import AccountMergeRequest
from accounts.services import AccountMergeError
from accounts.services.email_deduplication import EmailDedupeAction, EmailDedupePlan


class SetAdminCommandTests(TestCase):
    """Test suite for the setadmin management command."""

    databases = {"default"}

    def setUp(self):
        """Create a baseline user for tests."""
        self.user = get_user_model().objects.create_user(
            username="regular",
            email="regular@example.com",
            password="password123",
            is_staff=False,
            is_superuser=False,
        )

    def test_promote_user_by_username(self):
        """Promote a user using their username."""
        output = StringIO()

        call_command("setadmin", username=self.user.username, stdout=output)

        self.user.refresh_from_db()

        assert self.user.is_staff is True
        assert self.user.is_superuser is True
        assert "promoted to admin" in output.getvalue().lower()

    def test_promote_user_by_uid(self):
        """Promote a user using their primary key."""
        output = StringIO()

        call_command("setadmin", uid=self.user.pk, stdout=output)

        self.user.refresh_from_db()

        assert self.user.is_staff is True
        assert self.user.is_superuser is True
        assert "promoted to admin" in output.getvalue().lower()

    def test_command_requires_identifier(self):
        """Command must receive exactly one identifier."""
        with self.assertRaisesMessage(
            CommandError, "Provide either --uid or --username."
        ):
            call_command("setadmin")

        with self.assertRaisesMessage(
            CommandError, "Provide only one of --uid or --username."
        ):
            call_command("setadmin", uid=self.user.pk, username=self.user.username)

    def test_missing_user_raises_error(self):
        """Command raises an error when the user does not exist."""
        with self.assertRaisesMessage(
            CommandError, "User with uid=999 does not exist."
        ):
            call_command("setadmin", uid=999)

        with self.assertRaisesMessage(
            CommandError,
            "User with username='ghost' does not exist.",
        ):
            call_command("setadmin", username="ghost")

    def test_already_admin_outputs_warning(self):
        """Warn when the user is already an admin."""
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save(update_fields=["is_staff", "is_superuser"])

        output = StringIO()

        call_command("setadmin", username=self.user.username, stdout=output)

        assert "already an admin" in output.getvalue().lower()


class MergeAccountsCommandTests(TestCase):
    """Exercise the merge_accounts management command branches."""

    databases = {"default"}

    def setUp(self):
        """Create reusable source/target accounts for merge command tests."""
        self.source = get_user_model().objects.create_user(
            username="merge-source",
            email="merge-source@example.com",
            password="password123",
        )
        self.target = get_user_model().objects.create_user(
            username="merge-target",
            email="merge-target@example.com",
            password="password123",
        )

    def _create_merge_request(self, **overrides):
        """Create a pending merge request with reasonable defaults."""
        return AccountMergeRequest.objects.create(
            source_user=overrides.get("source_user", self.source),
            target_user=overrides.get("target_user", self.target),
            target_username_input=overrides.get(
                "target_username_input",
                self.target.username,
            ),
            status=overrides.get("status", AccountMergeRequest.Status.PENDING),
            approve_token=overrides.get("approve_token", "merge-command-token"),
            expires_at=overrides.get(
                "expires_at",
                timezone.now() + timedelta(days=1),
            ),
            asset_snapshot=overrides.get("asset_snapshot", {}),
        )

    @patch("accounts.management.commands.merge_accounts.perform_merge")
    def test_runs_pending_request_and_prints_success(self, mock_perform_merge):
        """Pending requests should be passed through to the merge service."""
        merge_request = self._create_merge_request()
        output = StringIO()

        call_command("merge_accounts", request_id=str(merge_request.id), stdout=output)

        mock_perform_merge.assert_called_once()
        self.assertEqual(mock_perform_merge.call_args.args[0].id, merge_request.id)
        self.assertIn("Merge completed for request", output.getvalue())
        self.assertIn(str(merge_request.id), output.getvalue())

    @patch("accounts.management.commands.merge_accounts.perform_merge")
    def test_processed_request_warns_and_skips_merge(self, mock_perform_merge):
        """Non-pending requests should emit a warning and exit early."""
        merge_request = self._create_merge_request(
            status=AccountMergeRequest.Status.ACCEPTED,
            approve_token="processed-command-token",
        )
        output = StringIO()

        call_command("merge_accounts", request_id=str(merge_request.id), stdout=output)

        mock_perform_merge.assert_not_called()
        self.assertIn("already processed", output.getvalue())
        self.assertIn(AccountMergeRequest.Status.ACCEPTED, output.getvalue())

    def test_missing_request_raises_command_error(self):
        """Unknown request ids should produce a user-facing command error."""
        with self.assertRaisesMessage(
            CommandError,
            "Merge request 00000000-0000-0000-0000-000000000000 does not exist",
        ):
            call_command(
                "merge_accounts",
                request_id="00000000-0000-0000-0000-000000000000",
            )

    @patch(
        "accounts.management.commands.merge_accounts.perform_merge",
        side_effect=AccountMergeError("service failed"),
    )
    def test_merge_service_error_is_promoted_to_command_error(
        self, _mock_perform_merge
    ):
        """Service-level merge failures should abort the command cleanly."""
        merge_request = self._create_merge_request(
            approve_token="failing-command-token"
        )

        with self.assertRaisesMessage(CommandError, "service failed"):
            call_command("merge_accounts", request_id=str(merge_request.id))


class DedupeUserEmailsCommandTests(SimpleTestCase):
    """Exercise dry-run and apply branches of the dedupe-user-emails command."""

    def _build_plan(self, *, blocked: bool = False):
        """Create a lightweight duplicate-email plan for command tests."""
        primary = SimpleNamespace(username="primary", pk=1)
        source = SimpleNamespace(username="source", pk=2)
        return EmailDedupePlan(
            normalized_email="duplicate@example.com",
            primary=primary,
            actions=[
                EmailDedupeAction(
                    source=source,
                    primary=primary,
                    archive_only=False,
                )
            ],
            blocking_reason="group contains an admin account" if blocked else None,
        )

    @patch(
        "accounts.management.commands.dedupe_user_emails.build_duplicate_email_plans"
    )
    def test_no_duplicate_email_groups_reports_success(self, build_plans_mock):
        """An empty plan list should short-circuit without warnings."""
        build_plans_mock.return_value = []
        output = StringIO()

        call_command("dedupe_user_emails", stdout=output)

        self.assertIn("No duplicate non-empty emails found.", output.getvalue())

    @patch(
        "accounts.management.commands.dedupe_user_emails.build_duplicate_email_plans"
    )
    @patch(
        "accounts.management.commands.dedupe_user_emails.apply_duplicate_email_plans"
    )
    def test_dry_run_reports_plan_without_applying(
        self,
        apply_mock,
        build_plans_mock,
    ):
        """Dry-run mode should print the plan and skip execution."""
        build_plans_mock.return_value = [self._build_plan()]
        output = StringIO()

        call_command("dedupe_user_emails", stdout=output)

        self.assertIn("DRY-RUN", output.getvalue())
        self.assertIn("Dry-run only", output.getvalue())
        apply_mock.assert_not_called()

    @patch(
        "accounts.management.commands.dedupe_user_emails.build_duplicate_email_plans"
    )
    def test_dry_run_reports_blocked_groups_without_raising(self, build_plans_mock):
        """Dry-runs should print blocked group warnings but not raise."""
        build_plans_mock.return_value = [self._build_plan(blocked=True)]
        output = StringIO()

        call_command("dedupe_user_emails", stdout=output)

        self.assertIn("blocked: group contains an admin account", output.getvalue())
        self.assertIn("Blocked duplicate-email groups remain.", output.getvalue())

    @patch(
        "accounts.management.commands.dedupe_user_emails.build_duplicate_email_plans"
    )
    def test_apply_rejects_blocked_groups(self, build_plans_mock):
        """Blocked groups should abort the apply path before making changes."""
        build_plans_mock.return_value = [self._build_plan(blocked=True)]

        with self.assertRaisesMessage(
            CommandError,
            "Blocked duplicate-email groups remain. Resolve them before applying.",
        ):
            call_command("dedupe_user_emails", apply=True)

    @patch(
        "accounts.management.commands.dedupe_user_emails.build_duplicate_email_plans"
    )
    @patch(
        "accounts.management.commands.dedupe_user_emails.apply_duplicate_email_plans"
    )
    def test_apply_executes_safe_plans(
        self,
        apply_mock,
        build_plans_mock,
    ):
        """Safe groups should be passed through to the execution helper."""
        plan = self._build_plan()
        build_plans_mock.return_value = [plan]
        output = StringIO()

        call_command("dedupe_user_emails", apply=True, stdout=output)

        apply_mock.assert_called_once_with([plan])
        self.assertIn("cleanup completed", output.getvalue().lower())

    @patch(
        "accounts.management.commands.dedupe_user_emails.build_duplicate_email_plans"
    )
    @patch(
        "accounts.management.commands.dedupe_user_emails.apply_duplicate_email_plans"
    )
    def test_apply_wraps_account_merge_errors(self, apply_mock, build_plans_mock):
        """Execution errors should be reported as management command failures."""
        build_plans_mock.return_value = [self._build_plan()]
        apply_mock.side_effect = AccountMergeError("merge failed")

        with self.assertRaisesMessage(CommandError, "merge failed"):
            call_command("dedupe_user_emails", apply=True)
