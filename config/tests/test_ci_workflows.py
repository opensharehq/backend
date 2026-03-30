"""Regression checks for explicit coverage gate configuration."""

from pathlib import Path

from django.test import SimpleTestCase


class CoverageGateContractTests(SimpleTestCase):
    """Keep coverage gates explicit instead of relying on script defaults."""

    @property
    def repo_root(self) -> Path:
        """Return the repository root for locating workflow files."""
        return Path(__file__).resolve().parents[2]

    def _read_workflow(self, name: str) -> str:
        """Load a workflow file as text."""
        return (self.repo_root / ".github" / "workflows" / name).read_text(
            encoding="utf-8"
        )

    def test_django_tests_workflow_pins_coverage_thresholds(self):
        """The main test workflow should declare its coverage gate explicitly."""
        workflow = self._read_workflow("django-tests.yml")

        self.assertIn(
            (
                "uv run python scripts/check_coverage.py coverage.json "
                "--line-threshold 95 --branch-threshold 85"
            ),
            workflow,
        )

    def test_ghcr_build_workflow_pins_coverage_thresholds(self):
        """The image workflow should preserve its historical line coverage gate."""
        workflow = self._read_workflow("ghcr-build.yml")

        self.assertIn(
            (
                "uv run python scripts/check_coverage.py coverage.json "
                "--line-threshold 90 --branch-threshold 85"
            ),
            workflow,
        )

    def test_local_test_command_pins_coverage_thresholds(self):
        """The local test shortcut should stay aligned with the main test workflow."""
        justfile = (self.repo_root / "justfile").read_text(encoding="utf-8")

        self.assertIn(
            (
                "uv run python scripts/check_coverage.py coverage.json "
                "--line-threshold 95 --branch-threshold 85"
            ),
            justfile,
        )
