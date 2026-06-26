# ruff: noqa: D101, EM101
"""Talent outreach endpoints for API v1."""

from __future__ import annotations

from ninja import Router, Schema

from accounts.api_v1 import jwt_bearer_auth
from chdb.services import get_available_languages
from config.api_common import ApiError, ErrorResponseSchema

from . import services

router = Router(tags=["talent-reach"], auth=jwt_bearer_auth)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class DraftCreateSchema(Schema):
    title: str
    content: str
    title_zh: str = ""
    content_zh: str = ""


class DraftResponseSchema(Schema):
    id: int
    title: str
    content: str
    title_zh: str
    content_zh: str
    created_at: str
    updated_at: str


class PreviewRequestSchema(Schema):
    tag_ids: list[str]
    languages: list[str] | None = None
    countries: list[str] | None = None
    regions: list[str] | None = None
    top_n: int | None = None


class SendRequestSchema(Schema):
    draft_id: int
    tag_ids: list[str]
    tag_names: list[str]
    languages: list[str] | None = None
    countries: list[str] | None = None
    regions: list[str] | None = None
    top_n: int | None = None
    point_type: str  # 'cash' or 'gift'


class CampaignListSchema(Schema):
    id: int
    title: str
    status: str
    total_recipients: int
    read_count: int
    rewarded_count: int
    total_cost: int
    reward_pool: int
    point_type: str
    created_at: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_draft(draft) -> dict:
    return {
        "id": draft.id,
        "title": draft.title,
        "content": draft.content,
        "title_zh": draft.title_zh,
        "content_zh": draft.content_zh,
        "created_at": draft.created_at.isoformat(),
        "updated_at": draft.updated_at.isoformat(),
    }


