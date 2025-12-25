"""Configuration for the labels Django application."""

from django.apps import AppConfig


class LabelsConfig(AppConfig):
    """App configuration for the labels app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "labels"
    verbose_name = "标签管理"
