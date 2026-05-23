# ruff: noqa: EM101
"""Django Ninja auth endpoints for API v1."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model, login as django_login, logout
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponseRedirect
from django.urls import reverse
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from ninja import Router, Schema
from ninja.security import HttpBearer
from social_django.models import UserSocialAuth

from config.api_common import (
    ApiError,
    ErrorResponseSchema,
    form_error_detail,
    validate_form,
)

from .email_addresses import select_password_reset_user
from .forms import (
    ChangeEmailForm as ChangeEmailDjangoForm,
)
from .forms import (
    CustomPasswordChangeForm,
    PasswordResetConfirmForm,
    SignUpForm,
)
from .forms import (
    PasswordResetRequestForm as PasswordResetRequestDjangoForm,
)
from .services.authentication import PasswordLoginError, authenticate_by_login_id
from .services.jwt_tokens import (
    get_user_from_access_token,
    issue_token_pair,
    revoke_all_refresh_tokens_for_user,
    revoke_refresh_token,
    rotate_refresh_token,
)
from .services.social_exchange import (
    SocialExchangeUnavailableError,
    consume_exchange_code,
    create_exchange_code,
)
from .social_auth import (
    FrontendSocialCallbackNotConfigured,
    social_api_callback_path,
)
from .social_auth import (
    build_frontend_social_callback_url as build_social_callback_url,
)
from .tasks import send_password_reset_email

router = Router(tags=["auth"])
logger = logging.getLogger(__name__)

SOCIAL_PROVIDERS = {
    "github": {
        "name": "GitHub",
        "icon": "bi-github",
        "key": "SOCIAL_AUTH_GITHUB_KEY",
        "secret": "SOCIAL_AUTH_GITHUB_SECRET",
        "profile_url_template": "https://github.com/{username}",
    },
    "google-oauth2": {
        "name": "Google",
        "icon": "bi-google",
        "key": "SOCIAL_AUTH_GOOGLE_OAUTH2_KEY",
        "secret": "SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET",
    },
    "bitbucket-oauth2": {
        "name": "Bitbucket",
        "icon": "bi-git",
        "key": "SOCIAL_AUTH_BITBUCKET_OAUTH2_KEY",
        "secret": "SOCIAL_AUTH_BITBUCKET_OAUTH2_SECRET",
        "profile_url_template": "https://bitbucket.org/{username}",
    },
    "docker": {
        "name": "Docker",
        "icon": "bi-box-seam",
        "key": "SOCIAL_AUTH_DOCKER_KEY",
        "secret": "SOCIAL_AUTH_DOCKER_SECRET",
        "profile_url_template": "https://hub.docker.com/u/{username}",
    },
    "facebook": {
        "name": "Facebook",
        "icon": "bi-facebook",
        "key": "SOCIAL_AUTH_FACEBOOK_KEY",
        "secret": "SOCIAL_AUTH_FACEBOOK_SECRET",
        "profile_url_template": "https://facebook.com/{username}",
    },
    "gitlab": {
        "name": "GitLab",
        "icon": "bi-gitlab",
        "key": "SOCIAL_AUTH_GITLAB_KEY",
        "secret": "SOCIAL_AUTH_GITLAB_SECRET",
        "profile_url_template": "https://gitlab.com/{username}",
    },
    "gitea": {
        "name": "Gitea",
        "icon": "bi-git",
        "key": "SOCIAL_AUTH_GITEA_KEY",
        "secret": "SOCIAL_AUTH_GITEA_SECRET",
    },
    "gitee": {
        "name": "Gitee",
        "icon": "git-branch",
        "key": "SOCIAL_AUTH_GITEE_KEY",
        "secret": "SOCIAL_AUTH_GITEE_SECRET",
        "profile_url_template": "https://gitee.com/{username}",
    },
    "linkedin-oauth2": {
        "name": "LinkedIn",
        "icon": "bi-linkedin",
        "key": "SOCIAL_AUTH_LINKEDIN_OAUTH2_KEY",
        "secret": "SOCIAL_AUTH_LINKEDIN_OAUTH2_SECRET",
        "profile_url_template": "https://www.linkedin.com/in/{username}",
    },
    "twitter-oauth2": {
        "name": "Twitter",
        "icon": "bi-twitter-x",
        "key": "SOCIAL_AUTH_TWITTER_OAUTH2_KEY",
        "secret": "SOCIAL_AUTH_TWITTER_OAUTH2_SECRET",
        "profile_url_template": "https://twitter.com/{username}",
    },
    "huggingface": {
        "name": "HuggingFace",
        "icon": "brain",
        "key": "SOCIAL_AUTH_HUGGINGFACE_KEY",
        "secret": "SOCIAL_AUTH_HUGGINGFACE_SECRET",
    },
}


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


class RegisterRequestSchema(Schema):
    """Sign-up request payload."""

    username: str
    email: str
    password1: str
    password2: str


class RefreshRequestSchema(Schema):
    """Refresh request payload."""

    refresh_token: str


class SocialExchangeRequestSchema(Schema):
    """One-time social-login exchange payload."""

    exchange_code: str


class PasswordChangeRequestSchema(Schema):
    """Password change payload."""

    old_password: str
    new_password1: str
    new_password2: str


class EmailChangeRequestSchema(Schema):
    """Email change payload."""

    email: str
    password: str


class PasswordResetRequestSchema(Schema):
    """Password reset request payload."""

    email: str


class PasswordResetConfirmRequestSchema(Schema):
    """Password reset confirm payload."""

    uidb64: str
    token: str
    new_password1: str
    new_password2: str


class TokenResponseSchema(Schema):
    """Token pair response."""

    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    refresh_expires_in: int
    user: AuthenticatedUserSchema


class VerifyResponseSchema(Schema):
    """Verify success response."""

    authenticated: bool
    user: AuthenticatedUserSchema


class StatusResponseSchema(Schema):
    """Simple status response."""

    message: str


class LogoutResponseSchema(Schema):
    """Logout response payload."""

    revoked: bool


class SocialProviderSchema(Schema):
    """Configured social-login provider."""

    provider: str
    name: str
    icon: str
    start_url: str


class SocialProvidersResponseSchema(Schema):
    """Configured provider list response."""

    providers: list[SocialProviderSchema]


class SocialConnectionSchema(Schema):
    """Serialized social connection."""

    provider: str
    name: str
    icon: str
    is_connected: bool
    uid: str | None = None
    username: str | None = None
    profile_url: str | None = None
    social_auth_id: int | None = None


class SocialConnectionsResponseSchema(Schema):
    """Current user's social connection state."""

    has_password: bool
    can_disconnect: bool
    connections: list[SocialConnectionSchema]


