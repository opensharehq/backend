"""JWT helpers for API authentication."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from accounts.models import RefreshToken

ACCESS_TOKEN_TYPE = "access"  # noqa: S105 - JWT claim discriminator, not a secret
REFRESH_TOKEN_TYPE = "refresh"  # noqa: S105 - JWT claim discriminator, not a secret
REQUIRED_TOKEN_CLAIMS = ["sub", "type", "iat", "exp"]
REQUIRED_REFRESH_TOKEN_CLAIMS = [*REQUIRED_TOKEN_CLAIMS, "jti"]


def get_access_token_expires_in() -> int:
    """Return the configured JWT access token lifetime in seconds."""
    return settings.JWT_ACCESS_TTL_SECONDS


def get_refresh_token_expires_in() -> int:
    """Return the configured JWT refresh token lifetime in seconds."""
    return settings.JWT_REFRESH_TTL_SECONDS


def _encode_token(payload: dict[str, Any]) -> str:
    """Encode a JWT payload with the configured signing settings."""
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


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
    return _encode_token(payload)


def create_refresh_token(user: Any) -> str:
    """Create a signed refresh token and persist its server-side record."""
    issued_at = timezone.now()
    expires_at = issued_at + timedelta(seconds=get_refresh_token_expires_in())
    record = RefreshToken.objects.create(user=user, expires_at=expires_at)
    payload = {
        "sub": str(user.pk),
        "type": REFRESH_TOKEN_TYPE,
        "jti": str(record.jti),
        "iat": issued_at,
        "exp": expires_at,
    }
    return _encode_token(payload)


def issue_token_pair(user: Any) -> dict[str, Any]:
    """Return a standard token pair payload for API auth flows."""
    return {
        "access_token": create_access_token(user),
        "refresh_token": create_refresh_token(user),
        "token_type": "Bearer",
        "expires_in": get_access_token_expires_in(),
        "refresh_expires_in": get_refresh_token_expires_in(),
    }


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode an access token and validate its structure."""
    return _decode_token(token, ACCESS_TOKEN_TYPE, REQUIRED_TOKEN_CLAIMS)


def _decode_token(
    token: str,
    expected_type: str,
    required_claims: list[str],
) -> dict[str, Any] | None:
    """Decode a token and validate its shared structure."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": required_claims},
        )
    except (jwt.InvalidTokenError, TypeError, ValueError):
        return None

    if payload.get("type") != expected_type:
        return None

    return payload


def decode_refresh_token(token: str) -> dict[str, Any] | None:
    """Decode a refresh token and validate its structure."""
    return _decode_token(
        token,
        REFRESH_TOKEN_TYPE,
        REQUIRED_REFRESH_TOKEN_CLAIMS,
    )


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


def _get_refresh_token_user_id(payload: dict[str, Any]) -> int | None:
    """Return the user id embedded in a refresh token payload."""
    try:
        return int(payload["sub"])
    except (TypeError, ValueError, KeyError):
        return None


def _get_refresh_record(payload: dict[str, Any]) -> RefreshToken | None:
    try:
        jti = uuid.UUID(str(payload["jti"]))
    except (TypeError, ValueError, KeyError):
        return None

    return RefreshToken.objects.select_related("user").filter(jti=jti).first()


def _get_refresh_record_user(
    payload: dict[str, Any],
) -> tuple[Any, RefreshToken] | None:
    """Resolve the refresh token owner while validating the bound subject."""
    record = _get_refresh_record(payload)
    if record is None:
        return None

    payload_user_id = _get_refresh_token_user_id(payload)
    user = record.user
    if payload_user_id is None or payload_user_id != user.pk:
        return None

    if not user.is_active or user.merged_into_id:
        return None

    return user, record


def _revoke_refresh_record_if_active(jti: uuid.UUID, now) -> bool:
    """Revoke a refresh token only if it is still active."""
    return (
        RefreshToken.objects.filter(
            jti=jti,
            revoked_at__isnull=True,
            expires_at__gt=now,
        ).update(revoked_at=now)
        == 1
    )


def get_user_from_refresh_token(token: str) -> Any | None:
    """Resolve an active, non-merged user from a refresh token."""
    payload = decode_refresh_token(token)
    if not payload:
        return None

    refresh_record_user = _get_refresh_record_user(payload)
    if refresh_record_user is None:
        return None

    user, record = refresh_record_user
    if not record.is_active:
        return None

    return user


def revoke_refresh_token(token: str) -> bool:
    """Mark a refresh token record as revoked."""
    payload = decode_refresh_token(token)
    if not payload:
        return False

    refresh_record_user = _get_refresh_record_user(payload)
    if refresh_record_user is None:
        return False

    _user, record = refresh_record_user
    return _revoke_refresh_record_if_active(record.jti, timezone.now())


def revoke_all_refresh_tokens_for_user(user: Any) -> int:
    """Revoke every active refresh token issued to the provided user."""
    now = timezone.now()
    return RefreshToken.objects.filter(
        user=user,
        revoked_at__isnull=True,
        expires_at__gt=now,
    ).update(revoked_at=now)


def rotate_refresh_token(token: str) -> tuple[Any, dict[str, Any]] | None:
    """Revoke the current refresh token and return a fresh token pair."""
    payload = decode_refresh_token(token)
    if not payload:
        return None

    refresh_record_user = _get_refresh_record_user(payload)
    if refresh_record_user is None:
        return None

    user, record = refresh_record_user
    now = timezone.now()

    with transaction.atomic():
        if not _revoke_refresh_record_if_active(record.jti, now):
            return None

        return user, issue_token_pair(user)
