"""Focused contract tests for the WSGI entrypoint."""

import os
import sys
import types
from pathlib import Path
from unittest import mock

from django.core.handlers.wsgi import WSGIHandler
from django.test import SimpleTestCase


class WSGIEntrypointTests(SimpleTestCase):
    """Keep the WSGI module covered without environment-sensitive assertions."""

    @property
    def module_path(self) -> Path:
        """Return the WSGI module file path."""
        return Path(__file__).resolve().parents[2] / "config" / "wsgi.py"

    def _load_module(self, module_name="config.wsgi"):
        """Execute the WSGI module from source so coverage sees the file."""
        module = types.ModuleType(module_name)
        module.__file__ = str(self.module_path)
        module.__package__ = "config"
        exec(  # noqa: S102 - intentional test-only execution of a local source file.
            compile(
                self.module_path.read_text(encoding="utf-8"),
                str(self.module_path),
                "exec",
            ),
            module.__dict__,
        )
        return module

    def tearDown(self):
        """Discard module cache between tests that mutate import state."""
        sys.modules.pop("config.wsgi", None)
        super().tearDown()

    def test_import_exposes_application_handler(self):
        """The module should expose a concrete Django WSGI handler."""
        from config.wsgi import application

        assert isinstance(application, WSGIHandler)
        assert callable(application)

    def test_import_sets_default_settings_module(self):
        """A missing DJANGO_SETTINGS_MODULE should be defaulted on import."""
        with mock.patch.dict(os.environ, {}, clear=True):
            module = self._load_module("config.wsgi.coverage")
            assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings"

        assert module.__name__ == "config.wsgi.coverage"

    def test_import_preserves_existing_settings_module(self):
        """Import should respect an already configured settings module."""
        with mock.patch.dict(
            os.environ, {"DJANGO_SETTINGS_MODULE": "custom.settings"}, clear=True
        ):
            self._load_module("config.wsgi.coverage")
            assert os.environ["DJANGO_SETTINGS_MODULE"] == "custom.settings"

    def test_import_uses_django_get_wsgi_application(self):
        """The module should build its application via Django's factory."""
        mock_application = mock.Mock(spec=WSGIHandler)

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch(
                "django.core.wsgi.get_wsgi_application",
                return_value=mock_application,
            ) as mock_get_wsgi,
        ):
            module = self._load_module("config.wsgi.coverage")

        mock_get_wsgi.assert_called_once_with()
        assert module.application is mock_application
