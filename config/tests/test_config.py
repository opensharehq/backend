import importlib
import os
import sys
from unittest import mock

from django.conf import settings
from django.core.handlers.asgi import ASGIHandler
from django.core.handlers.wsgi import WSGIHandler
from django.test import SimpleTestCase
from django.urls import resolve


class ConfigModuleTests(SimpleTestCase):
    def test_settings_loaded_defaults(self):
        self.assertEqual(settings.AUTH_USER_MODEL, "accounts.User")
        self.assertIn("MAILGUN_API_KEY", settings.ANYMAIL)
        self.assertIn("MAILGUN_SENDER_DOMAIN", settings.ANYMAIL)

    def test_root_url_resolves_homepage_index(self):
        match = resolve("/")

        self.assertEqual(match.func.__name__, "index")

    def test_asgi_application_reload(self):
        sys.modules.pop("config.asgi", None)

        with mock.patch.dict(os.environ, {}, clear=True):
            module = importlib.import_module("config.asgi")
            reloaded = importlib.reload(module)

            self.assertEqual(os.environ["DJANGO_SETTINGS_MODULE"], "config.settings")
            self.assertIsInstance(reloaded.application, ASGIHandler)

    def test_wsgi_application_reload(self):
        sys.modules.pop("config.wsgi", None)

        with mock.patch.dict(os.environ, {}, clear=True):
            module = importlib.import_module("config.wsgi")
            reloaded = importlib.reload(module)

            self.assertEqual(os.environ["DJANGO_SETTINGS_MODULE"], "config.settings")
            self.assertIsInstance(reloaded.application, WSGIHandler)
