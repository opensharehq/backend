"""Regression checks for the repository mutation-testing baseline."""

import tomllib
from pathlib import Path

from django.test import SimpleTestCase


class MutationConfigurationContractTests(SimpleTestCase):
    """Keep mutation testing focused on real business risk, not only helpers."""

    @property
    def pyproject_path(self) -> Path:
        """Return the repository pyproject path."""
        return Path(__file__).resolve().parents[2] / "pyproject.toml"

    @property
    def mutmut_config(self) -> dict:
        """Load the configured mutmut section."""
        config = tomllib.loads(self.pyproject_path.read_text(encoding="utf-8"))
        return config["tool"]["mutmut"]

    def test_mutation_targets_include_core_business_modules(self):
        """Mutation scope should include the highest-risk request and points flows."""
        self.assertEqual(
            self.mutmut_config["paths_to_mutate"],
            [
                "accounts/views.py",
                "common/load_testing.py",
                "common/middleware.py",
                "config/settings_helpers.py",
                "points/allocation_services.py",
                "points/services.py",
                "scripts/check_coverage.py",
            ],
        )

    def test_mutation_test_selection_covers_accounts_and_points_contracts(self):
        """The curated mutation suite should exercise the newly added business modules."""
        selection = self.mutmut_config["pytest_add_cli_args_test_selection"]

        self.assertIn("accounts/tests/test_views.py", selection)
        self.assertIn("points/tests/test_allocation_contract.py", selection)
        self.assertIn("points/tests/test_allocation_services.py", selection)
        self.assertIn("points/tests/test_services.py", selection)
