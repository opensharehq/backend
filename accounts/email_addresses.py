"""Helpers for normalized email handling across the accounts app."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model

MERGED_EMAIL_DOMAIN = "users.invalid"


def normalize_email_address(email: str | None) -> str:
    """Return the canonical storage form for a user email address."""
    return (email or "").strip().lower()


def build_merged_placeholder_email(user_id: int) -> str:
    """Return a deterministic placeholder email for merged source accounts."""
    return f"merged+{user_id}@{MERGED_EMAIL_DOMAIN}"


def matching_email_users(email: str | None):
    """Return users whose email matches the normalized value."""
    normalized_email = normalize_email_address(email)
    UserModel = get_user_model()
    if not normalized_email:
        return UserModel.objects.none()
    return UserModel.objects.filter(email__iexact=normalized_email).order_by("pk")


def email_in_use(email: str | None, *, exclude_user: Any | None = None) -> bool:
    """Return whether a normalized email is already used by another user."""
    qs = matching_email_users(email)
    if exclude_user is not None:
        qs = qs.exclude(pk=exclude_user.pk)
    return qs.exists()


def _candidate_sort_key(user: Any) -> tuple[int, int, int, int]:
    """Sort candidate accounts so the best login/reset target comes first."""
    return (
        0 if user.merged_into_id is None else 1,
        0 if user.is_active else 1,
        0 if user.has_usable_password() else 1,
        user.pk,
    )


def get_email_login_candidates(email: str | None) -> list[Any]:
    """Return matching users ordered by login priority."""
    return sorted(matching_email_users(email), key=_candidate_sort_key)


def select_password_reset_user(email: str | None) -> tuple[Any | None, list[Any]]:
    """Return the best password-reset candidate together with all matches."""
    candidates = get_email_login_candidates(email)
    for candidate in candidates:
        if candidate.has_usable_password():
            return candidate, candidates
    return None, candidates
