"""Management command to re-run an account merge by request id."""

from django.core.management.base import BaseCommand, CommandError

from accounts.models import AccountMergeRequest
from accounts.services import AccountMergeError, perform_merge


class Command(BaseCommand):
    """Execute a pending account merge by request UUID."""

    help = "Run account merge for a specific request (UUID)."

    def add_arguments(self, parser):
        """Register CLI arguments for the merge command."""
        parser.add_argument(
            "--request",
            dest="request_id",
            required=True,
            help="AccountMergeRequest UUID",
        )

    def handle(self, *args, **options):
        """Execute merge for the provided request id."""
        request_id = options["request_id"]
        try:
            merge_request = AccountMergeRequest.objects.get(id=request_id)
        except AccountMergeRequest.DoesNotExist as exc:  # pragma: no cover - defensive
            msg = f"Merge request {request_id} does not exist"
            raise CommandError(msg) from exc

        if merge_request.status != AccountMergeRequest.Status.PENDING:
            self.stdout.write(
                self.style.WARNING(
                    f"Request {merge_request.id} already processed with status {merge_request.status}"
                )
            )
            return

        try:
            perform_merge(merge_request)
        except AccountMergeError as exc:  # pragma: no cover - defensive
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Merge completed for request {merge_request.id}: {merge_request.source_user} -> {merge_request.target_user}"
            )
        )
