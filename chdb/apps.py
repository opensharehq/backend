"""ClickHouse 数据库集成应用配置."""

from django.apps import AppConfig


class ChdbConfig(AppConfig):
    """ClickHouse 数据库集成应用配置类."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "chdb"
