"""Management command to plan or apply duplicate-email cleanup."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from accounts.services.account_merge import AccountMergeError
from accounts.services.email_deduplication import (
    apply_duplicate_email_plans,
    build_duplicate_email_plans,
)


class Command(BaseCommand):
    """Plan or execute duplicate-email cleanup across user accounts."""

    help = "Plan or apply duplicate-email cleanup before adding a unique constraint."

    def add_arguments(self, parser):
        """Register CLI arguments."""
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply the planned cleanup instead of running a dry-run.",
        )

    def handle(self, *args, **options):
        """Print a dry-run plan or execute duplicate-email cleanup."""
        apply_changes = options["apply"]
        plans = build_duplicate_email_plans()
        if not plans:
            self.stdout.write(
                self.style.SUCCESS("No duplicate non-empty emails found.")
            )
            return

        blocked_plans = [plan for plan in plans if plan.is_blocked]
        total_actions = sum(len(plan.actions) for plan in plans)
        mode = "APPLY" if apply_changes else "DRY-RUN"
        self.stdout.write(
            f"{mode}: {len(plans)} duplicate-email groups, {total_actions} source accounts"
        )

        for plan in plans:
            self.stdout.write(
                f"- {plan.normalized_email}: primary={plan.primary.username}"
                f"#{plan.primary.pk}"
            )
            if plan.blocking_reason:
                self.stdout.write(
                    self.style.WARNING(f"  blocked: {plan.blocking_reason}")
                )
                continue

            for action in plan.actions:
                action_name = "archive-only" if action.archive_only else "merge"
                self.stdout.write(
                    f"  {action_name}: {action.source.username}#{action.source.pk}"
                    f" -> {plan.primary.username}#{plan.primary.pk}"
                )

        if blocked_plans:
            message = (
                "Blocked duplicate-email groups remain. Resolve them before applying."
            )
            if apply_changes:
                raise CommandError(message)
            self.stdout.write(self.style.WARNING(message))
            return

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING("Dry-run only. Re-run with --apply to execute.")
            )
            return

        try:
            apply_duplicate_email_plans(plans)
        except AccountMergeError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Duplicate-email cleanup completed for {len(plans)} groups."
            )
        )
