"""Tests for the standalone coverage gate script."""

from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase


@dataclass(frozen=True)
class ScriptRunResult:
    """Captured result of invoking the coverage gate entrypoint directly."""

    returncode: int
    stdout: str
    stderr: str


class CoverageGateScriptTests(SimpleTestCase):
    """Validate independent line and branch coverage thresholds."""

    @property
    def script_path(self) -> Path:
        """Return the path to the coverage gate script."""
        return Path(__file__).resolve().parents[2] / "scripts" / "check_coverage.py"

    @property
    def script_module(self):
        """Load the coverage gate module from its script path."""
        spec = importlib.util.spec_from_file_location(
            "scripts.check_coverage",
            self.script_path,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec is not None
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def _run_gate(self, totals: dict) -> ScriptRunResult:
        """Write a temporary coverage report and invoke the script entrypoint."""
        with TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "coverage.json"
            report_path.write_text(
                json.dumps({"meta": {}, "files": {}, "totals": totals}),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                returncode = self.script_module.main([str(report_path)])

            return ScriptRunResult(
                returncode=returncode,
                stdout=stdout.getvalue(),
                stderr=stderr.getvalue(),
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
