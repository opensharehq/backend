"""APScheduler configuration for Shenbianyun periodic tasks."""

import logging
import socket
from contextlib import contextmanager

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from django.conf import settings
from django.core.cache import caches
from django_apscheduler.jobstores import DjangoJobStore

logger = logging.getLogger(__name__)

# 分布式锁 key 前缀; 不同 Job 使用不同 key, 仅同 Job 互斥
_LOCK_PREFIX = "shenbianyun:scheduler:lock:"
# 节点标识, 仅用于日志区分是哪个节点拿到/释放了锁
_NODE_ID = socket.gethostname()


@contextmanager
def _distributed_lock(name: str, timeout: int):
    """
    基于专用 ``scheduler_lock`` cache 的跨节点互斥锁.

    cache.add() 在 Redis 后端等价于 SET NX EX, 是原子操作, 多节点同时
    调用只会有一个返回 True. 拿到锁的节点执行任务, 其他节点直接跳过本轮.
    timeout 作为节点崩溃时的兜底自动释放, 应略小于任务调度间隔.

    本地无 Redis 时该 alias 会回落到 LocMemCache (见 build_cache_settings),
    避免使用 DummyCache 导致 add() 恒返回 True、锁形同虚设.
    """
    cache = caches["scheduler_lock"]
    key = f"{_LOCK_PREFIX}{name}"
    acquired = cache.add(key, _NODE_ID, timeout)
    try:
        yield acquired
    finally:
        if acquired:
            try:
                cache.delete(key)
            except Exception:
                # 锁释放失败不影响业务, TTL 会兜底
                logger.warning("释放分布式锁失败: %s", key, exc_info=True)


def sync_signed_users_job():
    """定时同步身边云签约用户到本地数据库."""
    from .services import sync_signed_users

    # 锁 TTL 设为 150s, 小于 3min 调度间隔, 防止节点崩溃时长期阻塞
    with _distributed_lock("sync_signed_users", timeout=150) as acquired:
        if not acquired:
            logger.info("签约用户同步: 另一节点持有锁, 本节点(%s)跳过本轮", _NODE_ID)
            return
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

    # 锁 TTL 设为 270s, 小于 5min 调度间隔
    with _distributed_lock("batch_payment", timeout=270) as acquired:
        if not acquired:
            logger.info("批量付款: 另一节点持有锁, 本节点(%s)跳过本轮", _NODE_ID)
            return
        try:
            result = batch_payment()
            logger.info("批量付款任务完成: %s", result)
        except Exception:
            logger.exception("批量付款任务失败")


def check_payment_status_job():
    """定时查询付款结果: 检查未完成的付款记录状态."""
    from .services import check_payment_status

    with _distributed_lock("check_payment_status", timeout=270) as acquired:
        if not acquired:
            logger.info("付款状态查询: 另一节点持有锁, 本节点(%s)跳过本轮", _NODE_ID)
            return
        try:
            result = check_payment_status()
            logger.info("付款状态查询任务完成: %s", result)
        except Exception:
            logger.exception("付款状态查询任务失败")


def start_scheduler():
    """
    Initialize and start the APScheduler background scheduler.

    在配置了 Redis 的环境 (生产) 使用 DjangoJobStore 持久化 Job 元数据,
    便于 admin 可视与节点重启后恢复; 本地开发未配置 Redis 时使用
    MemoryJobStore, 避免 SQLite 写锁竞争 (database is locked) 偶发
    阻断后续触发. 多节点单点执行由 _distributed_lock 兜底.
    """
    scheduler = BackgroundScheduler()
    if getattr(settings, "REDIS_URL", ""):
        scheduler.add_jobstore(DjangoJobStore(), "default")
    else:
        scheduler.add_jobstore(MemoryJobStore(), "default")

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
