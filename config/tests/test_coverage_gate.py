"""Tests for the standalone coverage gate script."""

from __future__ import annotations

import importlib
import io
import json
import os
import sys
import types
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from config import api_v1
from config.api_common import ApiError, translate_error_text


@dataclass(frozen=True)
class ScriptRunResult:
    """Captured result of invoking the coverage gate entrypoint directly."""

    returncode: int
    stdout: str
    stderr: str


class CoverageGateScriptTests(SimpleTestCase):
    """Validate threshold checks plus complete source-file reporting."""

    @property
    def repo_root(self) -> Path:
        """Return the repository root for configuration lookup."""
        return Path(__file__).resolve().parents[2]

    @property
    def config_path(self) -> Path:
        """Return the active pyproject path."""
        return self.repo_root / "pyproject.toml"

    @property
    def script_path(self) -> Path:
        """Return the path to the coverage gate script."""
        return self.repo_root / "scripts" / "check_coverage.py"

    @property
    def script_module(self):
        """Load the coverage gate module from its script path."""
        module = types.ModuleType("scripts.check_coverage")
        module.__file__ = str(self.script_path)
        module.__package__ = "scripts"
        exec(  # noqa: S102 - intentional test-only execution of a local source file.
            compile(
                self.script_path.read_text(encoding="utf-8"),
                str(self.script_path),
                "exec",
            ),
            module.__dict__,
        )
        return module

    @property
    def expected_source_files(self) -> list[str]:
        """Return the repo-owned Python files that must appear in coverage."""
        run_config = self.script_module._load_coverage_run_config(self.config_path)
        return self.script_module._iter_source_files(
            self.repo_root,
            self.config_path,
            run_config,
        )

    def _run_gate(
        self, totals: dict, files: list[str] | None = None
    ) -> ScriptRunResult:
        """Write a temporary coverage report and invoke the script entrypoint."""
        with TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "coverage.json"
            file_payload = {path: {} for path in (files or self.expected_source_files)}
            report_path.write_text(
                json.dumps({"meta": {}, "files": file_payload, "totals": totals}),
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                returncode = self.script_module.main(
                    [
                        str(report_path),
                        "--config-path",
                        str(self.config_path),
                    ]
                )

            return ScriptRunResult(
                returncode=returncode,
                stdout=stdout.getvalue(),
                stderr=stderr.getvalue(),
            )

    def test_gate_passes_when_thresholds_are_met_and_source_list_is_complete(self):
        """Coverage at the threshold should still pass with complete reporting."""
        result = self._run_gate(
            {
                "covered_lines": 95,
                "num_statements": 100,
                "covered_branches": 17,
                "num_branches": 20,
            }
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("complete source reporting", result.stdout)

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

    def test_gate_fails_when_report_omits_expected_source_file(self):
        """A report missing a repo-owned source module should be rejected."""
        incomplete_files = [
            path for path in self.expected_source_files if path != "accounts/admin.py"
        ]

        result = self._run_gate(
            {
                "covered_lines": 100,
                "num_statements": 100,
                "covered_branches": 20,
                "num_branches": 20,
            },
            files=incomplete_files,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("accounts/admin.py", result.stderr)

    def test_helper_functions_cover_parser_and_normalization_branches(self):
        """Small helpers should handle zero totals, omit matching, and path normalization."""
        parser = self.script_module._build_parser()
        parsed = parser.parse_args([])

        self.assertEqual(parsed.report_path, "coverage.json")
        self.assertEqual(self.script_module._calculate_percentage(0, 0), 100.0)
        self.assertEqual(
            self.script_module._require_metric({"covered": 3}, "covered"), 3
        )
        self.assertTrue(
            self.script_module._is_omitted(
                "accounts/tests/test_views.py", ["*/tests/*"]
            )
        )
        self.assertEqual(
            self.script_module._normalize_report_path(
                self.repo_root, "accounts/admin.py"
            ),
            "accounts/admin.py",
        )
        self.assertEqual(
            self.script_module._normalize_report_path(
                self.repo_root,
                str((self.repo_root / "accounts" / "admin.py").resolve()),
            ),
            "accounts/admin.py",
        )
        self.assertEqual(
            self.script_module._normalize_report_path(
                self.repo_root,
                str((self.repo_root.parent / "external-script.py").resolve()),
            ),
            str((self.repo_root.parent / "external-script.py").resolve()),
        )

    def test_load_totals_and_metrics_raise_helpful_errors(self):
        """Malformed reports should fail with direct, actionable exceptions."""
        with TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "coverage.json"
            report_path.write_text(json.dumps({"files": {}}), encoding="utf-8")

            with self.assertRaisesMessage(
                ValueError,
                f"Coverage report at {report_path} is missing a totals section.",
            ):
                self.script_module._load_totals(report_path)

            report_path.write_text(
                json.dumps(
                    {
                        "files": {},
                        "totals": {
                            "covered_lines": 1,
                            "num_statements": 1,
                            "covered_branches": 0,
                            "num_branches": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                self.script_module._load_totals(report_path)["covered_lines"],
                1,
            )

        with self.assertRaisesMessage(
            ValueError,
            "Coverage report is missing required metric: covered_lines",
        ):
            self.script_module._require_metric({}, "covered_lines")

    def test_load_coverage_run_config_requires_explicit_source(self):
        """Config loading should reject missing coverage sections and missing source roots."""
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "pyproject.toml"
            config_path.write_text("", encoding="utf-8")

            with self.assertRaisesMessage(
                ValueError,
                f"Coverage config at {config_path} must declare tool.coverage.run.source.",
            ):
                self.script_module._load_coverage_run_config(config_path)

            config_path.write_text(
                "[tool.coverage.run]\nsource = []\n", encoding="utf-8"
            )
            with self.assertRaisesMessage(
                ValueError,
                f"Coverage config at {config_path} must declare tool.coverage.run.source.",
            ):
                self.script_module._load_coverage_run_config(config_path)

            config_path.write_text(
                "[tool.coverage]\nrun = 'invalid'\n", encoding="utf-8"
            )
            with self.assertRaisesMessage(
                ValueError,
                f"Coverage config at {config_path} is missing [tool.coverage.run].",
            ):
                self.script_module._load_coverage_run_config(config_path)

    def test_iter_source_files_skips_omitted_entries_and_validates_roots(self):
        """Source enumeration should honor omit patterns and reject missing directories."""
        files = self.script_module._iter_source_files(
            self.repo_root,
            self.config_path,
            self.script_module._load_coverage_run_config(self.config_path),
        )

        self.assertIn("accounts/admin.py", files)
        self.assertNotIn("accounts/tests/test_views.py", files)

        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            config_path = repo_root / "pyproject.toml"
            config_path.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError) as exc:
                self.script_module._iter_source_files(
                    repo_root,
                    config_path,
                    {"source": ["missing"], "omit": []},
                )
            self.assertIn(
                "Coverage source entry 'missing' does not exist under",
                str(exc.exception),
            )

            source_dir = repo_root / "pkg"
            source_dir.mkdir()
            with patch.object(Path, "rglob", return_value=[source_dir]):
                files = self.script_module._iter_source_files(
                    repo_root,
                    config_path,
                    {"source": ["pkg"], "omit": []},
                )
            self.assertEqual(files, [])

    def test_find_missing_files_and_main_report_parse_failures(self):
        """Missing files and invalid JSON should both surface through the gate."""
        report = {
            "files": {
                path: {}
                for path in self.expected_source_files
                if path != "accounts/admin.py"
            }
        }
        missing = self.script_module._find_missing_files(
            report,
            self.repo_root,
            self.config_path,
        )
        self.assertEqual(missing, ["accounts/admin.py"])

        with TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "bad.json"
            report_path.write_text("{not-json", encoding="utf-8")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                returncode = self.script_module.main(
                    [str(report_path), "--config-path", str(self.config_path)]
                )

        self.assertEqual(returncode, 1)
        self.assertIn("Coverage gate error:", stderr.getvalue())

    def test_main_rejects_reports_without_a_totals_mapping(self):
        """The top-level gate should fail fast when the JSON totals payload is malformed."""
        with TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "coverage.json"
            report_path.write_text(
                json.dumps({"meta": {}, "files": {}, "totals": []}),
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                returncode = self.script_module.main(
                    [str(report_path), "--config-path", str(self.config_path)]
                )

        self.assertEqual(returncode, 1)
        self.assertIn("missing a totals section", stderr.getvalue())

    def test_api_helpers_and_s3_settings_branches_for_full_coverage(self):
        """Cover direct API helpers in the non-parallel coverage test segment."""
        request = RequestFactory().get("/api/v1/test")

        self.assertEqual(str(ApiError("code", 409, "message")), "message")
        self.assertEqual(
            translate_error_text("现金积分不足，当前可用: 123"),
            "Not enough cash points. Available balance: 123.",
        )
        response = api_v1._permission_denied_handler(request, PermissionError())
        self.assertEqual(response.status_code, 403)

        original_env = os.environ.copy()
        original_argv = sys.argv[:]
        try:
            os.environ.update(
                {
                    "AWS_STORAGE_BUCKET_NAME": "openshare-test",
                    "AWS_S3_ACCESS_KEY_ID": "access-key",
                    "AWS_S3_SECRET_ACCESS_KEY": "secret-key",
                }
            )
            sys.argv = ["manage.py"]
            sys.modules.pop("config.settings", None)
            import config.settings as settings_module

            reloaded = importlib.reload(settings_module)
            self.assertEqual(
                reloaded.STORAGES["default"]["BACKEND"],
                "storages.backends.s3.S3Storage",
            )
        finally:
            os.environ.clear()
            os.environ.update(original_env)
            sys.argv = original_argv
            sys.modules.pop("config.settings", None)
            importlib.import_module("config.settings")
