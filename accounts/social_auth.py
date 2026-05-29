"""Helpers for social-auth frontend handoff URLs."""

from __future__ import annotations

from urllib.parse import urlencode, urlparse

from django.conf import settings


class FrontendSocialCallbackNotConfigured(RuntimeError):
    """Raised when the frontend social callback URL cannot be built."""


def social_api_callback_path(provider: str) -> str:
    """Return the server-side callback path for an API social-login handoff."""
    return f"/api/v1/auth/social/{provider}/callback"


def is_api_social_callback_target(target_url: str | None, provider: str) -> bool:
    """Return whether the stored next target belongs to the SPA social flow."""
    if not target_url:
        return False
    parsed = urlparse(target_url)
    path = parsed.path or target_url
    return path == social_api_callback_path(provider)


def build_frontend_social_callback_url(provider: str, **params: str) -> str:
    """Return the frontend callback URL used after social auth completes."""
    if not settings.FRONTEND_APP_URL:
        raise FrontendSocialCallbackNotConfigured()

    query = urlencode({"provider": provider, **params})
    return (
        f"{settings.FRONTEND_APP_URL.rstrip('/')}"
        f"{settings.FRONTEND_SOCIAL_CALLBACK_PATH}?{query}"
    )
