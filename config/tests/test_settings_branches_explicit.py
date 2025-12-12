"""Extra coverage for conditional settings branches."""

import importlib
import os
import sys
from unittest import mock

from django.test import SimpleTestCase


class SettingsBranchesExplicitTests(SimpleTestCase):
    """Reload config.settings under controlled environments to hit all branches."""

    def reload_settings(self, env=None, argv=None, extra_modules=None):
        env = env or {}
        extra_modules = extra_modules or {}
        original_env = os.environ.copy()
        original_argv = sys.argv[:]
        try:
            os.environ.update(env)
            if argv is not None:
                sys.argv = argv
            sys.modules.pop("config.settings", None)
            with mock.patch.dict(sys.modules, extra_modules, clear=False):
                import config.settings as settings_module

                return importlib.reload(settings_module)
        finally:
            os.environ.clear()
            os.environ.update(original_env)
            sys.argv = original_argv
            sys.modules.pop("config.settings", None)
            importlib.import_module("config.settings")

    def test_cache_middleware_branch_when_redis_enabled(self):
        """REDIS_URL should wrap middleware list with cache handlers."""
        reloaded = self.reload_settings(
            env={"REDIS_URL": "redis://cache:6379/0"}, argv=["manage.py"]
        )
        self.assertIn(
            "django.middleware.cache.UpdateCacheMiddleware", reloaded.MIDDLEWARE
        )
        self.assertTrue(reloaded.MIDDLEWARE[-1].endswith("FetchFromCacheMiddleware"))

    def test_debug_toolbar_branch_inserts_middleware(self):
        """DEBUG toolbar is appended when available and not testing."""
        fake_toolbar = mock.MagicMock()
        reloaded = self.reload_settings(
            env={"DEBUG": "true"},
            argv=["manage.py"],
            extra_modules={"debug_toolbar": fake_toolbar},
        )
        self.assertIn("debug_toolbar", reloaded.INSTALLED_APPS)
        self.assertIn(
            "debug_toolbar.middleware.DebugToolbarMiddleware",
            reloaded.MIDDLEWARE,
        )

    def test_security_flags_enabled_when_not_debug(self):
        """Production security flags should be turned on when DEBUG is false."""
        reloaded = self.reload_settings(env={"DEBUG": "false"}, argv=["manage.py"])
        self.assertTrue(reloaded.SECURE_SSL_REDIRECT)
        self.assertTrue(reloaded.CSRF_COOKIE_SECURE)
        self.assertEqual(reloaded.CSRF_COOKIE_SAMESITE, "Strict")
