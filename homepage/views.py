"""Views for the homepage app."""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse

from accounts.models import UserProfile

from .cache import get_search_cache_version

MAX_SEARCH_RESULTS = 150
PAGE_SIZE = 12
SEARCH_RESULTS_CACHE_TIMEOUT = 60


def index(request):
    """Render the homepage index page."""
    return render(request, "homepage/index.html")


@dataclass
class SearchFilters:
    """Filters extracted from the incoming request."""

    location: str = ""
    company: str = ""
    sort: str = "relevance"

    @classmethod
    def from_request(cls, request):
        """Build filters from query parameters."""
        return cls(
            location=request.GET.get("location", "").strip(),
            company=request.GET.get("company", "").strip(),
            sort=request.GET.get("sort", "relevance"),
        )

    def ordering(self) -> Iterable[str]:
        """Return database ordering for the chosen sort."""
        sort_map = {
            "relevance": ["username"],
            "username": ["username"],
        }
        return sort_map.get(self.sort, sort_map["relevance"])


def _apply_optional_filters(queryset, filters: SearchFilters):
    """Apply optional location and company filters."""
    lookups = {
        "profile__location__icontains": filters.location,
        "profile__company__icontains": filters.company,
    }
    criteria = {lookup: value for lookup, value in lookups.items() if value}
    if criteria:
        queryset = queryset.filter(**criteria)
    return queryset


def _collect_available_values(queryset, field: str) -> list[str]:
    """Return ordered distinct values for the requested profile field."""
    lookup = f"profile__{field}"
    return list(
        queryset.exclude(**{f"{lookup}__isnull": True})
        .exclude(**{f"{lookup}__exact": ""})
        .values_list(lookup, flat=True)
        .distinct()
        .order_by(lookup)
    )


def _resolve_profile(user):
    try:
        return user.profile
    except UserProfile.DoesNotExist:  # pragma: no cover - defensive
        return None


def _serialize_user(user):
    profile = _resolve_profile(user)
    return {
        "username": user.username,
        "display_name": user.get_full_name() or user.username,
        "bio": getattr(profile, "bio", "") or "",
        "company": getattr(profile, "company", "") or "",
        "location": getattr(profile, "location", "") or "",
        "profile_url": reverse("public_profile", args=[user.username]),
        "avatar_url": f"https://ui-avatars.com/api/?name={user.username}&background=random",
    }


def user_search(request):
    """Search for users by keyword and render results with filters."""
    query = request.GET.get("q", "").strip()
    if not query:
        messages.info(request, "请输入要搜索的关键词。")
        return redirect("homepage:index")

    User = get_user_model()
    exact_match = User.objects.filter(username__iexact=query).first()
    if exact_match:
        return redirect("public_profile", username=exact_match.username)

    filters = SearchFilters.from_request(request)

    cache_key = _build_search_cache_key(
        query=query,
        filters=filters,
    )
    cached_context = cache.get(cache_key)
    if cached_context is not None:
        return render(request, "homepage/search_results.html", cached_context)

    users_qs = (
        User.objects.filter(
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

    users_qs = _apply_optional_filters(users_qs, filters)

    users_qs = users_qs.order_by(*filters.ordering())

    total_matches = users_qs.count()
    available_locations = _collect_available_values(users_qs, "location")
    available_companies = _collect_available_values(users_qs, "company")

    limited_users = users_qs[:MAX_SEARCH_RESULTS]
    results = [_serialize_user(user) for user in limited_users]

    context = {
        "query": query,
        "results": results,
        "results_json": json.dumps(results, ensure_ascii=False),
        "results_count": total_matches,
        "max_results": MAX_SEARCH_RESULTS,
        "filters": {
            "location": filters.location,
            "company": filters.company,
            "sort": filters.sort,
        },
        "available_locations": available_locations,
        "available_companies": available_companies,
        "page_size": PAGE_SIZE,
    }

    cache.set(cache_key, context, SEARCH_RESULTS_CACHE_TIMEOUT)

    return render(request, "homepage/search_results.html", context)


def _build_search_cache_key(
    *,
    query: str,
    filters: SearchFilters,
) -> str:
    payload = {
        "query": query,
        "location": filters.location,
        "company": filters.company,
        "sort": filters.sort,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    version = get_search_cache_version()
    return f"homepage:user_search:{version}:{digest}"
