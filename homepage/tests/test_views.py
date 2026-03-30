"""Focused regression tests for the homepage index view."""

from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, override_settings
from django.urls import resolve, reverse

from common.test_utils import CacheClearTestCase
from homepage.views import index

User = get_user_model()


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    },
)
class HomepageViewTests(CacheClearTestCase):
    """Homepage tests that lock user-visible behavior rather than presentation noise."""

    def setUp(self):
        """Set up a request factory and client."""
        self.factory = RequestFactory()
        self.client = Client()

    def test_homepage_renders_index_template_with_html_response(self):
        """GET / should render the homepage template as HTML."""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])
        self.assertIn(
            "homepage/index.html",
            [template.name for template in response.templates if template.name],
        )
        self.assertContains(response, "OpenShare")
        self.assertContains(response, "开源贡献激励平台")

    def test_homepage_supports_get_and_head_requests(self):
        """GET should render content and HEAD should reuse the same status without a body."""
        request = self.factory.get("/")
        response = index(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"OpenShare", response.content)

        head_response = self.client.head("/")
        self.assertEqual(head_response.status_code, 200)
        self.assertEqual(head_response.content, b"")

    def test_homepage_post_matches_current_rendering_contract(self):
        """POST / currently renders the same landing page instead of rejecting the method."""
        response = self.client.post("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "homepage/index.html",
            [template.name for template in response.templates if template.name],
        )
        self.assertContains(response, "OpenShare")

    def test_homepage_url_resolves_and_reverses(self):
        """The homepage route should keep resolving to the index view."""
        self.assertEqual(resolve("/").func, index)
        self.assertEqual(reverse("homepage:index"), "/")

    def test_anonymous_users_see_sign_in_and_sign_up_links(self):
        """Anonymous visitors should be prompted to sign in or register."""
        response = self.client.get("/")
        content = response.content.decode("utf-8")

        self.assertFalse(response.context["user"].is_authenticated)
        self.assertIn(f'href="{reverse("accounts:sign_in")}"', content)
        self.assertIn(f'href="{reverse("accounts:sign_up")}"', content)

    def test_authenticated_users_see_profile_and_logout_links(self):
        """Authenticated visitors should get account navigation instead of auth CTAs."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(user)

        response = self.client.get("/")
        content = response.content.decode("utf-8")

        self.assertTrue(response.context["user"].is_authenticated)
        self.assertEqual(response.context["user"], user)
        self.assertIn(f'href="{reverse("accounts:profile")}"', content)
        self.assertIn(f'href="{reverse("accounts:logout")}"', content)
        self.assertIn("个人资料", content)

    def test_homepage_contains_core_sections_and_cta_copy(self):
        """The landing page should keep its core navigation, stats, and CTA content."""
        response = self.client.get("/")
        content = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn("hero-section", content)
        self.assertIn("stats-section", content)
        self.assertIn('id="features"', content)
        self.assertIn('id="benefits"', content)
        self.assertIn("注册开发者", content)
        self.assertIn("项目贡献", content)
        self.assertIn("积分发放", content)
        self.assertIn("准备好开始了吗？", content)

    def test_homepage_escapes_username_fragments_in_user_menu(self):
        """User-controlled names should still be escaped before they reach the UI."""
        user = User.objects.create_user(
            username="<script>alert('xss')</script>",
            email="xss@example.com",
            password="testpass123",
        )
        self.client.force_login(user)

        response = self.client.get("/")
        content = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("<script>alert('xss')</script>", content)
        self.assertNotIn("alert('xss')", content)
        self.assertIn("&lt;S", content)

    def test_homepage_handles_query_parameters_without_changing_content(self):
        """Tracking parameters should not change the rendered landing page."""
        response = self.client.get("/?ref=github&utm_source=social")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "OpenShare")

    def test_homepage_anonymous_responses_are_stable_between_requests(self):
        """Anonymous homepage responses should be deterministic across repeated requests."""
        first_response = self.client.get("/")
        second_response = self.client.get("/")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response.content, second_response.content)
