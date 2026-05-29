"""Public Django Ninja endpoints for cross-cutting common features."""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router, Schema

from common.services.region import get_client_ip, is_mainland_china_ip

router = Router(tags=["common"])


class RegionResponseSchema(Schema):
    """
    Best-effort region info for the requesting client.

    ``is_mainland_cn`` is ``True`` when the visitor's IP can be confidently
    geolocated to mainland China (excluding HK/MO/TW), ``False`` for any
    other geolocated region, and ``None`` when the lookup is unavailable
    (xdb data file not configured, IP missing, etc.). The frontend treats
    anything other than ``True`` as "do not show AtomGit".
    """

    is_mainland_cn: bool | None


@router.get("/region", response=RegionResponseSchema)
def region_endpoint(request: HttpRequest) -> RegionResponseSchema:
    """Return whether the calling client appears to come from mainland China."""
    ip = get_client_ip(request)
    return RegionResponseSchema(is_mainland_cn=is_mainland_china_ip(ip))
