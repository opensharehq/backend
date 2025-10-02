from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase


class UserModelTests(TestCase):
    def test_user_defaults_active(self):
        user = get_user_model().objects.create_user(
            username="active-user",
            email="active@example.com",
            password="password123",
        )

        self.assertTrue(user.is_active)


class UserAdminRegistrationTests(TestCase):
    databases = {"default"}

    def test_user_registered_with_admin_site(self):
        from accounts import admin as accounts_admin

        user_model = get_user_model()

        self.assertIn(user_model, admin.site._registry)
        self.assertIsInstance(
            admin.site._registry[user_model],
            accounts_admin.UserAdmin,
        )
