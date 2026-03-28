"""Tests for the standalone coverage gate script."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


class CoverageGateScriptTests(SimpleTestCase):
    """Validate independent line and branch coverage thresholds."""

    @property
    def script_path(self) -> Path:
        """Return the path to the coverage gate script."""
        return Path(__file__).resolve().parents[2] / "scripts" / "check_coverage.py"

    def _run_gate(self, totals: dict) -> subprocess.CompletedProcess[str]:
        """Write a temporary coverage report and execute the gate script against it."""
        with TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "coverage.json"
            report_path.write_text(
                json.dumps({"meta": {}, "files": {}, "totals": totals}),
                encoding="utf-8",
            )
            return subprocess.run(  # noqa: S603 - trusted local script path and temp file.
                [sys.executable, str(self.script_path), str(report_path)],
                capture_output=True,
                check=False,
                text=True,
            )

    def test_gate_passes_when_line_and_branch_thresholds_are_met(self):
        """Coverage at the threshold should still pass."""
        result = self._run_gate(
            {
                "covered_lines": 95,
                "num_statements": 100,
                "covered_branches": 17,
                "num_branches": 20,
            }
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("Coverage gate passed", result.stdout)

    def test_gate_fails_when_line_coverage_is_below_threshold(self):
        """Line coverage should be enforced independently from branch coverage."""
        result = self._run_gate(
            {
                "covered_lines": 94,
                "num_statements": 100,
                "covered_branches": 17,
                "num_branches": 20,
            }
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("line coverage 94.00% is below threshold 95.00%", result.stderr)

    def test_gate_fails_when_branch_coverage_is_below_threshold(self):
        """Branch coverage should fail even if line coverage remains healthy."""
        result = self._run_gate(
            {
                "covered_lines": 98,
                "num_statements": 100,
                "covered_branches": 16,
                "num_branches": 20,
            }
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "branch coverage 80.00% is below threshold 85.00%",
            result.stderr,
        )
