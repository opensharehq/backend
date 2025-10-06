"""Django app configuration for shop application."""

from django.apps import AppConfig


class ShopConfig(AppConfig):
    """Configuration for shop application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "shop"
    verbose_name = "积分商城"
