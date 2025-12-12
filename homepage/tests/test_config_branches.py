"""Cover config-level conditional branches from an installed app test suite."""

import importlib
import os
import sys
from unittest import mock

from django.test import SimpleTestCase, override_settings

from config.settings_helpers import build_cache_settings, determine_email_backend


class ConfigSettingsBranchTests(SimpleTestCase):
    """Reload config.settings under different environments to exercise branches."""

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

    def test_cache_middleware_added_when_redis_enabled(self):
        reloaded = self.reload_settings(
            env={"REDIS_URL": "redis://cache:6379/0"}, argv=["manage.py"]
        )
        self.assertTrue(
            reloaded.MIDDLEWARE[0].endswith("UpdateCacheMiddleware"),
            reloaded.MIDDLEWARE,
        )
        self.assertTrue(
            reloaded.MIDDLEWARE[-1].endswith("FetchFromCacheMiddleware"),
            reloaded.MIDDLEWARE,
        )

    def test_debug_toolbar_injected_when_available(self):
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

    def test_debug_toolbar_importerror_is_tolerated(self):
        """When debug toolbar is missing, settings should skip injection gracefully."""
        reloaded = self.reload_settings(
            env={"DEBUG": "true"},
            argv=["manage.py"],
            extra_modules={"debug_toolbar": None, "debug_toolbar.toolbar": None},
        )
        self.assertNotIn("debug_toolbar", reloaded.INSTALLED_APPS)

    def test_security_flags_enabled_for_production(self):
        reloaded = self.reload_settings(env={"DEBUG": "false"}, argv=["manage.py"])
        self.assertTrue(reloaded.SECURE_SSL_REDIRECT)
        self.assertTrue(reloaded.SECURE_HSTS_INCLUDE_SUBDOMAINS)
        self.assertEqual(reloaded.SESSION_COOKIE_SAMESITE, "Strict")


class ConfigUrlsBranchTests(SimpleTestCase):
    """Ensure config.urls debug-toolbar inclusion executes."""

    @override_settings(DEBUG=True, TESTING=False)
    def test_debug_toolbar_urls_appended(self):
        fake_module = mock.MagicMock()
        fake_module.debug_toolbar_urls.return_value = ["__debug__/"]
        sys.modules.pop("config.urls", None)
        with mock.patch.dict(
            sys.modules, {"debug_toolbar.toolbar": fake_module}, clear=False
        ):
            urls = importlib.import_module("config.urls")

        self.assertIn("__debug__/", urls.urlpatterns[-1])

    @override_settings(DEBUG=True, TESTING=False)
    def test_debug_toolbar_importerror_in_urls_is_tolerated(self):
        """config.urls should ignore missing debug toolbar during import."""
        sys.modules.pop("config.urls", None)

        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if name == "debug_toolbar.toolbar":
                raise ImportError("debug toolbar not installed")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            urls = importlib.import_module("config.urls")

        self.assertTrue(
            all("__debug__" not in str(pattern.pattern) for pattern in urls.urlpatterns)
        )


class ConfigSettingsHelpersTests(SimpleTestCase):
    """Call helper functions directly to cover all branches."""

    def test_build_cache_settings_branches(self):
        redis_cache = build_cache_settings(debug=False, redis_url="redis://cache/1")
        self.assertEqual(
            redis_cache["default"]["BACKEND"],
            "django.core.cache.backends.redis.RedisCache",
        )

        testing_cache = build_cache_settings(debug=False, redis_url="", testing=True)
        self.assertEqual(
            testing_cache["default"]["BACKEND"],
            "django.core.cache.backends.dummy.DummyCache",
        )

        debug_cache = build_cache_settings(debug=True, redis_url="")
        self.assertEqual(
            debug_cache["default"]["BACKEND"],
            "django.core.cache.backends.dummy.DummyCache",
        )
        prod_cache = build_cache_settings(debug=False, redis_url="")
        self.assertEqual(
            prod_cache["default"]["BACKEND"],
            "django.core.cache.backends.locmem.LocMemCache",
        )

    def test_determine_email_backend_branches(self):
        backend, cfg = determine_email_backend("key", "mg.example.com")
        self.assertEqual(backend, "anymail.backends.mailgun.EmailBackend")
        self.assertEqual(cfg["MAILGUN_API_KEY"], "key")

        backend, cfg = determine_email_backend("", "")
        self.assertEqual(backend, "django.core.mail.backends.console.EmailBackend")
        self.assertEqual(cfg, {})
