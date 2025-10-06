"""Tests for homepage app views."""

from django.test import RequestFactory, TestCase, override_settings
from django.urls import resolve

from homepage.views import index


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    },
)
class HomepageViewTests(TestCase):
    """Test cases for homepage views."""

    def setUp(self):
        """Set up test fixtures."""
        self.factory = RequestFactory()

    def test_homepage_client_renders_template(self):
        """Test that homepage renders correct template via client."""
        response = self.client.get("/")

        assert response.status_code == 200
        assert any(
            template.name == "homepage/index.html"
            for template in response.templates
            if template.name is not None
        )

    def test_homepage_view_handles_request(self):
        """Test that homepage view handles request correctly."""
        request = self.factory.get("/")

        response = index(request)

        assert response.status_code == 200

    def test_homepage_url_resolves_to_index(self):
        """Test that homepage URL resolves to index view."""
        match = resolve("/")

        assert match.func == index
