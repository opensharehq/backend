"""Helper utilities for Django settings configuration."""

from __future__ import annotations

from typing import Any


def build_cache_settings(
    debug: bool, redis_url: str, testing: bool = False
) -> dict[str, Any]:
    """
    Return Django cache configuration based on debug flag and Redis URL.

    Always provides ``social_exchange`` and ``scheduler_lock`` cache aliases.
    When Redis is available they are shared with the default cache; otherwise
    they fall back to in-process LocMemCache so local development without
    Redis still works (DummyCache.add() always returns True and would defeat
    the distributed lock semantics).
    """
    if redis_url:
        # ``ssl_cert_reqs`` is only accepted by redis-py for TLS connections
        # (``rediss://``). Passing it on plain ``redis://`` URLs raises
        # ``TypeError`` on redis-py 7+. Build OPTIONS conditionally.
        options: dict[str, Any] = {}
        if redis_url.startswith("rediss://"):
            options["ssl_cert_reqs"] = None
        redis_backend: dict[str, Any] = {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": redis_url,
        }
        if options:
            redis_backend["OPTIONS"] = options
        return {
            "default": redis_backend,
            "social_exchange": redis_backend,
            "scheduler_lock": redis_backend,
        }

    # Use DummyCache for testing to avoid cache pollution in parallel tests
    if testing:
        return {
            "default": {
                "BACKEND": "django.core.cache.backends.dummy.DummyCache",
            },
            "social_exchange": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "social-exchange-testing",
            },
            "scheduler_lock": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "scheduler-lock-testing",
            },
        }

    backend = (
        "django.core.cache.backends.dummy.DummyCache"
        if debug
        else "django.core.cache.backends.locmem.LocMemCache"
    )
    return {
        "default": {
            "BACKEND": backend,
        },
        "social_exchange": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "social-exchange",
        },
        "scheduler_lock": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "scheduler-lock",
        },
    }


def determine_email_backend(
    mailgun_key: str, mailgun_domain: str
) -> tuple[str, dict[str, Any]]:
    """Return the email backend path and optional Anymail configuration."""
    if mailgun_key and mailgun_domain:
        return (
            "anymail.backends.mailgun.EmailBackend",
            {
                "MAILGUN_API_KEY": mailgun_key,
                "MAILGUN_SENDER_DOMAIN": mailgun_domain,
            },
        )

    return "django.core.mail.backends.console.EmailBackend", {}
