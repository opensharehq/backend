"""身边云模块 Django AppConfig 与启动钩子."""

import logging
import os
import sys

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class ShenbianyunConfig(AppConfig):
    """身边云模块应用配置, 负责在合适时机启动定时任务调度器."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "shenbianyun"
    verbose_name = "身边云平台对接"

    def ready(self):
        """应用就绪时启动定时任务调度器, 跳过非服务进程."""
        # Determine if we're inside a manage.py invocation
        is_manage = len(sys.argv) > 1 and sys.argv[0].endswith("manage.py")
        is_runserver = is_manage and sys.argv[1] in ("runserver", "runserver_plus")

        # Skip for non-server management commands (migrate, shell, makemigrations, etc.)
        if is_manage and not is_runserver:
            return

        # For dev server with autoreload: only start in the reloader child process
        # to avoid double-starting the scheduler.
        # - Django's runserver sets RUN_MAIN=true in the child process
        # - runserver_plus (Werkzeug) sets WERKZEUG_RUN_MAIN=true instead
        if is_runserver:
            is_reloader_child = (
                os.environ.get("RUN_MAIN") == "true"
                or os.environ.get("WERKZEUG_RUN_MAIN") == "true"
            )
            if not is_reloader_child:
                return

        # For production (gunicorn/uvicorn): ready() is called once, start normally
        from .scheduler import start_scheduler

        try:
            start_scheduler()
        except Exception:
            logger.exception("身边云定时任务调度器启动失败")
