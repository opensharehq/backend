"""Regression checks for the repository coverage contract."""

import tomllib
from pathlib import Path

from django.test import SimpleTestCase


class CoverageConfigurationContractTests(SimpleTestCase):
    """Keep the denominator explicit and aligned with the repo's risk areas."""

    @property
    def pyproject_path(self) -> Path:
        """Return the repository pyproject path."""
        return Path(__file__).resolve().parents[2] / "pyproject.toml"

    @property
    def coverage_run_config(self) -> dict:
        """Load the configured coverage run section."""
        config = tomllib.loads(self.pyproject_path.read_text(encoding="utf-8"))
        return config["tool"]["coverage"]["run"]

    def test_coverage_uses_explicit_source_roots(self):
        """Coverage must define repo-owned source roots instead of omit-only logic."""
        self.assertEqual(
            self.coverage_run_config["source"],
            [
                "accounts",
                "chdb",
                "common",
                "config",
                "contributions",
                "homepage",
                "messages",
                "points",
                "scripts",
                "shop",
            ],
        )
        self.assertTrue(self.coverage_run_config["relative_files"])

    def test_admin_modules_are_not_excluded_from_coverage(self):
        """Admin logic should stay inside the measured denominator."""
        self.assertNotIn("*/admin.py", self.coverage_run_config["omit"])
        self.assertIn("*/tests/*", self.coverage_run_config["omit"])
        self.assertIn("*/migrations/*", self.coverage_run_config["omit"])
