# ruff: noqa: EM101, PLR0913
"""Public discovery endpoints for API v1."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from accounts.api_serializers import (
    serialize_education,
    serialize_work_experience,
)
from config.api_common import (
    ApiError,
    ErrorResponseSchema,
    PaginationSchema,
    build_paginated_response,
    paginate_queryset,
)

from accounts.api_v1 import jwt_bearer_auth

from .views import (
    MAX_SEARCH_RESULTS,
    SearchFilters,
    _apply_optional_filters,
    _collect_available_values,
    _serialize_user,
)

router = Router(tags=["public"])


class PublicUserSearchItemSchema(Schema):
    """Serialized search result item."""

    username: str
    display_name: str
    bio: str
    company: str
    location: str
    profile_url: str
    avatar_url: str


class PublicProfileSchema(Schema):
    """Publicly visible profile fields."""

    bio: str
    github_url: str
    homepage_url: str
    blog_url: str
    twitter_url: str
    linkedin_url: str
    company: str
    location: str


class PublicUserSchema(Schema):
    """Public user identity payload."""

    id: int
    username: str
    display_name: str


class PublicUserSearchResponseSchema(Schema):
    """Paginated public user search response."""

    items: list[PublicUserSearchItemSchema]
    pagination: PaginationSchema
    query: str
    filters: dict[str, str]
    total_matches: int
    max_results: int
    exact_match_username: str | None = None
    available_locations: list[str]
    available_companies: list[str]


class PublicUserProfileResponseSchema(Schema):
    """Public profile detail response."""

    user: PublicUserSchema
    profile: PublicProfileSchema
    work_experiences: list[dict[str, Any]]
    educations: list[dict[str, Any]]


def _profile_or_none(user):
    try:
        return user.profile
    except ObjectDoesNotExist:  # pragma: no cover - OneToOne descriptor specific path
        return None


def _public_profile_payload(user) -> PublicProfileSchema:
    profile = _profile_or_none(user)
    return PublicProfileSchema(
        bio=getattr(profile, "bio", "") or "",
        github_url=getattr(profile, "github_url", "") or "",
        homepage_url=getattr(profile, "homepage_url", "") or "",
        blog_url=getattr(profile, "blog_url", "") or "",
        twitter_url=getattr(profile, "twitter_url", "") or "",
        linkedin_url=getattr(profile, "linkedin_url", "") or "",
        company=getattr(profile, "company", "") or "",
        location=getattr(profile, "location", "") or "",
    )


@router.get("/search", auth=jwt_bearer_auth)
def homepage_search_endpoint(request, q: str = ""):
    """Search repos and developers from name_info table."""
    keyword = q.strip()
    if not keyword or len(keyword) < 2:
        return {"items": []}
    try:
        from chdb import services as chdb_services

        return {"items": chdb_services.search_name_info(keyword)}
    except Exception as exc:
        raise ApiError(
            "search_unavailable",
            503,
            "Search is currently unavailable.",
        ) from exc


@router.get(
    "/users/search",
    response={200: PublicUserSearchResponseSchema, 422: ErrorResponseSchema},
)
def public_user_search_endpoint(
    request,
    q: str,
    location: str = "",
    company: str = "",
    sort: str = SearchFilters.DEFAULT_SORT,
    page: int = 1,
    page_size: int = 20,
):
    """Search public user profiles."""
    query = q.strip()
    if not query:
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            {"q": [{"message": "The search query is required.", "code": "required"}]},
        )

    filters = SearchFilters(
        location=location.strip(), company=company.strip(), sort=sort
    )
    if filters.sort not in SearchFilters.SUPPORTED_SORTS:
        filters.sort = SearchFilters.DEFAULT_SORT

    UserModel = get_user_model()
    visible_users = UserModel.objects.filter(is_active=True, merged_into__isnull=True)
    exact_match = visible_users.filter(username__iexact=query).first()
    users_qs = (
        visible_users.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(profile__company__icontains=query)
            | Q(profile__location__icontains=query)
        )
        .select_related("profile")
        .distinct()
    )
    users_qs = _apply_optional_filters(users_qs, filters).order_by(*filters.ordering())
    available_locations = _collect_available_values(users_qs, "location")
    available_companies = _collect_available_values(users_qs, "company")

    total_matches = users_qs.count()
    limited_queryset = users_qs[:MAX_SEARCH_RESULTS]
    page_obj = paginate_queryset(
        limited_queryset, page=page, page_size=page_size, max_page_size=50
    )
    response = build_paginated_response(
        page_obj, [_serialize_user(user) for user in page_obj]
    )
    response["query"] = query
    response["filters"] = {
        "location": filters.location,
        "company": filters.company,
        "sort": filters.sort,
    }
    response["total_matches"] = total_matches
    response["max_results"] = MAX_SEARCH_RESULTS
    response["exact_match_username"] = exact_match.username if exact_match else None
    response["available_locations"] = available_locations
    response["available_companies"] = available_companies
    return response


@router.get(
    "/users/{username}",
    response={200: PublicUserProfileResponseSchema, 404: ErrorResponseSchema},
)
def public_user_profile_endpoint(request, username: str):
    """Return a public user profile."""
    UserModel = get_user_model()
    user = get_object_or_404(
        UserModel.objects.select_related("profile").filter(
            is_active=True,
            merged_into__isnull=True,
        ),
        username=username,
    )
    profile = _profile_or_none(user)
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.get_full_name() or user.username,
        },
        "profile": _public_profile_payload(user),
        "work_experiences": [
            serialize_work_experience(item)
            for item in (profile.work_experiences.all() if profile else [])
        ],
        "educations": [
            serialize_education(item)
            for item in (profile.educations.all() if profile else [])
        ],
    }
