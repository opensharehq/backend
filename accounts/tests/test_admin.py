"""Tests for accounts admin."""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase


class UserAdminRegistrationTests(TestCase):
    """Test cases for User model admin registration."""

    databases = {"default"}

    def test_user_registered_with_admin_site(self):
        """Test that User model is registered with Django admin."""
        from accounts import admin as accounts_admin

        user_model = get_user_model()

        assert user_model in admin.site._registry
        assert isinstance(admin.site._registry[user_model], accounts_admin.UserAdmin)
