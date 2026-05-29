"""
IP geolocation helpers backed by the offline ip2region xdb database.

The xdb file is an offline IP-to-region lookup database maintained by
``lionsoul2014/ip2region``. We only need to know whether the visitor comes
from mainland China to decide whether to surface the AtomGit social-login
entry on the login page; therefore this module exposes a narrow API and
fails closed (returns ``None``) whenever the database is missing or the
lookup raises.

The xdb data file is intentionally **not** committed to the repository.

* Docker deployments: the file is downloaded during ``docker build`` and
  baked into the image at ``/app/data/ip2region_v4.xdb`` with
  ``IP2REGION_XDB_PATH`` pre-set via ``ENV`` (see ``Dockerfile``).
* Local development: download ``data/ip2region.xdb`` from
  ``https://github.com/lionsoul2014/ip2region`` and point
  ``IP2REGION_XDB_PATH`` at it via ``.env``.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from django.conf import settings
from django.http import HttpRequest

logger = logging.getLogger(__name__)

# Province names returned by ip2region for non-mainland regions that share
# the ``CN`` ISO country code. Anything not listed here is treated as
# mainland China.
_NON_MAINLAND_PROVINCES = ("香港", "澳门", "台湾")

_REGION_FIELD_COUNT = 5

_searcher_lock = threading.Lock()
_searcher_cache: dict[str, Any] = {}


def _resolve_xdb_path() -> Path | None:
    """Return the configured xdb path if it exists on disk."""
    raw = getattr(settings, "IP2REGION_XDB_PATH", "") or ""
    if not raw:
        return None
    path = Path(raw)
    if not path.is_file():
        logger.warning("ip2region xdb file not found at %s", path)
        return None
    return path


def _load_searcher(path: Path) -> Any | None:
    """
    Build (or return a cached) ip2region searcher for ``path``.

    The searcher is created in fully memory-cached mode so it can be safely
    shared across threads without re-reading the xdb file on every request.
    """
    key = str(path.resolve())
    cached = _searcher_cache.get(key)
    if cached is not None:
        return cached

    with _searcher_lock:
        cached = _searcher_cache.get(key)
        if cached is not None:
            return cached
        try:
            import ip2region.searcher as xdb
            from ip2region import util

            buffer = util.load_content_from_file(str(path))
            searcher = xdb.new_with_buffer(util.IPv4, buffer)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to initialize ip2region searcher from %s", path)
            return None
        _searcher_cache[key] = searcher
        return searcher


def _reset_searcher_cache() -> None:
    """Drop the cached searcher (used by tests)."""
    with _searcher_lock:
        _searcher_cache.clear()


def get_client_ip(request: HttpRequest) -> str | None:
    """
    Return the best-effort client IP from the incoming request.

    Honors ``X-Forwarded-For`` (taking the first hop, which is the original
    client when set by a trusted reverse proxy) and falls back to
    ``REMOTE_ADDR``. Returns ``None`` if neither is available.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        candidate = forwarded.split(",")[0].strip()
        if candidate:
            return candidate
    remote = request.META.get("REMOTE_ADDR")
    if remote:
        return remote.strip() or None
    return None


def _parse_region(region: str) -> tuple[str, str] | None:
    """
    Parse an ip2region row into ``(iso_code, province)`` or ``None``.

    The ip2region xdb encodes regions as
    ``Country|Province|City|ISP|iso-alpha2-Code``. Empty or malformed rows
    return ``None``.
    """
    if not region:
        return None
    parts = region.split("|")
    if len(parts) < _REGION_FIELD_COUNT:
        return None
    province = parts[1].strip()
    iso_code = parts[4].strip().upper()
    return iso_code, province


def is_mainland_china_ip(ip: str | None) -> bool | None:
    """
    Return whether ``ip`` belongs to mainland China.

    Returns ``True`` for mainland addresses, ``False`` for any other
    geolocated address, and ``None`` when the result cannot be determined
    (missing xdb file, lookup failure, empty input, etc.).
    """
    if not ip:
        return None
    path = _resolve_xdb_path()
    if path is None:
        return None
    searcher = _load_searcher(path)
    if searcher is None:
        return None
    try:
        region = searcher.search(ip)
    except Exception:
        logger.warning("ip2region lookup failed for ip=%s", ip, exc_info=True)
        return None
    parsed = _parse_region(region or "")
    if parsed is None:
        return None
    iso_code, province = parsed
    return province not in _NON_MAINLAND_PROVINCES if iso_code == "CN" else False
