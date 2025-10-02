from django.test import RequestFactory, TestCase, override_settings
from django.urls import resolve

from homepage.views import index


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)
class HomepageViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_homepage_client_renders_template(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            any(
                template.name == "homepage/index.html"
                for template in response.templates
                if template.name is not None
            )
        )

    def test_homepage_view_handles_request(self):
        request = self.factory.get("/")

        response = index(request)

        self.assertEqual(response.status_code, 200)

    def test_homepage_url_resolves_to_index(self):
        match = resolve("/")

        self.assertEqual(match.func, index)
