# ruff: noqa: D101, EM101, B904
"""Shop and redemption endpoints for API v1."""

from __future__ import annotations

import re

from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from accounts.api_serializers import serialize_shipping_address
from accounts.api_v1 import jwt_bearer_auth
from accounts.models import ShippingAddress
from config.api_common import (
    ApiError,
    ErrorResponseSchema,
    PaginationSchema,
    build_paginated_response,
    paginate_queryset,
)
from points import services as points_services

from .models import Redemption, ShopItem
from .services import RedemptionError, redeem_item

router = Router(tags=["shop"], auth=jwt_bearer_auth)


class RedemptionCreateSchema(Schema):
    item_id: int
    shipping_address_id: int | None = None


class ShopItemAllowedTagSchema(Schema):
    slug: str
    name: str
    tag_type: str


class ShippingAddressSchema(Schema):
    id: int
    receiver_name: str
    phone: str
    province: str
    city: str
    district: str
    address: str
    is_default: bool
    created_at: str
    updated_at: str


class DetailedBalanceSchema(Schema):
    total: int
    cash: int
    gift: int
    gift_no_tag: int
    by_tag: dict[str, int]


class ShopItemSchema(Schema):
    id: int
    name: str
    description: str
    cost: int
    stock: int | None = None
    is_active: bool
    image_url: str | None = None
    requires_shipping: bool
    allowed_tags: list[ShopItemAllowedTagSchema]
    created_at: str
    updated_at: str


class ShopItemDetailSchema(ShopItemSchema):
    shipping_addresses: list[ShippingAddressSchema] | None = None


class ShopItemListResponseSchema(Schema):
    items: list[ShopItemSchema]
    pagination: PaginationSchema
    balance: DetailedBalanceSchema


class RedemptionSchema(Schema):
    id: int
    status: str
    points_cost: int
    created_at: str
    item: ShopItemSchema
    shipping_address: ShippingAddressSchema | None = None


class RedemptionListResponseSchema(Schema):
    items: list[RedemptionSchema]
    pagination: PaginationSchema


def _serialize_shop_item(item: ShopItem) -> dict:
    allowed_tags = list(item.allowed_tags.all())
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "cost": item.cost,
        "stock": item.stock,
        "is_active": item.is_active,
        "image_url": item.image.url if item.image else None,
        "requires_shipping": item.requires_shipping,
        "allowed_tags": [
            {
                "slug": tag.slug,
                "name": tag.name,
                "tag_type": tag.tag_type,
            }
            for tag in allowed_tags
        ],
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }


def _serialize_redemption(redemption: Redemption) -> dict:
    return {
        "id": redemption.id,
        "status": redemption.status,
        "points_cost": redemption.points_cost_at_redemption,
        "created_at": redemption.created_at.isoformat(),
        "item": _serialize_shop_item(redemption.item),
        "shipping_address": (
            serialize_shipping_address(redemption.shipping_address)
            if redemption.shipping_address
            else None
        ),
    }


def _raise_redemption_api_error(message: str) -> None:
    normalized = message.strip()
    if normalized == "商品不存在。":
        raise ApiError("not_found", 404, "The requested item was not found.")
    if normalized == "该商品已下架。":
        raise ApiError("item_unavailable", 409, "This item is no longer available.")
    if normalized == "该商品已售罄。":
        raise ApiError("out_of_stock", 409, "This item is out of stock.")
    if normalized == "此商品需要收货地址。":
        raise ApiError(
            "shipping_address_required",
            422,
            "A shipping address is required for this item.",
        )
    if normalized == "无效的收货地址。":
        raise ApiError(
            "invalid_shipping_address", 422, "The shipping address is invalid."
        )
    if normalized == "您没有足够的符合条件的积分来兑换此商品":
        raise ApiError(
            "insufficient_points",
            409,
            "You do not have enough eligible points to redeem this item.",
        )
    exact_match = re.match(
        r"^积分不足：需要 (?P<required>\d+)，当前可用 (?P<available>\d+)$", normalized
    )
    if exact_match:
        groups = exact_match.groupdict()
        raise ApiError(
            "insufficient_points",
            409,
            (
                "Not enough points to redeem this item. "
                f"Required: {groups['required']}, available: {groups['available']}."
            ),
        )
    if normalized.startswith("积分不足："):
        raise ApiError(
            "insufficient_points", 409, "Not enough points to redeem this item."
        )
    raise ApiError("redemption_failed", 409, "The item could not be redeemed.")


@router.get(
    "/items",
    response={200: ShopItemListResponseSchema, 401: ErrorResponseSchema},
)
def shop_item_list_endpoint(request, page: int = 1, page_size: int = 20):
    """List active shop items."""
    items_qs = (
        ShopItem.objects.filter(is_active=True)
        .prefetch_related("allowed_tags")
        .order_by("id")
    )
    page_obj = paginate_queryset(
        items_qs, page=page, page_size=page_size, max_page_size=100
    )
    response = build_paginated_response(
        page_obj,
        [_serialize_shop_item(item) for item in page_obj.object_list],
    )
    response["balance"] = points_services.get_detailed_balance_or_zero(request.auth)
    return response


@router.get(
    "/items/{item_id}",
    response={
        200: ShopItemDetailSchema,
        401: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
)
def shop_item_detail_endpoint(request, item_id: int):
    """Return a single active shop item."""
    item = get_object_or_404(
        ShopItem.objects.prefetch_related("allowed_tags"), id=item_id, is_active=True
    )
    payload = _serialize_shop_item(item)
    if item.requires_shipping:
        payload["shipping_addresses"] = [
            serialize_shipping_address(address)
            for address in ShippingAddress.objects.filter(user=request.auth)
        ]
    return payload


@router.get(
    "/redemptions",
    response={200: RedemptionListResponseSchema, 401: ErrorResponseSchema},
)
def redemption_list_endpoint(request, page: int = 1, page_size: int = 20):
    """List the current user's redemption history."""
    redemptions = (
        Redemption.objects.filter(user_profile=request.auth)
        .select_related(
            "item",
            "shipping_address",
        )
        .prefetch_related("item__allowed_tags")
    )
    page_obj = paginate_queryset(
        redemptions, page=page, page_size=page_size, max_page_size=100
    )
    return build_paginated_response(
        page_obj,
        [_serialize_redemption(item) for item in page_obj.object_list],
    )


@router.get(
    "/redemptions/{redemption_id}",
    response={
        200: RedemptionSchema,
        401: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
)
def redemption_detail_endpoint(request, redemption_id: int):
    """Return a single redemption record owned by the current user."""
    redemption = get_object_or_404(
        Redemption.objects.select_related("item", "shipping_address").prefetch_related(
            "item__allowed_tags"
        ),
        id=redemption_id,
        user_profile=request.auth,
    )
    return _serialize_redemption(redemption)


@router.post(
    "/redemptions",
    response={
        201: RedemptionSchema,
        401: ErrorResponseSchema,
        404: ErrorResponseSchema,
        409: ErrorResponseSchema,
        422: ErrorResponseSchema,
    },
)
def redemption_create_endpoint(request, payload: RedemptionCreateSchema):
    """Redeem a shop item."""
    try:
        redemption = redeem_item(
            user=request.auth,
            item_id=payload.item_id,
            shipping_address_id=payload.shipping_address_id,
        )
    except RedemptionError as exc:
        _raise_redemption_api_error(str(exc))
        raise AssertionError("unreachable")

    redemption = (
        Redemption.objects.select_related("item", "shipping_address")
        .prefetch_related("item__allowed_tags")
        .get(id=redemption.id)
    )
    return 201, _serialize_redemption(redemption)