def _serialize_user(user: Any) -> AuthenticatedUserSchema:
    """Build the shared user response payload."""
    return AuthenticatedUserSchema(
        id=user.pk,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
    )


def _build_token_response(user: Any) -> TokenResponseSchema:
    """Return the common token payload shape."""
    token_pair = issue_token_pair(user)
    return TokenResponseSchema(user=_serialize_user(user), **token_pair)


def _auth_error_message(exc: PasswordLoginError) -> str:
    """Map shared auth service errors to API-facing English messages."""
    return "Invalid username, email, or password."


def _configured_providers() -> list[tuple[str, dict[str, str]]]:
    """Return providers configured in settings."""
    providers: list[tuple[str, dict[str, str]]] = []
    for provider, provider_info in SOCIAL_PROVIDERS.items():
        key = getattr(settings, provider_info["key"], "")
        secret = getattr(settings, provider_info["secret"], "")
        if key and secret:
            providers.append((provider, provider_info))
    return providers


def _extract_social_username(social_auth: Any) -> str | None:
    """Return a human-readable login/username from social auth extra_data."""
    extra = getattr(social_auth, "extra_data", None) or {}
    for key in ("username", "login", "preferred_username", "screen_name"):
        value = extra.get(key)
        if value:
            return str(value)
    return None


def _extract_social_profile_url(
    social_auth: Any, provider_info: dict[str, str]
) -> str | None:
    """Resolve a best-effort profile URL for a social connection."""
    extra = getattr(social_auth, "extra_data", None) or {}
    for key in ("profile_url", "html_url", "profile", "url"):
        value = extra.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    template = provider_info.get("profile_url_template")
    username = _extract_social_username(social_auth)
    if template and username:
        return template.format(username=username)
    return None


def _get_provider_or_error(provider: str) -> dict[str, str]:
    """Resolve a configured provider or raise an API error."""
    provider_info = SOCIAL_PROVIDERS.get(provider)
    if provider_info is None:
        raise ApiError(
            "provider_not_found", 404, "The requested provider was not found."
        )

    if not getattr(settings, provider_info["key"], "") or not getattr(
        settings, provider_info["secret"], ""
    ):
        raise ApiError(
            "provider_not_configured",
            409,
            "This social-login provider is not configured.",
        )

    return provider_info


