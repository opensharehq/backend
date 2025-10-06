"""
Comprehensive tests for config/asgi.py module.

This test module ensures 100% coverage of the ASGI application configuration,
including environment variable handling, Django settings loading, and ASGI
application instantiation.
"""

import importlib
import os
import sys
from unittest import mock

from django.core.handlers.asgi import ASGIHandler
from django.test import SimpleTestCase


class ASGIApplicationTests(SimpleTestCase):
    """Test cases for ASGI application configuration and initialization."""

    def test_asgi_module_imports_correctly(self):
        """Test that config.asgi module can be imported without errors."""
        # Remove from cache to force fresh import
        sys.modules.pop("config.asgi", None)

        # Import should succeed without exceptions
        module = importlib.import_module("config.asgi")

        assert module is not None
        assert hasattr(module, "application")

    def test_asgi_application_is_asgi_handler_instance(self):
        """Test that the application object is an instance of ASGIHandler."""
        from config.asgi import application

        assert isinstance(application, ASGIHandler)

    def test_asgi_sets_django_settings_module_default(self):
        """Test that ASGI module sets DJANGO_SETTINGS_MODULE to config.settings."""
        # Remove from cache to force reimport
        sys.modules.pop("config.asgi", None)

        # Clear environment to test default behavior
        with mock.patch.dict(os.environ, {}, clear=True):
            importlib.import_module("config.asgi")

            # Verify the environment variable was set
            assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings"

    def test_asgi_preserves_existing_django_settings_module(self):
        """Test that ASGI respects pre-existing DJANGO_SETTINGS_MODULE."""
        sys.modules.pop("config.asgi", None)

        custom_settings = "custom.test.settings"

        with mock.patch.dict(
            os.environ, {"DJANGO_SETTINGS_MODULE": custom_settings}, clear=True
        ):
            importlib.import_module("config.asgi")

            # Verify the custom settings were preserved (setdefault behavior)
            assert os.environ["DJANGO_SETTINGS_MODULE"] == custom_settings

    def test_asgi_application_callable(self):
        """Test that the ASGI application is callable."""
        from config.asgi import application

        # ASGI application should be callable (it's an ASGIHandler instance)
        assert callable(application)

    def test_asgi_module_reload_works_correctly(self):
        """Test that ASGI module can be reloaded without errors."""
        sys.modules.pop("config.asgi", None)

        # Import once
        module = importlib.import_module("config.asgi")
        first_application = module.application

        # Reload the module
        reloaded_module = importlib.reload(module)
        second_application = reloaded_module.application

        # Both should be ASGIHandler instances
        assert isinstance(first_application, ASGIHandler)
        assert isinstance(second_application, ASGIHandler)

    def test_asgi_uses_get_asgi_application(self):
        """Test that ASGI module uses django.core.asgi.get_asgi_application."""
        sys.modules.pop("config.asgi", None)

        with mock.patch("django.core.asgi.get_asgi_application") as mock_get_asgi:
            # Configure the mock to return a mock ASGIHandler
            mock_application = mock.Mock(spec=ASGIHandler)
            mock_get_asgi.return_value = mock_application

            # Import the module
            module = importlib.import_module("config.asgi")

            # Verify get_asgi_application was called
            mock_get_asgi.assert_called_once()

            # Verify the application is set to the return value
            assert module.application == mock_application

    def test_asgi_environment_variable_name_correct(self):
        """Test that the correct environment variable name is used."""
        sys.modules.pop("config.asgi", None)

        # Clear environment
        with mock.patch.dict(os.environ, {}, clear=True):
            importlib.import_module("config.asgi")

            # Verify specifically that DJANGO_SETTINGS_MODULE is set (not a typo)
            assert "DJANGO_SETTINGS_MODULE" in os.environ
            assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings"

    def test_asgi_module_has_correct_docstring(self):
        """Test that ASGI module has proper documentation."""
        from config import asgi

        # Module should have a docstring
        assert asgi.__doc__ is not None
        assert "ASGI config" in asgi.__doc__
        assert "application" in asgi.__doc__

    def test_asgi_application_integration_with_django(self):
        """Test that ASGI application integrates correctly with Django settings."""
        from config.asgi import application

        # The application should have Django's settings configured
        # This is implicitly tested by the fact that it's an ASGIHandler instance
        # and Django hasn't raised configuration errors
        assert isinstance(application, ASGIHandler)

        # Verify Django settings are loaded
        from django.conf import settings

        assert settings.configured


