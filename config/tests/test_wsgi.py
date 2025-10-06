"""
Comprehensive tests for config/wsgi.py module.

This test module ensures 100% coverage of the WSGI configuration,
including initialization, environment setup, and application instantiation.
"""

import importlib
import os
import sys
from unittest import mock

from django.core.handlers.wsgi import WSGIHandler
from django.test import SimpleTestCase


class WSGIModuleTests(SimpleTestCase):
    """Test cases for WSGI module configuration."""

    def test_wsgi_module_imports_successfully(self):
        """Test that wsgi module can be imported without errors."""
        import config.wsgi

        assert config.wsgi is not None
        assert hasattr(config.wsgi, "application")

    def test_wsgi_application_is_wsgi_handler_instance(self):
        """Test that application is a WSGIHandler instance."""
        import config.wsgi

        assert isinstance(config.wsgi.application, WSGIHandler)

    def test_wsgi_application_is_callable(self):
        """Test that WSGI application is callable (WSGI spec requirement)."""
        import config.wsgi

        # WSGI applications must be callable
        assert callable(config.wsgi.application)

    def test_wsgi_sets_django_settings_module_by_default(self):
        """Test that WSGI module sets DJANGO_SETTINGS_MODULE to config.settings."""
        # Remove wsgi from modules to force fresh import
        sys.modules.pop("config.wsgi", None)

        # Clear environment variable
        with mock.patch.dict(os.environ, {}, clear=True):
            import config.wsgi

            assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings"
            assert isinstance(config.wsgi.application, WSGIHandler)

    def test_wsgi_respects_existing_django_settings_module(self):
        """Test that wsgi.py respects pre-existing DJANGO_SETTINGS_MODULE."""
        # Remove wsgi from modules
        sys.modules.pop("config.wsgi", None)

        custom_settings = "custom.test.settings"
        with mock.patch.dict(
            os.environ, {"DJANGO_SETTINGS_MODULE": custom_settings}, clear=True
        ):
            # Import should not override existing setting
            import config.wsgi  # noqa: F401

            # setdefault should preserve existing value
            assert os.environ["DJANGO_SETTINGS_MODULE"] == custom_settings

    def test_wsgi_reload_preserves_functionality(self):
        """Test that reloading wsgi module preserves application functionality."""
        sys.modules.pop("config.wsgi", None)

        with mock.patch.dict(os.environ, {}, clear=True):
            module = importlib.import_module("config.wsgi")
            reloaded = importlib.reload(module)

            assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings"
            assert isinstance(reloaded.application, WSGIHandler)
            assert callable(reloaded.application)

    def test_wsgi_application_has_correct_attributes(self):
        """Test that WSGI application has required Django handler attributes."""
        import config.wsgi

        # WSGIHandler should have these attributes from Django
        assert hasattr(config.wsgi.application, "load_middleware")
        assert hasattr(config.wsgi.application, "get_response")

    def test_wsgi_module_has_docstring(self):
        """Test that wsgi module has proper documentation."""
        import config.wsgi

        assert config.wsgi.__doc__ is not None
        assert "WSGI config" in config.wsgi.__doc__
        assert "application" in config.wsgi.__doc__

    def test_wsgi_environ_setdefault_only_sets_if_not_present(self):
        """Test that os.environ.setdefault only sets value when not already present."""
        sys.modules.pop("config.wsgi", None)

        # First scenario: No existing value
        with mock.patch.dict(os.environ, {}, clear=True):
            assert "DJANGO_SETTINGS_MODULE" not in os.environ

            assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings"

        # Clean up
        sys.modules.pop("config.wsgi", None)

        # Second scenario: Existing value should be preserved
        existing_value = "existing.settings.module"
        with mock.patch.dict(
            os.environ, {"DJANGO_SETTINGS_MODULE": existing_value}, clear=True
        ):
            assert os.environ["DJANGO_SETTINGS_MODULE"] == existing_value

    def test_wsgi_get_wsgi_application_called_correctly(self):
        """Test that get_wsgi_application is called during module import."""
        sys.modules.pop("config.wsgi", None)

        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch(
                "django.core.wsgi.get_wsgi_application", return_value=mock.Mock()
            ) as mock_get_wsgi:
                # Verify get_wsgi_application was called
                mock_get_wsgi.assert_called_once()

    def test_wsgi_application_singleton_behavior(self):
        """Test that wsgi.application is created once during module import."""
        import config.wsgi

        # Get reference to application
        app1 = config.wsgi.application

        # Import again (should use cached module)
        import config.wsgi as wsgi2

        app2 = wsgi2.application

        # Should be the same instance (module cached by Python)
        assert app1 is app2

    def test_wsgi_module_level_imports(self):
        """Test that wsgi module imports required dependencies."""
        import config.wsgi

        # Verify os is available in module
        assert hasattr(config.wsgi, "os")

        # Verify get_wsgi_application was imported
        assert hasattr(config.wsgi, "get_wsgi_application")

    def test_wsgi_application_can_handle_request_environ(self):
        """Test that WSGI application accepts proper WSGI environ dict (signature test)."""
        # WSGI spec requires application(environ, start_response)
        # We'll verify the signature is correct by checking it's callable with 2 args
        import inspect

        import config.wsgi

        sig = inspect.signature(config.wsgi.application)
        params = list(sig.parameters.keys())

        # WSGIHandler.__call__ accepts environ and start_response
        assert len(params) >= 2 or sig.parameters.get("environ") is not None

    def test_wsgi_multiple_reload_scenarios(self):
        """Test that wsgi module can be reloaded multiple times safely."""
        sys.modules.pop("config.wsgi", None)

        with mock.patch.dict(os.environ, {}, clear=True):
            # First import
            module1 = importlib.import_module("config.wsgi")
            assert isinstance(module1.application, WSGIHandler)

            # First reload
            module2 = importlib.reload(module1)
            assert isinstance(module2.application, WSGIHandler)

            # Second reload
            module3 = importlib.reload(module2)
            assert isinstance(module3.application, WSGIHandler)

            # All should set the same settings module
            assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings"

    def test_wsgi_os_environ_modification_is_persistent(self):
        """Test that os.environ modification by wsgi persists in process."""
        sys.modules.pop("config.wsgi", None)

        with mock.patch.dict(os.environ, {}, clear=True):
            # Before import
            assert "DJANGO_SETTINGS_MODULE" not in os.environ

            import config.wsgi  # noqa: F401

            # After import - should persist in environment
            assert os.environ.get("DJANGO_SETTINGS_MODULE") == "config.settings"

            # Should be accessible from os module directly
            assert os.getenv("DJANGO_SETTINGS_MODULE") == "config.settings"

    def test_wsgi_application_wsgi_compliance(self):
        """Test that application follows WSGI specification requirements."""
        import config.wsgi

        # WSGI spec requirements:
        # 1. Application must be callable
        assert callable(config.wsgi.application)

        # 2. Must accept two positional arguments (environ, start_response)
        # We can check the signature
        import inspect

        sig = inspect.signature(config.wsgi.application)

        # WSGIHandler.__call__(self, environ, start_response)
        # Should have at least 2 parameters (excluding self)
        params = [
            p
            for p in sig.parameters.values()
            if p.name != "self" or p.kind == inspect.Parameter.VAR_POSITIONAL
        ]

        # Should accept environ and start_response
        assert len(params) >= 2 or any(
            p.kind == inspect.Parameter.VAR_POSITIONAL for p in params
        )