def _social_callback_url(provider: str) -> str:
    """Return the API callback path used after social auth completes."""
    return social_api_callback_path(provider)


def _build_frontend_social_callback_url(provider: str, **params: str) -> str:
    """Return the SPA callback URL for social-login handoff."""
    try:
        return build_social_callback_url(provider, **params)
    except FrontendSocialCallbackNotConfigured as exc:
        raise ApiError(
            "frontend_handoff_not_configured",
            503,
            "The frontend callback URL is not configured.",
        ) from exc


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
        200: TokenResponseSchema,
        401: ErrorResponseSchema,
    },
)
def login_endpoint(request: HttpRequest, payload: LoginRequestSchema):
    """Authenticate a user and issue a JWT token pair."""
    try:
        user = authenticate_by_login_id(
            payload.account, payload.password, request=request
        )
    except PasswordLoginError as exc:
        return 401, ErrorResponseSchema(
            code="invalid_credentials",
            message=_auth_error_message(exc),
        )

    return _build_token_response(user)


@router.post(
    "/register",
    response={201: TokenResponseSchema, 422: ErrorResponseSchema},
)
def register_endpoint(request: HttpRequest, payload: RegisterRequestSchema):
    """Register a new user and immediately issue a JWT token pair."""
    form = SignUpForm(payload.model_dump())
    if not validate_form(form):
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            form_error_detail(form),
        )

    try:
        user = form.save()
    except IntegrityError:
        form.add_error(
            "email",
            DjangoValidationError(
                "该邮箱已被注册", code="email_already_registered"
            ),
        )
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            form_error_detail(form),
        ) from None
    return 201, _build_token_response(user)


@router.post(
    "/refresh",
    response={200: TokenResponseSchema, 401: ErrorResponseSchema},
)
def refresh_endpoint(request: HttpRequest, payload: RefreshRequestSchema):
    """Rotate a refresh token and return a fresh token pair."""
    rotation_result = rotate_refresh_token(payload.refresh_token)
    if rotation_result is None:
        return 401, ErrorResponseSchema(
            code="invalid_token",
            message="The token is invalid or has expired.",
        )

    user, token_pair = rotation_result
    return TokenResponseSchema(user=_serialize_user(user), **token_pair)


@router.post(
    "/logout",
    response={200: LogoutResponseSchema, 401: ErrorResponseSchema},
)
def logout_endpoint(request: HttpRequest, payload: RefreshRequestSchema):
    """Revoke a refresh token."""
    if not revoke_refresh_token(payload.refresh_token):
        return 401, ErrorResponseSchema(
            code="invalid_token",
            message="The token is invalid or has expired.",
        )

    return LogoutResponseSchema(revoked=True)


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


@router.get(
    "/me",
    auth=jwt_bearer_auth,
    response={200: AuthenticatedUserSchema, 401: ErrorResponseSchema},
)
def me_endpoint(request: HttpRequest):
    """Return the authenticated API user."""
    return _serialize_user(request.auth)


@router.post(
    "/password/change",
    auth=jwt_bearer_auth,
    response={200: StatusResponseSchema, 422: ErrorResponseSchema},
)
def change_password_endpoint(
    request: HttpRequest, payload: PasswordChangeRequestSchema
):
    """Change the authenticated user's password."""
    form = CustomPasswordChangeForm(
        user=request.auth,
        data=payload.model_dump(),
    )
    if not validate_form(form):
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            form_error_detail(form),
        )

    form.save()
    revoke_all_refresh_tokens_for_user(request.auth)
    return StatusResponseSchema(message="Your password has been changed successfully.")


@router.post(
    "/email/change",
    auth=jwt_bearer_auth,
    response={200: AuthenticatedUserSchema, 422: ErrorResponseSchema},
)
def change_email_endpoint(request: HttpRequest, payload: EmailChangeRequestSchema):
    """Change the authenticated user's email."""
    form = ChangeEmailDjangoForm(user=request.auth, data=payload.model_dump())
    if not validate_form(form):
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            form_error_detail(form),
        )

    request.auth.email = form.cleaned_data["email"]
    try:
        request.auth.save(update_fields=["email"])
    except IntegrityError:
        form.add_error(
            "email",
            DjangoValidationError(
                "该邮箱已被其他用户使用", code="email_already_in_use"
            ),
        )
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            form_error_detail(form),
        ) from None
    return _serialize_user(request.auth)


