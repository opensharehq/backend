"""Tests for API v1 configuration."""

import importlib
import os
import sys

from django.test import SimpleTestCase


class ConfigApiV1Tests(SimpleTestCase):
    """Cover API v1 wiring and JWT setting defaults."""

    def reload_settings(self, env=None, argv=None):
        """Reload config.settings with temporary environment overrides."""
        env = env or {}
        original_env = os.environ.copy()
        original_argv = sys.argv[:]
        try:
            effective_env = original_env.copy()
            for key, value in env.items():
                if value is None:
                    effective_env.pop(key, None)
                else:
                    effective_env[key] = value
            os.environ.clear()
            os.environ.update(effective_env)
            if argv is not None:
                sys.argv = argv
            sys.modules.pop("config.settings", None)
            import config.settings as settings_module

            return importlib.reload(settings_module)
        finally:
            os.environ.clear()
            os.environ.update(original_env)
            sys.argv = original_argv
            sys.modules.pop("config.settings", None)
            importlib.import_module("config.settings")

    def test_openapi_schema_exposes_v1_auth_endpoints(self):
        """The OpenAPI schema should expose the new auth endpoints."""
        response = self.client.get("/api/v1/openapi.json")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["info"]["title"], "OpenShare API")
        self.assertEqual(payload["info"]["version"], "1.0.0")
        self.assertIn("/api/v1/auth/login", payload["paths"])
        self.assertIn("/api/v1/auth/verify", payload["paths"])

    def test_jwt_settings_fall_back_to_defaults(self):
        """JWT settings should use the documented defaults when unset."""
        reloaded = self.reload_settings(
            env={
                "JWT_SECRET_KEY": None,
                "JWT_ALGORITHM": None,
                "JWT_ACCESS_TTL_SECONDS": None,
            },
            argv=["manage.py"],
        )

        self.assertEqual(reloaded.JWT_SECRET_KEY, reloaded.SECRET_KEY)
        self.assertEqual(reloaded.JWT_ALGORITHM, "HS256")
        self.assertEqual(reloaded.JWT_ACCESS_TTL_SECONDS, 86400)
