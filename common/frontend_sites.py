"""Resolve the frontend site associated with an incoming request."""

from __future__ import annotations

from enum import StrEnum
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpRequest


class FrontendSite(StrEnum):
    """Stable identifiers for the two independently operated frontends."""

    CN = "cn"
    GLOBAL = "global"


FRONTEND_SITE_SESSION_KEY = "open_share_frontend_site"
FRONTEND_SITE_HEADER = "X-OpenShare-Site"

_CANONICAL_HOSTS = {
    "open-share.cn": FrontendSite.CN,
    "www.open-share.cn": FrontendSite.CN,
    "open-share.com": FrontendSite.GLOBAL,
    "www.open-share.com": FrontendSite.GLOBAL,
}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def parse_frontend_site(value: object) -> FrontendSite | None:
    """Parse a site marker without accepting aliases or arbitrary values."""
    try:
        return FrontendSite(str(value).strip().lower())
    except ValueError:
        return None


def default_frontend_site() -> FrontendSite:
    """Return the configured fallback for requests that have no browser origin."""
    configured = parse_frontend_site(
        getattr(settings, "FRONTEND_DEFAULT_SITE", FrontendSite.CN)
    )
    return configured or FrontendSite.CN


def frontend_app_url(site: FrontendSite | str) -> str:
    """Return the configured SPA base URL for a frontend site."""
    resolved = parse_frontend_site(site)
    if resolved is None:
        return ""

    setting_name = (
        "FRONTEND_CN_APP_URL"
        if resolved == FrontendSite.CN
        else "FRONTEND_GLOBAL_APP_URL"
    )
    configured = str(getattr(settings, setting_name, "") or "").strip()
    if configured:
        return configured.rstrip("/")

    # Preserve the original single-frontend setting as a migration fallback,
    # but only for the configured default site. The other site must always
    # have its own explicit callback URL.
    if resolved == default_frontend_site():
        return str(getattr(settings, "FRONTEND_APP_URL", "") or "").rstrip("/")
    return ""


def _url_origin(value: str | None) -> str | None:
    """Normalize an absolute URL to its lower-cased scheme and authority."""
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _site_from_url(value: str | None) -> FrontendSite | None:
    """Resolve canonical and configured frontend URLs to a site."""
    origin = _url_origin(value)
    if origin is None:
        return None
    hostname = (urlsplit(origin).hostname or "").lower()
    canonical = _CANONICAL_HOSTS.get(hostname)
    if canonical is not None:
        return canonical

    for site in FrontendSite:
        if origin == _url_origin(frontend_app_url(site)):
            return site
    return None


def _is_local_url(value: str | None) -> bool:
    origin = _url_origin(value)
    if origin is None:
        return False
    return (urlsplit(origin).hostname or "").lower() in _LOCAL_HOSTS


def _is_allowed_origin(value: str | None) -> bool:
    origin = _url_origin(value)
    if origin is None:
        return False
    allowed = {
        normalized
        for item in getattr(settings, "CORS_ALLOWED_ORIGINS", [])
        if (normalized := _url_origin(item)) is not None
    }
    return origin in allowed


def frontend_site_from_request(
    request: HttpRequest,
    *,
    allow_query_marker: bool = False,
) -> FrontendSite | None:
    """
    Resolve the frontend site from trusted browser metadata.

    Canonical/configured ``Origin`` and ``Referer`` hosts take precedence.
    ``X-OpenShare-Site`` is accepted only without browser origin metadata or
    from an allowlisted non-production origin (primarily local development).
    The query marker is reserved for OAuth top-level navigation, where a
    browser does not consistently retain ``Origin``.
    """
    origin = request.headers.get("Origin")
    referer = request.headers.get("Referer")
    source_url = origin or referer
    marker = parse_frontend_site(request.headers.get(FRONTEND_SITE_HEADER))
    if marker is None and allow_query_marker:
        marker = parse_frontend_site(request.GET.get("frontend_site"))

    resolved = _site_from_url(source_url)
    if resolved is not None:
        # A single localhost origin may be used to test either build. Explicit
        # markers are never allowed to override a production frontend domain.
        if marker is not None and _is_local_url(source_url):
            return marker
        return resolved

    if source_url:
        if marker is not None and _is_allowed_origin(source_url):
            return marker
        return None

    return marker or default_frontend_site()


def request_frontend_site(request: HttpRequest) -> FrontendSite | None:
    """Read middleware state, resolving it lazily for direct view tests."""
    value = getattr(request, "frontend_site", None)
    if value is not None:
        return parse_frontend_site(value)
    return frontend_site_from_request(request)