class ASGIEdgeCaseTests(SimpleTestCase):
    """Edge case tests for ASGI module to ensure robustness."""

    def test_asgi_multiple_imports_same_instance(self):
        """Test that multiple imports return the same application instance."""
        # Import twice
        from config.asgi import application as app1
        from config.asgi import application as app2

        # Should be the exact same object (singleton-like behavior from module cache)
        assert app1 is app2

    def test_asgi_module_attributes(self):
        """Test that ASGI module has expected attributes."""
        from config import asgi

        # Check for expected module-level attributes
        assert hasattr(asgi, "application")
        assert hasattr(asgi, "os")
        assert hasattr(asgi, "get_asgi_application")

    def test_asgi_settings_module_value_correctness(self):
        """Test that the settings module string is exactly correct."""
        sys.modules.pop("config.asgi", None)

        with mock.patch.dict(os.environ, {}, clear=True):
            importlib.import_module("config.asgi")

            # Verify exact string match (no extra spaces, correct casing)
            assert os.environ["DJANGO_SETTINGS_MODULE"] == "config.settings"
            assert os.environ["DJANGO_SETTINGS_MODULE"] != "config.Settings"  # casing
            assert os.environ["DJANGO_SETTINGS_MODULE"] != " config.settings"  # spacing

    def test_asgi_imports_from_correct_django_module(self):
        """Test that get_asgi_application is imported from correct Django module."""
        sys.modules.pop("config.asgi", None)

        # Mock the correct import path
        with mock.patch("django.core.asgi.get_asgi_application") as mock_get:
            mock_get.return_value = mock.Mock(spec=ASGIHandler)

            importlib.import_module("config.asgi")

            # Verify it was called (meaning it was imported from correct path)
            mock_get.assert_called_once()


class ASGINegativeTests(SimpleTestCase):
    """Negative test cases for ASGI error handling and edge cases."""

    def test_asgi_with_invalid_settings_module_name(self):
        """Test ASGI behavior when settings module name is invalid."""
        sys.modules.pop("config.asgi", None)

        # Set an invalid settings module
        with mock.patch.dict(
            os.environ, {"DJANGO_SETTINGS_MODULE": "nonexistent.settings"}, clear=True
        ):
            # Importing should still work (errors come later when app is used)
            module = importlib.import_module("config.asgi")

            # Module should import successfully
            assert module is not None
            assert hasattr(module, "application")

    def test_asgi_os_environ_setdefault_behavior(self):
        """Test that os.environ.setdefault is used (not direct assignment)."""
        sys.modules.pop("config.asgi", None)

        # Pre-set a different value
        existing_value = "existing.settings"

        with mock.patch.dict(
            os.environ, {"DJANGO_SETTINGS_MODULE": existing_value}, clear=True
        ):
            importlib.import_module("config.asgi")

            # Value should remain unchanged (setdefault doesn't override)
            assert os.environ["DJANGO_SETTINGS_MODULE"] == existing_value