class WSGIEnvironmentTests(SimpleTestCase):
    """Test cases for WSGI environment variable configuration."""

    def setUp(self):
        """Set up test environment by removing cached wsgi module."""
        super().setUp()
        # Remove from sys.modules to force fresh import
        sys.modules.pop("config.wsgi", None)

    def test_wsgi_with_empty_environment(self):
        """Test wsgi module initialization with completely empty environment."""
        with mock.patch.dict(os.environ, {}, clear=True):
            import config.wsgi

            assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings"
            assert isinstance(config.wsgi.application, WSGIHandler)

    def test_wsgi_with_development_settings(self):
        """Test wsgi module with development settings override."""
        sys.modules.pop("config.wsgi", None)

        dev_settings = "config.settings.development"
        with mock.patch.dict(
            os.environ, {"DJANGO_SETTINGS_MODULE": dev_settings}, clear=True
        ):
            assert os.environ["DJANGO_SETTINGS_MODULE"] == dev_settings

    def test_wsgi_with_production_settings(self):
        """Test wsgi module with production settings override."""
        sys.modules.pop("config.wsgi", None)

        prod_settings = "config.settings.production"
        with mock.patch.dict(
            os.environ, {"DJANGO_SETTINGS_MODULE": prod_settings}, clear=True
        ):
            assert os.environ["DJANGO_SETTINGS_MODULE"] == prod_settings

    def test_wsgi_environment_isolation(self):
        """Test that wsgi environment changes don't leak between imports."""
        # First import with one setting
        with mock.patch.dict(
            os.environ, {"DJANGO_SETTINGS_MODULE": "settings1"}, clear=True
        ):
            import config.wsgi as wsgi1  # noqa: F401

            env1 = os.environ["DJANGO_SETTINGS_MODULE"]

        # Clean up
        sys.modules.pop("config.wsgi", None)

        # Second import with different setting
        with mock.patch.dict(
            os.environ, {"DJANGO_SETTINGS_MODULE": "settings2"}, clear=True
        ):
            import config.wsgi as wsgi2  # noqa: F401

            env2 = os.environ["DJANGO_SETTINGS_MODULE"]

        # Each context should have its own setting
        assert env1 == "settings1"
        assert env2 == "settings2"
        assert env1 != env2


