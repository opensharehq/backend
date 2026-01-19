"""Django app configuration for accounts."""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Configuration for the accounts app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "用户管理"

    def ready(self):
        """Import signal handlers when Django starts."""
        import accounts.signals  # noqa: F401