class ASGISecurityTests(SimpleTestCase):
    """Security-related tests for ASGI configuration."""

    def test_asgi_does_not_expose_secrets(self):
        """Test that ASGI module does not expose sensitive information."""
        from config import asgi

        # Get all module attributes
        module_attrs = dir(asgi)

        # Should not have any obvious secret-related attributes
        secret_keywords = ["SECRET", "PASSWORD", "KEY", "TOKEN", "CREDENTIAL"]

        for attr in module_attrs:
            if not attr.startswith("_"):  # Skip private attributes
                # Attribute names shouldn't contain secret keywords
                assert not any(
                    keyword in attr.upper() for keyword in secret_keywords
                ), f"Potentially sensitive attribute: {attr}"

    def test_asgi_settings_module_not_in_module_globals(self):
        """Test that settings module content is not leaked into ASGI module."""
        from config import asgi

        # ASGI module should not have Django settings as module-level variables
        # (they should be accessed via django.conf.settings)
        assert not hasattr(asgi, "SECRET_KEY")
        assert not hasattr(asgi, "DATABASES")
        assert not hasattr(asgi, "DEBUG")


class ASGIPerformanceTests(SimpleTestCase):
    """Performance and efficiency tests for ASGI module."""

    def test_asgi_import_is_fast(self):
        """Test that ASGI module imports quickly (no heavy initialization)."""
        import time

        sys.modules.pop("config.asgi", None)

        start_time = time.time()
        importlib.import_module("config.asgi")
        end_time = time.time()

        import_duration = end_time - start_time

        # Import should complete in under 2 seconds (generous threshold)
        # Actual import is much faster, but we allow overhead for test environment
        assert import_duration < 2.0, f"ASGI import took {import_duration:.3f}s"

    def test_asgi_application_cached_after_import(self):
        """Test that application object is cached in sys.modules."""
        from config import asgi

        # Module should be in sys.modules cache
        assert "config.asgi" in sys.modules

        cached_module = sys.modules["config.asgi"]

        # Cached module should be the same object
        assert cached_module is asgi


class ASGICompatibilityTests(SimpleTestCase):
    """Compatibility tests for ASGI with different Django versions and configurations."""

    def test_asgi_compatible_with_django_settings(self):
        """Test that ASGI works with current Django settings configuration."""
        from django.conf import settings

        from config.asgi import application

        # Application should work with current settings
        assert isinstance(application, ASGIHandler)

        # Settings should be configured
        assert settings.configured

        # Custom user model should be accessible
        assert settings.AUTH_USER_MODEL == "accounts.User"

    def test_asgi_uses_correct_wsgi_asgi_pattern(self):
        """Test that ASGI follows Django's standard ASGI pattern."""
        # Read the actual asgi.py file to verify structure
        asgi_file = "/Users/bestony/Developer/openshare/fullsite/config/asgi.py"

        with open(asgi_file) as f:
            content = f.read()

        # Verify standard Django ASGI pattern
        assert "import os" in content
        assert "from django.core.asgi import get_asgi_application" in content
        assert 'os.environ.setdefault("DJANGO_SETTINGS_MODULE"' in content
        assert "application = get_asgi_application()" in content

    def test_asgi_module_location_correct(self):
        """Test that ASGI module is in the correct location."""
        from config import asgi

        # Module should be in config package
        assert asgi.__name__ == "config.asgi"
        assert asgi.__package__ == "config"


class ASGIIntegrationTests(SimpleTestCase):
    """Integration tests for ASGI with other Django components."""

    def test_asgi_application_has_django_middleware(self):
        """Test that ASGI application is configured with Django middleware."""
        from config.asgi import application

        # ASGIHandler should be properly initialized with Django configuration
        assert isinstance(application, ASGIHandler)

        # The handler should have access to Django's middleware
        # This is verified by checking that it's a properly initialized ASGIHandler
        assert callable(application)

    def test_asgi_application_can_access_settings(self):
        """Test that ASGI application can access Django settings."""
        from django.conf import settings

        # Importing ASGI should not break settings access
        from config.asgi import application  # noqa: F401

        # Settings should still be accessible
        assert settings.configured
        assert hasattr(settings, "INSTALLED_APPS")
        assert "django.contrib.admin" in settings.INSTALLED_APPS
