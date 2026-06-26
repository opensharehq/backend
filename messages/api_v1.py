# ruff: noqa: D101, EM101
"""Message center endpoints for API v1."""

from __future__ import annotations

from typing import Any

from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from accounts.api_v1 import jwt_bearer_auth
from config.api_common import (
    ApiError,
    ErrorResponseSchema,
    PaginationSchema,
    build_paginated_response,
    paginate_queryset,
)

from .models import Message, UserMessage
from .services import (
    delete_messages,
    get_message_stats,
    get_unread_count,
    get_user_messages,
    mark_all_as_read,
    mark_as_read,
    mark_as_unread,
)

router = Router(tags=["messages"], auth=jwt_bearer_auth)

VALID_MESSAGE_STATUSES = {"all", "read", "unread"}
VALID_MESSAGE_TYPES = {choice[0] for choice in Message.MessageType.choices}


class MessageActionSchema(Schema):
    message_ids: list[int] | None = None


class MessageItemSchema(Schema):
    id: int
    user_message_id: int
    title: str
    message_type: str
    sender: dict[str, Any] | None = None
    is_broadcast: bool
    is_read: bool
    read_at: str | None = None
    received_at: str
    created_at: str
    updated_at: str
    content_preview: str
    reward_amount: int | None = None
    title_zh: str | None = None
    content_preview_zh: str | None = None


class MessageDetailSchema(MessageItemSchema):
    content: str
    reward_amount: int | None = None
    reward_point_type: str | None = None
    title_zh: str | None = None
    content_zh: str | None = None


class MessageStatsSchema(Schema):
    total: int
    unread: int
    read: int
    type_counts: dict[str, int]


class MessageListResponseSchema(Schema):
    items: list[MessageItemSchema]
    pagination: PaginationSchema
    stats: MessageStatsSchema
    filters: dict[str, str | None]


class CountResponseSchema(Schema):
    count: int


class UpdateCountResponseSchema(Schema):
    updated: int


class DeleteCountResponseSchema(Schema):
    deleted: int


def _validation_error(field: str, message: str, code: str = "invalid") -> ApiError:
    return ApiError(
        "validation_error",
        422,
        "Request validation failed.",
        {field: [{"message": message, "code": code}]},
    )


def _validate_message_type(message_type: str | None) -> None:
    if message_type and message_type not in VALID_MESSAGE_TYPES:
        raise _validation_error(
            "message_type",
            "The specified message type is invalid.",
        )


def _serialize_message_item(user_message: UserMessage) -> MessageItemSchema:
    message = user_message.message
    return MessageItemSchema(
        id=message.id,
        user_message_id=user_message.id,
        title=message.title,
        message_type=message.message_type,
        sender=(
            {
                "id": message.sender_id,
                "username": message.sender.username,
            }
            if message.sender
            else None
        ),
        is_broadcast=message.is_broadcast,
        is_read=user_message.is_read,
        read_at=user_message.read_at.isoformat() if user_message.read_at else None,
        received_at=user_message.created_at.isoformat(),
        created_at=message.created_at.isoformat(),
        updated_at=message.updated_at.isoformat(),
        content_preview=message.content[:200],
    )


def _serialize_message_detail(user_message: UserMessage) -> MessageDetailSchema:
    payload = _serialize_message_item(user_message).model_dump()
    payload["content"] = user_message.message.content

    # Include reward info and bilingual content for outreach messages
    if user_message.message.message_type == "outreach":
        from talent_reach.models import OutreachRecipient

        recipient = (
            OutreachRecipient.objects.select_related("campaign")
            .filter(user_message_id=user_message.id)
            .first()
        )
        if recipient:
            payload["reward_amount"] = recipient.reward_amount
            payload["reward_point_type"] = recipient.campaign.point_type
            # Include Chinese content if available
            if recipient.campaign.title_zh:
                payload["title_zh"] = recipient.campaign.title_zh
            if recipient.campaign.content_zh:
                payload["content_zh"] = recipient.campaign.content_zh

    return MessageDetailSchema(**payload)


