"""Tests for API v1 configuration."""

import importlib
import os
import sys

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase

from config import api_v1
from config.api_common import ApiError, translate_error_text


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

    def test_openapi_schema_exposes_response_contracts_for_key_non_auth_endpoints(self):
        """Representative non-auth routes should publish concrete response contracts."""
        response = self.client.get("/api/v1/openapi.json")

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        public_profile = payload["paths"]["/api/v1/public/users/{username}"]["get"]
        self.assertIn("200", public_profile["responses"])
        self.assertIn("404", public_profile["responses"])
        self.assertIn(
            "schema",
            public_profile["responses"]["200"]["content"]["application/json"],
        )

        message_mark_read = payload["paths"]["/api/v1/messages/mark-read"]["post"]
        self.assertIn("422", message_mark_read["responses"])
        self.assertIn(
            "schema",
            message_mark_read["responses"]["200"]["content"]["application/json"],
        )

        wallet_detail = payload["paths"]["/api/v1/points/me/wallet"]["get"]
        self.assertIn("200", wallet_detail["responses"])
        self.assertIn("401", wallet_detail["responses"])
        self.assertIn(
            "schema",
            wallet_detail["responses"]["200"]["content"]["application/json"],
        )

        redemption_create = payload["paths"]["/api/v1/shop/redemptions"]["post"]
        self.assertIn("201", redemption_create["responses"])
        self.assertIn("409", redemption_create["responses"])
        self.assertIn(
            "schema",
            redemption_create["responses"]["201"]["content"]["application/json"],
        )

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

    def test_settings_enable_s3_storage_when_required_keys_are_present(self):
        """S3 storage should activate only when all required credentials exist."""
        reloaded = self.reload_settings(
            env={
                "AWS_STORAGE_BUCKET_NAME": "openshare-test",
                "AWS_S3_ACCESS_KEY_ID": "access-key",
                "AWS_S3_SECRET_ACCESS_KEY": "secret-key",
            },
            argv=["manage.py"],
        )

        self.assertEqual(
            reloaded.STORAGES["default"]["BACKEND"],
            "storages.backends.s3.S3Storage",
        )

    def test_api_error_and_permission_handlers_and_translation_pattern(self):
        """Shared API handlers and translations should cover simple branches."""
        request = RequestFactory().get("/api/v1/test")

        self.assertEqual(str(ApiError("code", 409, "message")), "message")
        self.assertEqual(
            translate_error_text("现金积分不足，当前可用: 123"),
            "Not enough cash points. Available balance: 123.",
        )

        response = api_v1._permission_denied_handler(request, PermissionDenied())
        self.assertEqual(response.status_code, 403)
