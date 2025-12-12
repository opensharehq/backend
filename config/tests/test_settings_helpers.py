"""Focused tests for `config.settings_helpers`."""

from django.test import SimpleTestCase

from config.settings_helpers import build_cache_settings, determine_email_backend


class SettingsHelpersTests(SimpleTestCase):
    """Ensure cache and email helper functions cover all branches."""

    def test_build_cache_settings_prefers_redis_when_url_provided(self):
        """Return Redis-backed cache when a Redis URL is configured."""
        caches = build_cache_settings(debug=False, redis_url="redis://localhost:6379/1")

        self.assertEqual(
            caches["default"]["BACKEND"],
            "django.core.cache.backends.redis.RedisCache",
        )
        self.assertEqual(caches["default"]["LOCATION"], "redis://localhost:6379/1")

    def test_build_cache_settings_returns_dummy_cache_during_testing(self):
        """Use dummy cache backend when testing flag is enabled."""
        caches = build_cache_settings(debug=False, redis_url="", testing=True)

        self.assertEqual(
            caches["default"]["BACKEND"],
            "django.core.cache.backends.dummy.DummyCache",
        )

    def test_build_cache_settings_switches_backend_by_debug_flag(self):
        """Ensure cache backend toggles between dummy and locmem by debug."""
        debug_cache = build_cache_settings(debug=True, redis_url="")
        prod_cache = build_cache_settings(debug=False, redis_url="")

        self.assertEqual(
            debug_cache["default"]["BACKEND"],
            "django.core.cache.backends.dummy.DummyCache",
        )
        self.assertEqual(
            prod_cache["default"]["BACKEND"],
            "django.core.cache.backends.locmem.LocMemCache",
        )

    def test_determine_email_backend_defaults_to_console(self):
        """Default to console email backend when settings are empty."""
        backend, settings_dict = determine_email_backend("", "")

        self.assertEqual(backend, "django.core.mail.backends.console.EmailBackend")
        self.assertEqual(settings_dict, {})

    def test_determine_email_backend_uses_mailgun_when_configured(self):
        """Mailgun credentials should switch backend and provide API config."""
        backend, settings_dict = determine_email_backend("key-123", "mg.example.com")

        self.assertEqual(backend, "anymail.backends.mailgun.EmailBackend")
        self.assertEqual(
            settings_dict,
            {"MAILGUN_API_KEY": "key-123", "MAILGUN_SENDER_DOMAIN": "mg.example.com"},
        )
