"""Django Ninja auth endpoints for API v1."""

from typing import Any

from django.http import HttpRequest
from ninja import Router, Schema
from ninja.security import HttpBearer

from .services.authentication import PasswordLoginError, authenticate_by_login_id
from .services.jwt_tokens import (
    create_access_token,
    get_access_token_expires_in,
    get_user_from_access_token,
)

router = Router(tags=["auth"])


class ErrorResponseSchema(Schema):
    """Standard API error response."""

    code: str
    message: str


class AuthenticatedUserSchema(Schema):
    """Serialized authenticated user."""

    id: int
    username: str
    email: str
    is_active: bool


class LoginRequestSchema(Schema):
    """Login request payload."""

    account: str
    password: str


class LoginResponseSchema(Schema):
    """Login success response."""

    access_token: str
    token_type: str
    expires_in: int
    user: AuthenticatedUserSchema


class VerifyResponseSchema(Schema):
    """Verify success response."""

    authenticated: bool
    user: AuthenticatedUserSchema


def _serialize_user(user: Any) -> AuthenticatedUserSchema:
    """Build the shared user response payload."""
    return AuthenticatedUserSchema(
        id=user.pk,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
    )


class JWTBearerAuth(HttpBearer):
    """Bearer auth that resolves users from JWT access tokens."""

    def authenticate(self, request: HttpRequest, token: str) -> Any | None:
        """Resolve the current user from the presented bearer token."""
        user = get_user_from_access_token(token)
        if not user:
            return None

        request.user = user
        request._cached_user = user
        return user


jwt_bearer_auth = JWTBearerAuth()


@router.post(
    "/login",
    response={
        200: LoginResponseSchema,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        409: ErrorResponseSchema,
    },
)
def login_endpoint(request: HttpRequest, payload: LoginRequestSchema):
    """Authenticate a user and issue a JWT access token."""
    try:
        user = authenticate_by_login_id(
            payload.account, payload.password, request=request
        )
    except PasswordLoginError as exc:
        return exc.status_code, ErrorResponseSchema(code=exc.code, message=exc.message)

    return LoginResponseSchema(
        access_token=create_access_token(user),
        token_type="Bearer",
        expires_in=get_access_token_expires_in(),
        user=_serialize_user(user),
    )


@router.get(
    "/verify",
    auth=jwt_bearer_auth,
    response={200: VerifyResponseSchema, 401: ErrorResponseSchema},
)
def verify_endpoint(request: HttpRequest):
    """Validate the access token and return the current user."""
    return VerifyResponseSchema(
        authenticated=True,
        user=_serialize_user(request.auth),
    )
