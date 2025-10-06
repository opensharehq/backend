"""Django app configuration for homepage."""

from django.apps import AppConfig


class HomepageConfig(AppConfig):
    """Configuration for the homepage app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "homepage"
    verbose_name = "首页"
