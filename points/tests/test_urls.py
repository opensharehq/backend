"""Tests for points URL configuration."""

from django.test import TestCase
from django.urls import reverse


class URLTests(TestCase):
    """Test URL configuration."""

    def test_my_points_url_resolves(self):
        """Test that my_points URL resolves correctly."""
        url = reverse("points:my_points")

        assert url == "/accounts/points/"