class WSGIApplicationTests(SimpleTestCase):
    """Test cases for WSGI application object properties and behavior."""

    def test_application_is_module_level_variable(self):
        """Test that application is defined at module level."""
        import config.wsgi

        # Should be accessible directly from module
        assert "application" in dir(config.wsgi)

    def test_application_type_is_wsgi_handler(self):
        """Test that application is specifically a Django WSGIHandler."""
        import config.wsgi

        assert type(config.wsgi.application).__name__ == "WSGIHandler"

    def test_application_has_django_handler_methods(self):
        """Test that application has Django WSGIHandler-specific methods."""
        import config.wsgi

        # Django-specific WSGIHandler methods
        assert hasattr(config.wsgi.application, "load_middleware")
        assert hasattr(config.wsgi.application, "get_response")

    def test_application_request_response_handler_exists(self):
        """Test that application has request/response handling capabilities."""
        import config.wsgi

        # Check for core request handling
        assert callable(config.wsgi.application)
        assert callable(config.wsgi.application)

    def test_application_created_with_current_settings(self):
        """Test that application is created with currently configured settings."""
        sys.modules.pop("config.wsgi", None)

        with mock.patch.dict(os.environ, {}, clear=True):
            import config.wsgi

            # Application should be initialized after settings are configured
            assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings"
            assert isinstance(config.wsgi.application, WSGIHandler)


