"""Tests for homepage user search view."""

import json
import re
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts.models import UserProfile
from homepage import views as homepage_views
from homepage.cache import get_search_cache_version


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class HomepageUserSearchTests(TestCase):
    """Test suite for the homepage user search experience."""

    def setUp(self):
        """Create reusable users and related data."""
        self.User = get_user_model()
        self.search_url = reverse("homepage:search")
        self.factory = RequestFactory()

        self.alice = self.User.objects.create_user(
            username="alice",
            email="alice@example.com",
            password="pass1234",
            first_name="Alice",
            last_name="Wonder",
        )
        UserProfile.objects.create(
            user=self.alice,
            bio="Core contributor",
            company="OpenShare",
            location="上海",
        )

        self.bob = self.User.objects.create_user(
            username="bob",
            email="bob@example.com",
            password="pass1234",
            first_name="Bob",
            last_name="Builder",
        )
        UserProfile.objects.create(
            user=self.bob,
            bio="Community maintainer",
            company="自由职业者",
            location="北京",
        )

    def _extract_results_payload(self, response):
        """Extract search results JSON payload embedded by json_script."""
        html = response.content.decode("utf-8")
        match = re.search(
            r'<script id="search-results-data" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "Expected search-results-data payload in response.")
        return json.loads(match.group(1))

    def test_redirects_on_exact_username_match(self):
        """Exact matches should redirect to the public profile page."""
        response = self.client.get(self.search_url, {"q": "Alice"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("public_profile", args=["alice"]))

    def test_partial_search_returns_results_page(self):
        """Partial matches render the results template with data."""
        response = self.client.get(self.search_url, {"q": "example"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "homepage/search_results.html")
        payload = self._extract_results_payload(response)
        usernames = {item["username"] for item in payload}
        self.assertIn("alice", usernames)
        self.assertIn("bob", usernames)
        self.assertContains(response, "search-results-data")

    def test_location_filter_limits_results(self):
        """Location filter narrows the result set to the selected city."""
        response = self.client.get(
            self.search_url,
            {"q": "example", "location": "上海"},
        )

        self.assertEqual(response.status_code, 200)
        results = self._extract_results_payload(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["username"], "alice")
        self.assertEqual(results[0]["location"], "上海")

    def test_company_filter_limits_results(self):
        """Company filter narrows the result set to the selected organisation."""
        response = self.client.get(
            self.search_url,
            {"q": "example", "company": "OpenShare"},
        )

        self.assertEqual(response.status_code, 200)
        results = self._extract_results_payload(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["username"], "alice")
        self.assertEqual(results[0]["company"], "OpenShare")

    def test_empty_query_redirects_home(self):
        """Empty queries should redirect back to the homepage."""
        response = self.client.get(self.search_url, {"q": ""})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("homepage:index"))

    def test_results_context_limits_total_matches(self):
        """Context contains metadata for the filter summary."""
        response = self.client.get(self.search_url, {"q": "example"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "共找到 2 位用户")
        self.assertContains(response, 'option value="relevance" selected')

    def test_results_page_only_exposes_supported_filter_controls(self):
        """The results page should only render filters supported by the backend."""
        response = self.client.get(self.search_url, {"q": "example"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="location"')
        self.assertContains(response, 'name="company"')
        self.assertContains(response, 'option value="username"')
        self.assertNotContains(response, 'name="min_points"')
        self.assertNotContains(response, 'option value="points_desc"')
        self.assertNotContains(response, 'option value="points_asc"')

    def test_invalid_sort_value_falls_back_to_relevance(self):
        """Unsupported sort values should fall back to the default ordering."""
        request = self.factory.get(
            self.search_url,
            {"q": "example", "sort": "points_desc"},
        )
        filters = homepage_views.SearchFilters.from_request(request)

        self.assertEqual(filters.sort, homepage_views.SearchFilters.DEFAULT_SORT)

        response = self.client.get(
            self.search_url, {"q": "example", "sort": "points_desc"}
        )
        self.assertContains(response, 'option value="relevance" selected')

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            }
        }
    )
    def test_search_results_cached_for_repeat_queries(self):
        """Repeat searches reuse cached context instead of hitting the database."""
        cache.clear()
        params = {"q": "example"}

        initial_response = self.client.get(self.search_url, params)
        self.assertEqual(initial_response.status_code, 200)
        self.assertEqual(len(self._extract_results_payload(initial_response)), 2)

        initial_version = get_search_cache_version()

        cached_again = self.client.get(self.search_url, params)
        self.assertEqual(len(self._extract_results_payload(cached_again)), 2)

        filters = homepage_views.SearchFilters()
        cache_key = homepage_views._build_search_cache_key(
            query="example",
            filters=filters,
        )
        cached_context = cache.get(cache_key)
        self.assertIsNotNone(cached_context)

        charlie = self.User.objects.create_user(
            username="charlie",
            email="charlie@example.com",
            password="pass1234",
            first_name="Charlie",
            last_name="Chaplin",
        )
        UserProfile.objects.create(
            user=charlie,
            bio="New contributor",
            company="OpenShare",
            location="广州",
        )

        updated_version = get_search_cache_version()
        self.assertNotEqual(initial_version, updated_version)

        refreshed_response = self.client.get(self.search_url, params)
        usernames = {
            item["username"]
            for item in self._extract_results_payload(refreshed_response)
        }
        self.assertIn("charlie", usernames)
        cache.clear()

    def test_cached_search_reuses_payload_without_serializing_users_again(self):
        """A cache hit should bypass result serialization for repeated queries."""
        cache.clear()
        params = {"q": "example"}

        with patch(
            "homepage.views._serialize_user",
            wraps=homepage_views._serialize_user,
        ) as serializer:
            first_response = self.client.get(self.search_url, params)

        self.assertEqual(first_response.status_code, 200)
        self.assertGreater(serializer.call_count, 0)

        with patch(
            "homepage.views._serialize_user",
            wraps=homepage_views._serialize_user,
        ) as serializer:
            second_response = self.client.get(self.search_url, params)

        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(serializer.call_count, 0)
        self.assertEqual(
            self._extract_results_payload(first_response),
            self._extract_results_payload(second_response),
        )

    def test_cached_search_hit_avoids_database_queries(self):
        """A warm cache hit should render the results page without touching the database."""
        filters = homepage_views.SearchFilters()
        cache_key = homepage_views._build_search_cache_key(
            query="example",
            filters=filters,
        )
        cache.set(
            cache_key,
            {
                "query": "example",
                "results": [
                    {
                        "username": "cached-user",
                        "display_name": "Cached User",
                        "bio": "cached bio",
                        "company": "Cached Co",
                        "location": "Shanghai",
                        "profile_url": "/cached-user/",
                        "avatar_url": "https://example.com/avatar.png",
                    }
                ],
                "results_count": 1,
                "max_results": homepage_views.MAX_SEARCH_RESULTS,
                "filters": {
                    "location": "",
                    "company": "",
                    "sort": homepage_views.SearchFilters.DEFAULT_SORT,
                },
                "available_locations": [],
                "available_companies": [],
                "page_size": homepage_views.PAGE_SIZE,
            },
            homepage_views.SEARCH_RESULTS_CACHE_TIMEOUT,
        )
        request = self.factory.get(self.search_url, {"q": "example"})

        with self.assertNumQueries(0):
            response = homepage_views.user_search(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn("cached-user", response.content.decode("utf-8"))

    def test_cached_search_short_circuits_with_cached_context(self):
        """When cached context exists the view should return it immediately."""
        cached_context = {
            "query": "example",
            "results": [],
            "results_count": 0,
            "filters": {},
        }
        request = self.factory.get(self.search_url, {"q": "example"})

        with (
            patch("homepage.views.cache") as mock_cache,
            patch("homepage.views.render") as mock_render,
        ):
            mock_cache.get.return_value = cached_context
            mock_render.return_value = HttpResponse("cached")

            response = homepage_views.user_search(request)

        mock_cache.get.assert_called_once()
        mock_cache.set.assert_not_called()
        mock_render.assert_called_once_with(
            request,
            "homepage/search_results.html",
            cached_context,
        )
        self.assertEqual(response, mock_render.return_value)

    def test_exact_match_redirect_survives_warm_partial_search_cache(self):
        """User cache invalidation should prevent stale partial pages blocking redirects."""
        cache.clear()
        params = {"q": "ali"}

        initial_response = self.client.get(self.search_url, params)

        self.assertEqual(initial_response.status_code, 200)
        self.assertTemplateUsed(initial_response, "homepage/search_results.html")

        cache_key = homepage_views._build_search_cache_key(
            query="ali",
            filters=homepage_views.SearchFilters(),
        )
        self.assertIsNotNone(cache.get(cache_key))

        ali = self.User.objects.create_user(
            username="ali",
            email="ali@example.com",
            password="pass1234",
            first_name="Ali",
            last_name="Newcomer",
        )
        UserProfile.objects.create(
            user=ali,
            bio="Joined after the search cache warmed up",
            company="OpenShare",
            location="杭州",
        )

        redirected_response = self.client.get(self.search_url, params)

        self.assertEqual(redirected_response.status_code, 302)
        self.assertEqual(
            redirected_response.url,
            reverse("public_profile", args=["ali"]),
        )
