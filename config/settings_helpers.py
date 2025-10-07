"""Helper utilities for Django settings configuration."""

from __future__ import annotations

from typing import Any


def build_cache_settings(
    debug: bool, redis_url: str, testing: bool = False
) -> dict[str, Any]:
    """Return Django cache configuration based on debug flag and Redis URL."""
    if redis_url:
        return {
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": redis_url,
                "OPTIONS": {
                    "ssl_cert_reqs": None,
                },
            }
        }

    # Use DummyCache for testing to avoid cache pollution in parallel tests
    if testing:
        return {
            "default": {
                "BACKEND": "django.core.cache.backends.dummy.DummyCache",
            }
        }

    backend = (
        "django.core.cache.backends.dummy.DummyCache"
        if debug
        else "django.core.cache.backends.locmem.LocMemCache"
    )
    return {
        "default": {
            "BACKEND": backend,
        }
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
