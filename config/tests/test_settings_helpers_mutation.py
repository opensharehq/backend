"""Mutation-focused tests for the settings helpers module."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from django.test import SimpleTestCase


class SettingsHelpersMutationTests(SimpleTestCase):
    """Load the helper module by file path so mutmut sees the mutated file."""

    @property
    def module_path(self) -> Path:
        """Return the settings helpers module path in the active tree."""
        return Path(__file__).resolve().parents[2] / "config" / "settings_helpers.py"

    def load_module(self):
        """Load a fresh module instance using the canonical package name."""
        spec = importlib.util.spec_from_file_location(
            "config.settings_helpers",
            self.module_path,
        )
        module = importlib.util.module_from_spec(spec)
        assert spec is not None
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_build_cache_settings_covers_redis_testing_debug_and_default_branches(self):
        """The cache helper should select the right backend for each mode."""
        module = self.load_module()

        redis_cache = module.build_cache_settings(
            debug=False,
            redis_url="redis://cache/1",
        )
        testing_cache = module.build_cache_settings(
            debug=False,
            redis_url="",
            testing=True,
        )
        debug_cache = module.build_cache_settings(
            debug=True,
            redis_url="",
        )
        default_cache = module.build_cache_settings(
            debug=False,
            redis_url="",
        )

        self.assertEqual(
            redis_cache["default"]["BACKEND"],
            "django.core.cache.backends.redis.RedisCache",
        )
        self.assertEqual(
            redis_cache["default"]["LOCATION"],
            "redis://cache/1",
        )
        self.assertEqual(
            testing_cache["default"]["BACKEND"],
            "django.core.cache.backends.dummy.DummyCache",
        )
        self.assertEqual(
            debug_cache["default"]["BACKEND"],
            "django.core.cache.backends.dummy.DummyCache",
        )
        self.assertEqual(
            default_cache["default"]["BACKEND"],
            "django.core.cache.backends.locmem.LocMemCache",
        )

    def test_determine_email_backend_covers_mailgun_and_console_paths(self):
        """Email backend selection should switch on complete Mailgun credentials."""
        module = self.load_module()

        mailgun_backend, mailgun_config = module.determine_email_backend(
            "key",
            "mg.example.com",
        )
        console_backend, console_config = module.determine_email_backend("", "")

        self.assertEqual(mailgun_backend, "anymail.backends.mailgun.EmailBackend")
        self.assertEqual(mailgun_config["MAILGUN_API_KEY"], "key")
        self.assertEqual(
            mailgun_config["MAILGUN_SENDER_DOMAIN"],
            "mg.example.com",
        )
        self.assertEqual(
            console_backend,
            "django.core.mail.backends.console.EmailBackend",
        )
        self.assertEqual(console_config, {})
