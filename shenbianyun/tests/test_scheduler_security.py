"""Scheduler leases must not delete a successor's lock."""

from django.core.cache import caches
from django.test import SimpleTestCase

from shenbianyun.scheduler import _distributed_lock


class SchedulerLeaseTests(SimpleTestCase):
    def test_stale_worker_cannot_release_successor_lease(self):
        cache = caches["scheduler_lock"]
        key = "shenbianyun:scheduler:lock:security-test"
        cache.delete(key)
        try:
            with _distributed_lock("security-test", timeout=30) as acquired:
                self.assertTrue(acquired)
                cache.set(key, "successor", timeout=30)
            self.assertEqual(cache.get(key), "successor")
            with _distributed_lock("security-test", timeout=30) as acquired:
                self.assertFalse(acquired)
        finally:
            cache.delete(key)
