"""APScheduler configuration for Shenbianyun periodic tasks."""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from django_apscheduler.jobstores import DjangoJobStore

logger = logging.getLogger(__name__)


def sync_signed_users_job():
    """定时同步身边云签约用户到本地数据库."""
    from .services import sync_signed_users

    try:
        result = sync_signed_users()
        logger.info(
            "签约用户同步完成: pages=%d, created=%d, updated=%d",
            result["pages"],
            result["created"],
            result["updated"],
        )
    except Exception:
        logger.exception("身边云签约用户同步失败")


def batch_payment_job():
    """定时批量付款: 从已批准的提现申请发起身边云付款."""
    from .services import batch_payment

    try:
        result = batch_payment()
        logger.info("批量付款任务完成: %s", result)
    except Exception:
        logger.exception("批量付款任务失败")


def check_payment_status_job():
    """定时查询付款结果: 检查未完成的付款记录状态."""
    from .services import check_payment_status

    try:
        result = check_payment_status()
        logger.info("付款状态查询任务完成: %s", result)
    except Exception:
        logger.exception("付款状态查询任务失败")


def start_scheduler():
    """
    Initialize and start the APScheduler background scheduler.

    Uses DjangoJobStore (database-backed) to ensure that only one node
    in a multi-node deployment executes each scheduled job at a time.
    """
    scheduler = BackgroundScheduler()
    scheduler.add_jobstore(DjangoJobStore(), "default")

    scheduler.add_job(
        sync_signed_users_job,
        trigger=IntervalTrigger(minutes=3),
        id="sync_signed_users",
        max_instances=1,
        replace_existing=True,
    )

    scheduler.add_job(
        batch_payment_job,
        trigger=IntervalTrigger(minutes=5),
        id="batch_payment",
        max_instances=1,
        replace_existing=True,
    )

    scheduler.add_job(
        check_payment_status_job,
        trigger=IntervalTrigger(minutes=5),
        id="check_payment_status",
        max_instances=1,
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "身边云定时任务调度器已启动（同步签约用户:3min, 批量付款:5min, 付款状态查询:5min）"
    )
