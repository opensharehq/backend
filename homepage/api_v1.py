# ruff: noqa: EM101, PLR0913
"""Public discovery endpoints for API v1."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from ninja import Router

from accounts.api_serializers import (
    serialize_education,
    serialize_profile,
    serialize_work_experience,
)
from accounts.models import UserProfile
from config.api_common import ApiError, build_paginated_response, paginate_queryset

from .views import (
    MAX_SEARCH_RESULTS,
    SearchFilters,
    _apply_optional_filters,
    _collect_available_values,
    _serialize_user,
)

router = Router(tags=["public"])


def _get_or_create_profile(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


@router.get("/users/search")
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
    exact_match = UserModel.objects.filter(username__iexact=query).first()
    users_qs = (
        UserModel.objects.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
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


@router.get("/users/{username}")
def public_user_profile_endpoint(request, username: str):
    """Return a public user profile."""
    UserModel = get_user_model()
    user = get_object_or_404(UserModel, username=username)
    profile = _get_or_create_profile(user)
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.get_full_name() or user.username,
            "email": user.email,
        },
        "profile": serialize_profile(profile),
        "work_experiences": [
            serialize_work_experience(item) for item in profile.work_experiences.all()
        ],
        "educations": [serialize_education(item) for item in profile.educations.all()],
    }
