"""Tests for config module."""

import importlib
import os
import sys
from unittest import mock

from django.conf import settings
from django.contrib import admin
from django.core.handlers.asgi import ASGIHandler
from django.core.handlers.wsgi import WSGIHandler
from django.test import SimpleTestCase
from django.urls import resolve


class ConfigModuleTests(SimpleTestCase):
    """Test cases for configuration module."""

    def test_settings_loaded_defaults(self):
        """Test that settings are loaded with correct defaults."""
        assert settings.AUTH_USER_MODEL == "accounts.User"
        assert "MAILGUN_API_KEY" in settings.ANYMAIL
        assert "MAILGUN_SENDER_DOMAIN" in settings.ANYMAIL

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
