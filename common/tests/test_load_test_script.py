"""Tests for the lightweight load-test CLI wrapper."""

import runpy
import sys
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase


class LoadTestScriptEntrypointTests(SimpleTestCase):
    """Cover the thin scripts/load_test.py entrypoint."""

    @property
    def repo_root(self) -> Path:
        """Return the repository root."""
        return Path(__file__).resolve().parents[2]

    @property
    def script_path(self) -> Path:
        """Return the load-test wrapper path."""
        return self.repo_root / "scripts" / "load_test.py"

    def test_script_inserts_project_root_and_exits_with_main_return_code(self):
        """Running the script as __main__ should prepend the repo root and exit."""
        project_root = str(self.repo_root)
        path_without_root = [path for path in sys.path if path != project_root]

        with (
            patch.object(sys, "path", list(path_without_root)),
            patch("common.load_testing.main", return_value=7) as mock_main,
            self.assertRaises(SystemExit) as exc,
        ):
            runpy.run_path(str(self.script_path), run_name="__main__")

        self.assertEqual(exc.exception.code, 7)
        self.assertEqual(sys.path[0], project_root)
        mock_main.assert_called_once_with()
