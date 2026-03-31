# ruff: noqa: D101, EM101
"""Message center endpoints for API v1."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from accounts.api_v1 import jwt_bearer_auth
from config.api_common import ApiError, build_paginated_response, paginate_queryset

from .models import UserMessage
from .services import (
    delete_messages,
    get_message_stats,
    get_unread_count,
    get_user_messages,
    mark_as_read,
    mark_as_unread,
)

router = Router(tags=["messages"], auth=jwt_bearer_auth)

VALID_MESSAGE_STATUSES = {"all", "read", "unread"}


class MessageActionSchema(Schema):
    message_ids: list[int] | None = None


def _serialize_message_item(user_message: UserMessage) -> dict:
    message = user_message.message
    return {
        "id": message.id,
        "user_message_id": user_message.id,
        "title": message.title,
        "message_type": message.message_type,
        "sender": (
            {
                "id": message.sender_id,
                "username": message.sender.username,
            }
            if message.sender
            else None
        ),
        "is_broadcast": message.is_broadcast,
        "is_read": user_message.is_read,
        "read_at": user_message.read_at.isoformat() if user_message.read_at else None,
        "received_at": user_message.created_at.isoformat(),
        "created_at": message.created_at.isoformat(),
        "updated_at": message.updated_at.isoformat(),
        "content_preview": message.content[:200],
    }


def _serialize_message_detail(user_message: UserMessage) -> dict:
    payload = _serialize_message_item(user_message)
    payload["content"] = user_message.message.content
    return payload


@router.get("")
def message_list_endpoint(
    request,
    message_type: str | None = None,
    status: str = "all",
    page: int = 1,
    page_size: int = 20,
):
    """List inbox messages for the current user."""
    if status not in VALID_MESSAGE_STATUSES:
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            {
                "status": [
                    {
                        "message": 'Status must be one of "all", "read", or "unread".',
                        "code": "invalid",
                    }
                ]
            },
        )

    messages_qs = get_user_messages(request.auth, include_deleted=False)
    if message_type:
        messages_qs = messages_qs.filter(message__message_type=message_type)
    if status == "unread":
        messages_qs = messages_qs.filter(is_read=False)
    elif status == "read":
        messages_qs = messages_qs.filter(is_read=True)

    page_obj = paginate_queryset(
        messages_qs, page=page, page_size=page_size, max_page_size=100
    )
    response = build_paginated_response(
        page_obj,
        [_serialize_message_item(item) for item in page_obj.object_list],
    )
    response["stats"] = get_message_stats(request.auth)
    response["filters"] = {"message_type": message_type, "status": status}
    return response


@router.get("/stats")
def message_stats_endpoint(request):
    """Return inbox summary counts."""
    return get_message_stats(request.auth)


@router.get("/unread-count")
def message_unread_count_endpoint(request, message_type: str | None = None):
    """Return unread message counts."""
    return {"count": get_unread_count(request.auth, message_type=message_type)}


@router.post("/mark-read")
def message_mark_read_endpoint(request, payload: MessageActionSchema):
    """Mark messages as read. Empty message_ids marks all unread messages."""
    count = mark_as_read(request.auth, payload.message_ids)
    return {"updated": count}


@router.post("/mark-unread")
def message_mark_unread_endpoint(request, payload: MessageActionSchema):
    """Mark specific messages as unread."""
    if not payload.message_ids:
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            {
                "message_ids": [
                    {
                        "message": "Provide at least one message id.",
                        "code": "required",
                    }
                ]
            },
        )
    count = mark_as_unread(request.auth, payload.message_ids)
    return {"updated": count}


@router.post("/delete")
def message_delete_endpoint(request, payload: MessageActionSchema):
    """Soft-delete specific messages from the current user's inbox."""
    if not payload.message_ids:
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            {
                "message_ids": [
                    {
                        "message": "Provide at least one message id.",
                        "code": "required",
                    }
                ]
            },
        )
    count = delete_messages(request.auth, payload.message_ids)
    return {"deleted": count}


@router.get("/{message_id}")
def message_detail_endpoint(request, message_id: int):
    """Return a single inbox message and mark it as read."""
    user_message = get_object_or_404(
        UserMessage.objects.select_related("message", "message__sender"),
        message_id=message_id,
        user=request.auth,
        is_deleted=False,
    )
    if not user_message.is_read:
        user_message.mark_as_read()
        user_message.refresh_from_db()
    return _serialize_message_detail(user_message)