@router.post(
    "/password/reset/request",
    response={200: StatusResponseSchema, 422: ErrorResponseSchema},
)
def password_reset_request_endpoint(
    request: HttpRequest,
    payload: PasswordResetRequestSchema,
):
    """Queue a password-reset email."""
    form = PasswordResetRequestDjangoForm(payload.model_dump())
    if not validate_form(form):
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            form_error_detail(form),
        )

    email = form.cleaned_data["email"]
    generic_response = StatusResponseSchema(
        message="If the email is registered, a reset link will be sent."
    )
    user, matching_users = select_password_reset_user(email)
    if not matching_users:
        return generic_response

    if len(matching_users) > 1:
        logger.warning(
            "Password reset requested for duplicate email %s across user ids %s",
            email,
            ",".join(str(user.pk) for user in matching_users),
        )

    if user is None:
        social_user = matching_users[0]
        providers = list(
            UserSocialAuth.objects.filter(user=social_user).values_list(
                "provider", flat=True
            )[:3]
        )
        if providers:
            logger.warning(
                "Password reset requested for passwordless social account: %s (%s)",
                social_user.pk,
                ",".join(providers),
            )
        return generic_response

    send_password_reset_email.enqueue(user.id, request.get_host(), request.is_secure())
    return generic_response


@router.post(
    "/password/reset/confirm",
    response={
        200: StatusResponseSchema,
        400: ErrorResponseSchema,
        422: ErrorResponseSchema,
    },
)
def password_reset_confirm_endpoint(
    request: HttpRequest,
    payload: PasswordResetConfirmRequestSchema,
):
    """Reset a password using the emailed token."""
    UserModel = get_user_model()

    try:
        uid = force_str(urlsafe_base64_decode(payload.uidb64))
        user = UserModel.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, UserModel.DoesNotExist):
        user = None

    if user is None or not default_token_generator.check_token(user, payload.token):
        return 400, ErrorResponseSchema(
            code="invalid_token",
            message="The password reset link is invalid or has expired.",
        )

    form = PasswordResetConfirmForm(
        user,
        {
            "new_password1": payload.new_password1,
            "new_password2": payload.new_password2,
        },
    )
    if not validate_form(form):
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            form_error_detail(form),
        )

    form.save()
    revoke_all_refresh_tokens_for_user(user)
    return StatusResponseSchema(message="Your password has been reset successfully.")


@router.get(
    "/social/providers",
    response=SocialProvidersResponseSchema,
)
def social_providers_endpoint(request: HttpRequest):
    """Return configured social-login providers."""
    providers = [
        SocialProviderSchema(
            provider=provider,
            name=provider_info["name"],
            icon=provider_info["icon"],
            start_url=f"/api/v1/auth/social/{provider}/start",
        )
        for provider, provider_info in _configured_providers()
    ]
    return SocialProvidersResponseSchema(providers=providers)


@router.get(
    "/social/connections",
    auth=jwt_bearer_auth,
    response={200: SocialConnectionsResponseSchema, 401: ErrorResponseSchema},
)
def social_connections_endpoint(request: HttpRequest):
    """Return the current user's configured social connections."""
    connected_providers = {
        auth.provider: auth for auth in UserSocialAuth.objects.filter(user=request.auth)
    }

    connections = []
    for provider, provider_info in _configured_providers():
        social_auth = connected_providers.get(provider)
        connections.append(
            SocialConnectionSchema(
                provider=provider,
                name=provider_info["name"],
                icon=provider_info["icon"],
                is_connected=social_auth is not None,
                uid=str(social_auth.uid) if social_auth else None,
                username=_extract_social_username(social_auth) if social_auth else None,
                profile_url=(
                    _extract_social_profile_url(social_auth, provider_info)
                    if social_auth
                    else None
                ),
                social_auth_id=social_auth.id if social_auth else None,
            )
        )

    has_password = request.auth.has_usable_password()
    total_auth_methods = (1 if has_password else 0) + len(connected_providers)
    return SocialConnectionsResponseSchema(
        has_password=has_password,
        can_disconnect=total_auth_methods > 1,
        connections=connections,
    )


