"""Helpers for social-auth frontend handoff URLs."""

from __future__ import annotations

import logging
from urllib.parse import urlencode, urlparse

from django.conf import settings
from django.http import HttpResponseRedirect

logger = logging.getLogger(__name__)

# social-django URL path prefixes that participate in the OAuth handshake.
_SOCIAL_AUTH_PATH_PREFIXES = ("/login/", "/complete/", "/disconnect/")
_SOCIAL_AUTH_PATH_SEGMENTS = {"login", "complete", "disconnect"}


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


def _is_social_django_path(path: str) -> bool:
    """Return whether the path belongs to social-django's auth flow."""
    return any(path.startswith(prefix) for prefix in _SOCIAL_AUTH_PATH_PREFIXES)


def _extract_provider_from_social_path(path: str) -> str | None:
    """Pull the OAuth provider segment from a social-django URL path."""
    parts = path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] in _SOCIAL_AUTH_PATH_SEGMENTS:
        return parts[1] or None
    return None


class SocialAuthGenericExceptionMiddleware:
    """
    Convert unexpected social-auth errors into a SPA-friendly redirect.

    ``social_django.middleware.SocialAuthExceptionMiddleware`` only handles
    ``social_core.exceptions.SocialAuthBaseException``. Transport-level
    failures from the OAuth provider (network errors, HTTP 5xx, malformed
    responses from GitHub / AtomGit / Gitee, ...) bubble out of the
    ``/complete/<backend>/`` view and would otherwise surface as a Django
    500 page leaking tracebacks to the SPA. This middleware catches those
    generic errors and redirects to the frontend social-callback page
    with ``error=authentication_failed`` so the SPA can show a localized
    failure message instead.
    """

    def __init__(self, get_response):
        """Store the next middleware in the chain."""
        self.get_response = get_response

    def __call__(self, request):
        """Pass the request through; exceptions are handled below."""
        return self.get_response(request)

    def process_exception(self, request, exception):
        """Catch unexpected errors raised by the social-auth flow."""
        if not _is_social_django_path(request.path):
            return None

        # Let social-django handle the exception types it understands.
        try:
            from social_core.exceptions import SocialAuthBaseException
        except ImportError:  # pragma: no cover - dependency always present
            SocialAuthBaseException = ()  # type: ignore[assignment]
        if isinstance(exception, SocialAuthBaseException):
            return None

        provider = _extract_provider_from_social_path(request.path)
        if not provider:
            return None

        logger.exception(
            "Unexpected error during social auth flow for provider %s",
            provider,
        )

        try:
            url = build_frontend_social_callback_url(
                provider, error="authentication_failed"
            )
        except FrontendSocialCallbackNotConfigured:
            # Without a configured frontend URL there is nowhere safe to
            # redirect; let Django's default 500 handler take over so the
            # misconfiguration is surfaced rather than silently masked.
            return None

        return HttpResponseRedirect(url)
