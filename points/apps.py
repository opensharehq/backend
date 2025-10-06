"""Django app configuration for the points app."""

from django.apps import AppConfig


class PointsConfig(AppConfig):
    """Configuration for the Points application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "points"
    verbose_name = "积分系统"