def _serialize_campaign_list_item(campaign) -> dict:
    return {
        "id": campaign.id,
        "title": campaign.title,
        "status": campaign.status,
        "total_recipients": campaign.total_recipients,
        "read_count": campaign.read_count,
        "rewarded_count": campaign.rewarded_count,
        "total_cost": campaign.total_cost,
        "reward_pool": campaign.reward_pool,
        "point_type": campaign.point_type,
        "created_at": campaign.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Drafts CRUD
# ---------------------------------------------------------------------------


@router.post(
    "/drafts",
    response={201: dict, 401: ErrorResponseSchema, 422: ErrorResponseSchema},
)
def draft_create_endpoint(request, payload: DraftCreateSchema):
    """Create a new outreach draft."""
    if not payload.title or not payload.title.strip():
        raise ApiError("validation_error", 422, "Title is required.")
    if not payload.content or not payload.content.strip():
        raise ApiError("validation_error", 422, "Content is required.")
    draft = services.create_draft(
        author=request.auth,
        title=payload.title.strip(),
        content=payload.content,
        title_zh=payload.title_zh.strip(),
        content_zh=payload.content_zh,
    )
    return 201, _serialize_draft(draft)


@router.get(
    "/drafts",
    response={200: list[DraftResponseSchema], 401: ErrorResponseSchema},
)
def draft_list_endpoint(request):
    """List all drafts for the current user."""
    drafts = services.list_drafts(request.auth)
    return [_serialize_draft(d) for d in drafts]


@router.get(
    "/drafts/{draft_id}",
    response={
        200: DraftResponseSchema,
        401: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
)
def draft_detail_endpoint(request, draft_id: int):
    """Get a single draft."""
    try:
        draft = services.get_draft(draft_id, request.auth)
    except Exception as exc:
        raise ApiError("not_found", 404, "Draft not found.") from exc
    return _serialize_draft(draft)


@router.put(
    "/drafts/{draft_id}",
    response={
        200: DraftResponseSchema,
        401: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
)
def draft_update_endpoint(request, draft_id: int, payload: DraftCreateSchema):
    """Update an existing draft."""
    if not payload.title or not payload.title.strip():
        raise ApiError("validation_error", 422, "Title is required.")
    if not payload.content or not payload.content.strip():
        raise ApiError("validation_error", 422, "Content is required.")
    try:
        draft = services.update_draft(
            draft_id=draft_id,
            author=request.auth,
            title=payload.title.strip(),
            content=payload.content,
            title_zh=payload.title_zh.strip(),
            content_zh=payload.content_zh,
        )
    except Exception as exc:
        raise ApiError("not_found", 404, "Draft not found.") from exc
    return _serialize_draft(draft)


@router.delete(
    "/drafts/{draft_id}",
    response={204: None, 401: ErrorResponseSchema, 404: ErrorResponseSchema},
)
def draft_delete_endpoint(request, draft_id: int):
    """Delete a draft."""
    services.delete_draft(draft_id, request.auth)
    return 204, None


# ---------------------------------------------------------------------------
# Languages list (no auth required)
# ---------------------------------------------------------------------------


@router.get("/languages", auth=None, response={200: dict})
def languages_endpoint(request):
    """List available programming languages for filtering."""
    languages = get_available_languages()
    return {"items": languages}


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


@router.post(
    "/preview",
    response={200: dict, 401: ErrorResponseSchema, 422: ErrorResponseSchema},
)
def preview_endpoint(request, payload: PreviewRequestSchema):
    """Preview reachable users for the given filter criteria."""
    if not payload.tag_ids:
        raise ApiError("validation_error", 422, "At least one tag_id is required.")
    result = services.preview_recipients(
        tag_ids=payload.tag_ids,
        languages=payload.languages,
        countries=payload.countries,
        regions=payload.regions,
        top_n=payload.top_n,
    )
    return result


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------


@router.post(
    "/send",
    response={
        201: dict,
        401: ErrorResponseSchema,
        404: ErrorResponseSchema,
        409: ErrorResponseSchema,
        422: ErrorResponseSchema,
    },
)
def send_endpoint(request, payload: SendRequestSchema):
    """Send outreach messages to matching developers."""
    if not payload.tag_ids:
        raise ApiError("validation_error", 422, "At least one tag_id is required.")
    if payload.point_type not in ("cash", "gift"):
        raise ApiError("validation_error", 422, "point_type must be 'cash' or 'gift'.")
    try:
        campaign = services.send_outreach(
            draft_id=payload.draft_id,
            author=request.auth,
            tag_ids=payload.tag_ids,
            tag_names=payload.tag_names,
            languages=payload.languages,
            countries=payload.countries,
            regions=payload.regions,
            top_n=payload.top_n,
            point_type=payload.point_type,
        )
    except services.OutreachDraft.DoesNotExist as exc:
        raise ApiError("not_found", 404, "Draft not found.") from exc
    except ValueError as exc:
        raise ApiError("validation_error", 422, str(exc)) from exc
    except Exception as exc:
        # Catch InsufficientPointsError from spend_points
        from points.services import InsufficientPointsError

        if isinstance(exc, InsufficientPointsError):
            raise ApiError(
                "insufficient_points",
                409,
                "Not enough points to send this outreach.",
            ) from exc
        raise

    return 201, _serialize_campaign_list_item(campaign)


# ---------------------------------------------------------------------------
# Campaigns (history)
# ---------------------------------------------------------------------------


@router.get(
    "/campaigns",
    response={200: list[CampaignListSchema], 401: ErrorResponseSchema},
)
def campaign_list_endpoint(request):
    """List outreach campaigns for the current user."""
    campaigns = services.list_campaigns(request.auth)
    return [_serialize_campaign_list_item(c) for c in campaigns]


@router.get(
    "/campaigns/{campaign_id}",
    response={200: dict, 401: ErrorResponseSchema, 404: ErrorResponseSchema},
)
def campaign_detail_endpoint(request, campaign_id: int):
    """Get detailed campaign info with live stats."""
    try:
        detail = services.get_campaign_detail(campaign_id, request.auth)
    except Exception as exc:
        raise ApiError("not_found", 404, "Campaign not found.") from exc
    return detail