@router.delete(
    "/social/connections/{provider}/{association_id}",
    auth=jwt_bearer_auth,
    response={
        200: StatusResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
)
def disconnect_social_account_endpoint(
    request: HttpRequest,
    provider: str,
    association_id: int,
):
    """Disconnect a social account while keeping at least one auth method."""
    social_auth = UserSocialAuth.objects.filter(
        id=association_id,
        user=request.auth,
        provider=provider,
    ).first()
    if social_auth is None:
        return 404, ErrorResponseSchema(
            code="not_found",
            message="The requested social connection was not found.",
        )

    has_password = request.auth.has_usable_password()
    other_social_auths = UserSocialAuth.objects.filter(user=request.auth).exclude(
        id=association_id
    )
    if not has_password and not other_social_auths.exists():
        return 400, ErrorResponseSchema(
            code="last_auth_method",
            message="You must keep at least one active sign-in method.",
        )

    provider_name = social_auth.provider
    social_auth.delete()
    return StatusResponseSchema(
        message=f'The "{provider_name}" social account has been disconnected.'
    )


@router.get("/social/{provider}/start")
def social_start_endpoint(
    request: HttpRequest,
    provider: str,
    access_token: str | None = None,
):
    """Start a social-login flow that hands off to the frontend callback.

    When ``access_token`` is provided and resolves to an active user, promote
    the JWT identity to a Django session so ``social_django`` can recognize
    the current user and perform *binding* (attaching a new provider to the
    existing account) instead of treating it as a new signup. SPA clients
    must pass this query parameter when the user initiates a bind flow from
    an authenticated page; omitting it yields the regular social-login flow.
    """
    _get_provider_or_error(provider)
    _build_frontend_social_callback_url(provider)

    if access_token:
        authed_user = get_user_from_access_token(access_token)
        if (
            authed_user is not None
            and authed_user.is_active
            and not authed_user.merged_into_id
        ):
            django_login(
                request,
                authed_user,
                backend="django.contrib.auth.backends.ModelBackend",
            )

    query = urlencode({"next": _social_callback_url(provider)})
    return HttpResponseRedirect(f"{reverse('social:begin', args=[provider])}?{query}")


@router.get("/social/{provider}/callback")
def social_callback_endpoint(request: HttpRequest, provider: str):
    """Bridge session-based social auth back into the SPA with an exchange code."""
    _get_provider_or_error(provider)

    if not request.user.is_authenticated:
        return HttpResponseRedirect(
            _build_frontend_social_callback_url(
                provider,
                error="authentication_failed",
            )
        )

    if not UserSocialAuth.objects.filter(user=request.user, provider=provider).exists():
        return HttpResponseRedirect(
            _build_frontend_social_callback_url(
                provider,
                error="provider_not_connected",
            )
        )

    try:
        exchange_code = create_exchange_code(request.user, provider)
    except SocialExchangeUnavailableError:
        logger.warning(
            "Unable to create social exchange code for user %s via %s",
            request.user.pk,
            provider,
        )
        return HttpResponseRedirect(
            _build_frontend_social_callback_url(
                provider,
                error="authentication_failed",
            )
        )
    logout(request)
    return HttpResponseRedirect(
        _build_frontend_social_callback_url(
            provider,
            exchange_code=exchange_code,
        )
    )


@router.post(
    "/social/exchange",
    response={
        200: TokenResponseSchema,
        401: ErrorResponseSchema,
        503: ErrorResponseSchema,
    },
)
def social_exchange_endpoint(
    request: HttpRequest,
    payload: SocialExchangeRequestSchema,
):
    """Exchange a one-time social-login code for a JWT token pair."""
    try:
        exchange_payload = consume_exchange_code(payload.exchange_code)
    except SocialExchangeUnavailableError:
        logger.warning("Social exchange attempted without Redis-backed cache")
        return 503, ErrorResponseSchema(
            code="social_exchange_unavailable",
            message="Social login is temporarily unavailable.",
        )
    if exchange_payload is None:
        return 401, ErrorResponseSchema(
            code="invalid_exchange_code",
            message="The social-login exchange code is invalid or has expired.",
        )

    UserModel = get_user_model()
    user = UserModel.objects.filter(pk=exchange_payload["user_id"]).first()
    if user is None or not user.is_active or user.merged_into_id:
        return 401, ErrorResponseSchema(
            code="invalid_token",
            message="The token is invalid or has expired.",
        )

    return _build_token_response(user)
