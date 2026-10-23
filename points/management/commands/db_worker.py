"""Run django_tasks with automatic recovery for interrupted point allocations."""

import os

from django.utils.autoreload import DJANGO_AUTORELOAD_ENV, run_with_reloader
from django_tasks.backends.database.management.commands.db_worker import (
    Command as DatabaseWorkerCommand,
)

from points.allocation_worker import AllocationWorker


class Command(DatabaseWorkerCommand):
    """Preserve db_worker options and use the allocation-aware implementation."""

    def add_arguments(self, parser):
        """Disable development reload by default for long-running allocations."""
        super().add_arguments(parser)
        parser.set_defaults(reload=False)

    def handle(self, *, verbosity, queue_name, reload, **options):
        """Start the worker with the standard signal and optional reload support."""
        self.configure_logging(verbosity)
        worker = AllocationWorker(
            queue_names=queue_name.split(","),
            **{
                name: options[name]
                for name in (
                    "interval",
                    "batch",
                    "backend_name",
                    "startup_delay",
                    "max_tasks",
                    "worker_id",
                )
            },
        )
        if reload and not worker.batch:
            if os.environ.get(DJANGO_AUTORELOAD_ENV) == "true":
                worker.configure_signals()
            run_with_reloader(worker.run)
        else:
            worker.configure_signals()
            worker.run()
