"""Configuration for points application."""

from django.apps import AppConfig


class PointsConfig(AppConfig):
    """Points application configuration."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "points"
