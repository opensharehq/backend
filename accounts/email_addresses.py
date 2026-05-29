"""Helpers for normalized email handling across the accounts app."""

from __future__ import annotations

MERGED_EMAIL_DOMAIN = "users.invalid"


def normalize_email_address(email: str | None) -> str:
    """Return the canonical storage form for a user email address."""
    return (email or "").strip().lower()


def build_merged_placeholder_email(user_id: int) -> str:
    """Return a deterministic placeholder email for merged source accounts."""
    return f"merged+{user_id}@{MERGED_EMAIL_DOMAIN}"
