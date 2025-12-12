"""Tests for config module."""

import importlib
import os
import sys
from unittest import mock

from django.conf import settings
from django.contrib import admin
from django.core.handlers.asgi import ASGIHandler
from django.core.handlers.wsgi import WSGIHandler
from django.test import SimpleTestCase, override_settings
from django.urls import resolve

from config.settings_helpers import build_cache_settings, determine_email_backend


class ConfigModuleTests(SimpleTestCase):
    """Test cases for configuration module."""

    def test_settings_loaded_defaults(self):
        """Test that settings are loaded with correct defaults."""
        assert settings.AUTH_USER_MODEL == "accounts.User"
        assert "MAILGUN_API_KEY" in settings.ANYMAIL
        assert "MAILGUN_SENDER_DOMAIN" in settings.ANYMAIL
        self.assertIn(
            settings.CACHES["default"]["BACKEND"],
            {
                "django.core.cache.backends.locmem.LocMemCache",
                "django.core.cache.backends.dummy.DummyCache",
            },
        )

    def test_root_url_resolves_homepage_index(self):
        """Test that root URL resolves to homepage index view."""
        match = resolve("/")

        assert match.func.__name__ == "index"

    def test_asgi_application_reload(self):
        """Test that ASGI application can be reloaded correctly."""
        sys.modules.pop("config.asgi", None)

        with mock.patch.dict(os.environ, {}, clear=True):
            module = importlib.import_module("config.asgi")
            reloaded = importlib.reload(module)

            assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings"
            assert isinstance(reloaded.application, ASGIHandler)

    def test_wsgi_application_reload(self):
        """Test that WSGI application can be reloaded correctly."""
        sys.modules.pop("config.wsgi", None)

        with mock.patch.dict(os.environ, {}, clear=True):
            module = importlib.import_module("config.wsgi")
            reloaded = importlib.reload(module)

            assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings"
            assert isinstance(reloaded.application, WSGIHandler)

    def test_admin_site_customization(self):
        """Test that admin site is customized with OpenShare branding."""
        # Import admin customization to apply settings
        import config.admin  # noqa: F401

        assert admin.site.site_header == "OpenShare 管理后台"
        assert admin.site.site_title == "OpenShare 管理后台"
        assert admin.site.index_title == "欢迎使用 OpenShare 管理后台"

    def test_language_code_is_chinese(self):
        """Test that default language is Chinese."""
        assert settings.LANGUAGE_CODE == "zh-hans"

    def test_cache_configuration_uses_redis_when_url_present(self):
        """Cache helper returns redis backend when URL is provided."""
        caches = build_cache_settings(False, "redis://localhost:6379/1")
        assert (
            caches["default"]["BACKEND"]
            == "django.core.cache.backends.redis.RedisCache"
        )
        assert caches["default"]["LOCATION"] == "redis://localhost:6379/1"

    def test_cache_configuration_dummy_vs_locmem(self):
        """Cache helper falls back to dummy in debug and locmem otherwise."""
        debug_cache = build_cache_settings(True, "")
        prod_cache = build_cache_settings(False, "")

        assert (
            debug_cache["default"]["BACKEND"]
            == "django.core.cache.backends.dummy.DummyCache"
        )
        assert (
            prod_cache["default"]["BACKEND"]
            == "django.core.cache.backends.locmem.LocMemCache"
        )

    def test_email_backend_falls_back_to_console(self):
        """Console email backend is selected when Mailgun keys are missing."""
        backend, anymail = determine_email_backend("", "")
        assert backend == "django.core.mail.backends.console.EmailBackend"
        assert anymail == {}

    def test_email_backend_uses_mailgun_configuration(self):
        """Mailgun settings are returned when both key and domain exist."""
        backend, anymail = determine_email_backend("key", "domain")
        assert backend == "anymail.backends.mailgun.EmailBackend"
        assert anymail["MAILGUN_API_KEY"] == "key"
        assert anymail["MAILGUN_SENDER_DOMAIN"] == "domain"


class SettingsBranchCoverageTests(SimpleTestCase):
    """Reload settings with different environment combinations to hit import-time branches."""

    def reload_settings(self, env_overrides=None, argv=None, extra_modules=None):
        """Reload config.settings with temporary environment."""
        import config.settings as settings_module

        env_overrides = env_overrides or {}
        extra_modules = extra_modules or {}
        original_env = os.environ.copy()
        original_argv = sys.argv[:]
        try:
            os.environ.update(env_overrides)
            if argv is not None:
                sys.argv = argv
            with mock.patch.dict(sys.modules, extra_modules, clear=False):
                reloaded = importlib.reload(settings_module)
            return reloaded
        finally:
            os.environ.clear()
            os.environ.update(original_env)
            sys.modules.pop("config.settings", None)
            importlib.import_module("config.settings")
            sys.argv = original_argv

    def test_redis_middleware_enabled_when_url_present(self):
        """REDIS_URL should prepend cache middleware."""
        reloaded = self.reload_settings(env_overrides={"REDIS_URL": "redis://cache"})
        self.assertIn(
            "django.middleware.cache.UpdateCacheMiddleware", reloaded.MIDDLEWARE
        )
        self.assertTrue(
            reloaded.MIDDLEWARE[0].endswith("UpdateCacheMiddleware"),
            "Cache middleware should be first when REDIS_URL is set.",
        )

    def test_debug_toolbar_added_when_available_and_debug(self):
        """Importing debug_toolbar should append its URLs and middleware."""
        mock_toolbar = mock.MagicMock()
        mock_toolbar.debug_toolbar_urls.return_value = ["debug/"]
        fake_debug_toolbar = mock.MagicMock(toolbar=mock_toolbar)

        reloaded = self.reload_settings(
            env_overrides={"DEBUG": "true"},
            argv=["manage.py"],
            extra_modules={
                "debug_toolbar": fake_debug_toolbar,
                "debug_toolbar.toolbar": mock_toolbar,
            },
        )
        self.assertIn(
            "debug_toolbar.middleware.DebugToolbarMiddleware", reloaded.MIDDLEWARE
        )

    def test_security_flags_enabled_in_production(self):
        """When DEBUG is false, security-related settings should be enforced."""
        reloaded = self.reload_settings(
            env_overrides={"DEBUG": "false"},
            argv=["manage.py"],
        )
        self.assertTrue(reloaded.SECURE_SSL_REDIRECT)
        self.assertTrue(reloaded.SECURE_HSTS_PRELOAD)
        self.assertEqual(reloaded.SESSION_COOKIE_SAMESITE, "Strict")

    @override_settings(DEBUG=True, TESTING=False)
    def test_urls_append_debug_toolbar_patterns(self):
        """config.urls should append debug toolbar URLs when available."""
        mock_toolbar = mock.MagicMock()
        mock_toolbar.debug_toolbar_urls.return_value = ["dbg/"]
        with mock.patch.dict(
            sys.modules,
            {
                "debug_toolbar": mock.MagicMock(toolbar=mock_toolbar),
                "debug_toolbar.toolbar": mock_toolbar,
            },
            clear=False,
        ):
            from config import urls

            importlib.reload(urls)
            self.assertIn("dbg/", urls.urlpatterns[-1])
