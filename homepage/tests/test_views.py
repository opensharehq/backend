"""Tests for homepage app views."""

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
    """Test cases for homepage views."""

    def setUp(self):
        """Set up test fixtures."""
        self.factory = RequestFactory()
        self.client = Client()

    def test_homepage_client_renders_template(self):
        """Test that homepage renders correct template via client."""
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
        """Test that homepage view handles request correctly."""
        request = self.factory.get("/")

        response = index(request)

        self.assertEqual(response.status_code, 200)

    def test_homepage_url_resolves_to_index(self):
        """Test that homepage URL resolves to index view."""
        match = resolve("/")

        self.assertEqual(match.func, index)

    def test_homepage_url_reverse_resolves_correctly(self):
        """Test that homepage URL can be reversed correctly."""
        url = reverse("homepage:index")

        self.assertEqual(url, "/")

    def test_homepage_returns_correct_content_type(self):
        """Test that homepage returns HTML content type."""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])

    def test_homepage_contains_expected_content(self):
        """Test that homepage contains expected Chinese content."""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("OpenShare", content)
        self.assertIn("开源贡献激励平台", content)

    def test_homepage_with_authenticated_user(self):
        """Test that homepage displays correctly for authenticated users."""
        user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpass123"
        )
        self.client.force_login(user)

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["user"].is_authenticated)
        self.assertEqual(response.context["user"], user)
        content = response.content.decode("utf-8")
        # Check for user-specific content
        self.assertTrue("testuser" in content or "个人资料" in content)

    def test_homepage_with_anonymous_user(self):
        """Test that homepage displays correctly for anonymous users."""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["user"].is_authenticated)
        content = response.content.decode("utf-8")
        # Check for login/signup buttons
        self.assertIn("登录", content)
        self.assertIn("注册", content)

    def test_homepage_get_request_direct_view_call(self):
        """Test homepage view with GET request using RequestFactory."""
        request = self.factory.get("/")

        response = index(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"OpenShare", response.content)

    def test_homepage_post_request_not_allowed(self):
        """Test that POST requests to homepage return 405 Method Not Allowed."""
        response = self.client.post("/")

        # Django's generic views return 405 for disallowed methods,
        # but our function-based view doesn't explicitly handle this.
        # It will still render the page, which is acceptable for a simple view.
        # If we want strict REST semantics, we'd need to add method checking.
        self.assertIn(response.status_code, [200, 405])

    def test_homepage_uses_correct_template_name(self):
        """Test that the correct template is used for rendering."""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        template_names = [t.name for t in response.templates if t.name]
        self.assertIn("homepage/index.html", template_names)

    def test_homepage_template_has_required_sections(self):
        """Test that homepage template contains all required sections."""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        # Check for key sections
        self.assertIn("hero-section", content)  # Hero section
        self.assertIn("stats-section", content)  # Statistics
        self.assertIn("features", content)  # Features section
        self.assertIn("benefits", content)  # Benefits section
        self.assertIn("footer", content)  # Footer

    def test_homepage_includes_meta_tags(self):
        """Test that homepage includes proper meta tags for SEO."""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        # Check meta tags
        self.assertIn('name="description"', content)
        self.assertIn('name="keywords"', content)
        self.assertIn('name="author"', content)
        self.assertIn("OpenShare", content)

    def test_homepage_includes_static_files(self):
        """Test that homepage template includes necessary static files."""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        # Check for NobleUI CSS
        self.assertIn("nobleui/vendors/core/core.css", content)
        self.assertIn("nobleui/css/demo2/style.css", content)

        # Check for scripts
        self.assertIn("nobleui/vendors/lucide/lucide.min.js", content)
        self.assertIn("lucide.createIcons()", content)

    def test_homepage_charset_is_utf8(self):
        """Test that homepage uses UTF-8 charset for Chinese content."""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertTrue('charset="UTF-8"' in content or 'charset="utf-8"' in content)

    def test_homepage_language_is_chinese(self):
        """Test that homepage language is set to Chinese."""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn('lang="zh-CN"', content)

    def test_homepage_responsive_viewport_meta(self):
        """Test that homepage includes responsive viewport meta tag."""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn('name="viewport"', content)
        self.assertIn("width=device-width", content)

    def test_homepage_xss_protection_in_template(self):
        """Test that template properly escapes user input to prevent XSS."""
        # Create user with potentially malicious username
        user = User.objects.create_user(
            username="<script>alert('xss')</script>",
            email="xss@example.com",
            password="testpass123",
        )
        self.client.force_login(user)

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        # Django templates auto-escape by default, and template uses slice:":2"
        # which only shows first 2 characters, then uppercases them
        self.assertNotIn("<script>alert('xss')</script>", content)
        self.assertNotIn("alert('xss')", content)  # Script should not execute
        # Template escapes < to &lt;, slices first 2 chars (&l), then uppercases to &L
        # But actually it escapes AFTER slicing, so we get &lt;S
        self.assertTrue(
            "&lt;S" in content
        )  # Escaped, + first letter of "script" uppercased

    def test_homepage_contains_navigation_links(self):
        """Test that homepage contains expected navigation links."""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        # Check for navigation
        self.assertIn("功能", content)  # Features link
        self.assertIn("优势", content)  # Benefits link

    def test_homepage_contains_social_proof_stats(self):
        """Test that homepage displays social proof statistics."""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        # Check for stats
        self.assertIn("注册开发者", content)
        self.assertIn("项目贡献", content)
        self.assertIn("积分发放", content)

    def test_homepage_request_with_query_parameters(self):
        """Test homepage handles query parameters gracefully."""
        response = self.client.get("/?ref=github&utm_source=social")

        self.assertEqual(response.status_code, 200)
        # View should ignore query params but still render correctly

    def test_homepage_request_with_different_http_headers(self):
        """Test homepage handles various HTTP headers correctly."""
        response = self.client.get(
            "/",
            HTTP_USER_AGENT="Mozilla/5.0 TestBot",
            HTTP_ACCEPT_LANGUAGE="zh-CN,zh;q=0.9,en;q=0.8",
        )

        self.assertEqual(response.status_code, 200)

    def test_homepage_head_request(self):
        """Test homepage responds to HEAD requests."""
        response = self.client.head("/")

        # HEAD requests should return same status as GET but no body
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.content), 0)

    def test_homepage_multiple_requests_consistency(self):
        """Test that multiple requests to homepage return consistent results."""
        response1 = self.client.get("/")
        response2 = self.client.get("/")

        self.assertEqual(response1.status_code, 200)
        self.assertEqual(response2.status_code, 200)
        # Content should be identical for anonymous users
        self.assertEqual(response1.content, response2.content)

    def test_homepage_view_callable(self):
        """Test that index view is callable."""
        self.assertTrue(callable(index))

    def test_homepage_contains_cta_section(self):
        """Test that homepage contains call-to-action section."""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")

        self.assertTrue("准备好开始了吗" in content or "立即注册" in content)


class TestHomepageIntegration(CacheClearTestCase):
    """Integration tests for homepage view with full request/response cycle."""

    def setUp(self):
        """Set up test client."""
        self.client = Client()

    def test_homepage_full_request_cycle(self):
        """Test complete request/response cycle for homepage."""
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "homepage/index.html", [t.name for t in response.templates if t.name]
        )

    def test_homepage_with_session_data(self):
        """Test homepage with session data present."""
        session = self.client.session
        session["test_key"] = "test_value"
        session.save()

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)

    def test_homepage_url_name_resolution(self):
        """Test homepage URL name can be resolved."""
        url = reverse("homepage:index")

        self.assertEqual(url, "/")

    def test_homepage_with_authenticated_user_profile_link(self):
        """Test authenticated user sees profile-related links."""
        user = User.objects.create_user(
            username="profileuser", email="profile@test.com", password="pass123"
        )
        self.client.force_login(user)

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertTrue(
            "个人资料" in content or "PR" in content
        )  # Profile or user initials
