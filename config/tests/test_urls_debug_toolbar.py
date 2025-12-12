"""Ensure debug toolbar URL inclusion branch is covered."""

import importlib
import sys
from unittest import mock

from django.test import SimpleTestCase, override_settings


class ConfigUrlsDebugToolbarTests(SimpleTestCase):
    """Verify config.urls appends debug toolbar URLs when enabled."""

    @override_settings(DEBUG=True, TESTING=False)
    def test_debug_toolbar_urls_appended(self):
        fake_module = mock.MagicMock()
        fake_module.debug_toolbar_urls.return_value = ["__debug__/"]

        # Remove cached module to force evaluation of the debug branch
        sys.modules.pop("config.urls", None)
        with mock.patch.dict(
            sys.modules, {"debug_toolbar.toolbar": fake_module}, clear=False
        ):
            from config import urls

            urls = importlib.reload(urls)

        self.assertIn("__debug__/", urls.urlpatterns[-1])

    @override_settings(DEBUG=True, TESTING=False)
    def test_debug_toolbar_missing_module_is_ignored(self):
        """ImportError should be swallowed when debug toolbar is absent."""
        sys.modules.pop("config.urls", None)

        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if name == "debug_toolbar.toolbar":
                raise ImportError("debug toolbar not installed")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            from config import urls

            urls = importlib.reload(urls)

        self.assertTrue(
            all("__debug__" not in str(pattern.pattern) for pattern in urls.urlpatterns)
        )