@router.get(
    "",
    response={
        200: MessageListResponseSchema,
        401: ErrorResponseSchema,
        422: ErrorResponseSchema,
    },
)
def message_list_endpoint(
    request,
    message_type: str | None = None,
    status: str = "all",
    page: int = 1,
    page_size: int = 20,
):
    """List inbox messages for the current user."""
    _validate_message_type(message_type)
    if status not in VALID_MESSAGE_STATUSES:
        raise _validation_error(
            "status",
            'Status must be one of "all", "read", or "unread".',
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
    items = [_serialize_message_item(item) for item in page_obj.object_list]

    # Batch-enrich outreach messages with reward_amount
    outreach_um_ids = [
        item.user_message_id for item in items if item.message_type == "outreach"
    ]
    if outreach_um_ids:
        from talent_reach.models import OutreachRecipient

        recipients = OutreachRecipient.objects.select_related("campaign").filter(
            user_message_id__in=outreach_um_ids
        )
        reward_map = {}
        zh_map = {}
        for r in recipients:
            reward_map[r.user_message_id] = r.reward_amount
            if r.campaign.title_zh or r.campaign.content_zh:
                zh_map[r.user_message_id] = {
                    "title_zh": r.campaign.title_zh,
                    "content_zh": r.campaign.content_zh,
                }
        for item in items:
            if item.message_type == "outreach" and item.user_message_id in reward_map:
                item.reward_amount = reward_map[item.user_message_id]
            if item.message_type == "outreach" and item.user_message_id in zh_map:
                zh_data = zh_map[item.user_message_id]
                if zh_data["title_zh"]:
                    item.title_zh = zh_data["title_zh"]
                if zh_data["content_zh"]:
                    item.content_preview_zh = zh_data["content_zh"][:200]

    response = build_paginated_response(page_obj, items)
    response["stats"] = get_message_stats(request.auth)
    response["filters"] = {"message_type": message_type, "status": status}
    return response


@router.get(
    "/stats",
    response={200: MessageStatsSchema, 401: ErrorResponseSchema},
)
def message_stats_endpoint(request):
    """Return inbox summary counts."""
    return get_message_stats(request.auth)


@router.get(
    "/unread-count",
    response={
        200: CountResponseSchema,
        401: ErrorResponseSchema,
        422: ErrorResponseSchema,
    },
)
def message_unread_count_endpoint(request, message_type: str | None = None):
    """Return unread message counts."""
    _validate_message_type(message_type)
    return {"count": get_unread_count(request.auth, message_type=message_type)}


@router.post(
    "/mark-read",
    response={
        200: dict,
        401: ErrorResponseSchema,
        422: ErrorResponseSchema,
    },
)
def message_mark_read_endpoint(request, payload: MessageActionSchema):
    """Mark specific messages as read."""
    if not payload.message_ids:
        raise _validation_error(
            "message_ids",
            "Provide at least one message id.",
            code="required",
        )
    count = mark_as_read(request.auth, payload.message_ids)

    # Check for outreach reading rewards
    from talent_reach.services import claim_reading_reward

    rewards = []
    user_messages = UserMessage.objects.filter(
        user=request.auth, message_id__in=payload.message_ids
    )
    for um in user_messages:
        reward_result = claim_reading_reward(user=request.auth, user_message_id=um.id)
        if reward_result:
            rewards.append(reward_result)

    response: dict = {"updated": count}
    if rewards:
        response["rewards"] = rewards
    return response


@router.post(
    "/mark-all-read",
    response={200: UpdateCountResponseSchema, 401: ErrorResponseSchema},
)
def message_mark_all_read_endpoint(request):
    """Mark all unread messages as read."""
    return {"updated": mark_all_as_read(request.auth)}


@router.post(
    "/mark-unread",
    response={
        200: UpdateCountResponseSchema,
        401: ErrorResponseSchema,
        422: ErrorResponseSchema,
    },
)
def message_mark_unread_endpoint(request, payload: MessageActionSchema):
    """Mark specific messages as unread."""
    if not payload.message_ids:
        raise _validation_error(
            "message_ids",
            "Provide at least one message id.",
            code="required",
        )
    count = mark_as_unread(request.auth, payload.message_ids)
    return {"updated": count}


@router.post(
    "/delete",
    response={
        200: DeleteCountResponseSchema,
        401: ErrorResponseSchema,
        422: ErrorResponseSchema,
    },
)
def message_delete_endpoint(request, payload: MessageActionSchema):
    """Soft-delete specific messages from the current user's inbox."""
    if not payload.message_ids:
        raise _validation_error(
            "message_ids",
            "Provide at least one message id.",
            code="required",
        )
    count = delete_messages(request.auth, payload.message_ids)
    return {"deleted": count}


@router.get(
    "/{message_id}",
    response={
        200: MessageDetailSchema,
        401: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
)
def message_detail_endpoint(request, message_id: int):
    """Return a single inbox message without mutating read state."""
    user_message = get_object_or_404(
        UserMessage.objects.select_related("message", "message__sender"),
        message_id=message_id,
        user=request.auth,
        is_deleted=False,
    )
    return _serialize_message_detail(user_message)


@router.post(
    "/{message_id}/mark-read",
    response={
        200: dict,
        401: ErrorResponseSchema,
    },
)
def message_detail_mark_read_endpoint(request, message_id: int):
    """Mark a single message as read."""
    updated = mark_as_read(request.auth, [message_id])

    # Check for outreach reading reward
    from talent_reach.services import claim_reading_reward

    reward = None
    um = UserMessage.objects.filter(user=request.auth, message_id=message_id).first()
    if um:
        reward = claim_reading_reward(user=request.auth, user_message_id=um.id)

    response: dict = {"updated": updated}
    if reward:
        response["reward"] = reward
    return response
