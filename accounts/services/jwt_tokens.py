"""JWT helpers for API authentication."""

from datetime import timedelta
from typing import Any

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

ACCESS_TOKEN_TYPE = "access"  # noqa: S105 - JWT claim discriminator, not a secret
REQUIRED_TOKEN_CLAIMS = ["sub", "type", "iat", "exp"]


def get_access_token_expires_in() -> int:
    """Return the configured JWT access token lifetime in seconds."""
    return settings.JWT_ACCESS_TTL_SECONDS


def create_access_token(user: Any) -> str:
    """Create a signed access token for the provided user."""
    issued_at = timezone.now()
    expires_at = issued_at + timedelta(seconds=get_access_token_expires_in())
    payload = {
        "sub": str(user.pk),
        "type": ACCESS_TOKEN_TYPE,
        "iat": issued_at,
        "exp": expires_at,
    }
    return jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode an access token and validate its structure."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": REQUIRED_TOKEN_CLAIMS},
        )
    except (jwt.InvalidTokenError, TypeError, ValueError):
        return None

    if payload.get("type") != ACCESS_TOKEN_TYPE:
        return None

    return payload


def get_user_from_access_token(token: str) -> Any | None:
    """Resolve an active, non-merged user from a valid access token."""
    payload = decode_access_token(token)
    if not payload:
        return None

    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        return None

    UserModel = get_user_model()
    user = UserModel._default_manager.filter(pk=user_id).first()
    if not user or not user.is_active or user.merged_into_id:
        return None

    return user