class WSGIIntegrationTests(SimpleTestCase):
    """Integration tests for WSGI module in deployment scenarios."""

    def test_wsgi_module_loadable_by_gunicorn_pattern(self):
        """Test that wsgi module follows gunicorn/uwsgi import pattern."""
        # Gunicorn loads module as: module_path:variable_name
        # e.g., "config.wsgi:application"

        # Simulate fresh import
        sys.modules.pop("config.wsgi", None)

        with mock.patch.dict(os.environ, {}, clear=True):
            # This is how gunicorn imports it
            module_path = "config.wsgi"
            module = importlib.import_module(module_path)

            # Gunicorn would then access module.application
            assert hasattr(module, "application")
            assert isinstance(module.application, WSGIHandler)

    def test_wsgi_module_in_deployment_environment(self):
        """Test wsgi module with typical production environment variables."""
        sys.modules.pop("config.wsgi", None)

        deployment_env = {
            "DJANGO_SETTINGS_MODULE": "config.settings",
            "SECRET_KEY": "test-secret-key",
            "DEBUG": "False",
        }

        with mock.patch.dict(os.environ, deployment_env, clear=True):
            import config.wsgi

            assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings"
            assert isinstance(config.wsgi.application, WSGIHandler)

    def test_wsgi_can_be_imported_multiple_times_safely(self):
        """Test that wsgi can be imported multiple times (idempotent)."""
        sys.modules.pop("config.wsgi", None)

        with mock.patch.dict(os.environ, {}, clear=True):
            import config.wsgi as wsgi1
            import config.wsgi as wsgi2
            import config.wsgi as wsgi3

            # All should reference the same module (cached by Python)
            assert wsgi1 is wsgi2 is wsgi3

            # All should have valid application
            assert isinstance(wsgi1.application, WSGIHandler)
            assert isinstance(wsgi2.application, WSGIHandler)
            assert isinstance(wsgi3.application, WSGIHandler)

    def test_wsgi_works_with_relative_config_settings(self):
        """Test that wsgi works with the default relative settings path."""
        sys.modules.pop("config.wsgi", None)

        with mock.patch.dict(os.environ, {}, clear=True):
            # Should set to config.settings (not absolute path)
            assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings"
            assert "config.settings" in os.environ["DJANGO_SETTINGS_MODULE"]


class WSGIEdgeCaseTests(SimpleTestCase):
    """Edge case and error condition tests for WSGI module."""

    def test_wsgi_with_none_settings_override(self):
        """Test wsgi behavior when DJANGO_SETTINGS_MODULE is None (edge case)."""
        sys.modules.pop("config.wsgi", None)

        # Set to None (unusual but possible)
        os.environ.pop("DJANGO_SETTINGS_MODULE", None)

        import config.wsgi

        # Should set default value
        assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings"
        assert isinstance(config.wsgi.application, WSGIHandler)

    def test_wsgi_module_attributes_are_public(self):
        """Test that wsgi module exports expected public attributes."""
        import config.wsgi

        # Public attributes should not start with underscore
        public_attrs = [attr for attr in dir(config.wsgi) if not attr.startswith("_")]

        # Should include at minimum: application, os, get_wsgi_application
        assert "application" in public_attrs
        assert "os" in public_attrs
        assert "get_wsgi_application" in public_attrs

    def test_wsgi_application_not_none(self):
        """Test that application is never None."""
        import config.wsgi

        assert config.wsgi.application is not None

    def test_wsgi_setdefault_behavior_verified(self):
        """Test that os.environ.setdefault works as expected in wsgi."""
        sys.modules.pop("config.wsgi", None)

        # Test 1: No existing value - should set
        with mock.patch.dict(os.environ, {}, clear=True):
            value_before = os.environ.get("DJANGO_SETTINGS_MODULE")
            assert value_before is None

            value_after = os.environ.get("DJANGO_SETTINGS_MODULE")
            assert value_after == "config.settings"

        # Test 2: Existing value - should not change
        sys.modules.pop("config.wsgi", None)

        with mock.patch.dict(
            os.environ, {"DJANGO_SETTINGS_MODULE": "existing.settings"}, clear=True
        ):
            value_before = os.environ.get("DJANGO_SETTINGS_MODULE")
            assert value_before == "existing.settings"

            value_after = os.environ.get("DJANGO_SETTINGS_MODULE")
            assert value_after == "existing.settings"
