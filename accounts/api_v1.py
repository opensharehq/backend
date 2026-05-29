# ruff: noqa: EM101
"""Django Ninja auth endpoints for API v1."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model, logout
from django.contrib.auth import login as django_login
from django.http import HttpRequest, HttpResponseRedirect
from django.urls import reverse
from ninja import Router, Schema
from ninja.security import HttpBearer
from social_django.models import UserSocialAuth

from config.api_common import (
    ApiError,
    ErrorResponseSchema,
)

from .services.jwt_tokens import (
    get_user_from_access_token,
    issue_token_pair,
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
    "atomgit": {
        "name": "AtomGit",
        "icon": "git-branch",
        "key": "SOCIAL_AUTH_ATOMGIT_KEY",
        "secret": "SOCIAL_AUTH_ATOMGIT_SECRET",
        "profile_url_template": "https://atomgit.com/{username}",
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


class RefreshRequestSchema(Schema):
    """Refresh request payload."""

    refresh_token: str


class SocialExchangeRequestSchema(Schema):
    """One-time social-login exchange payload."""

    exchange_code: str


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


@lru_cache(maxsize=1)
def _configured_providers() -> tuple[tuple[str, dict[str, str]], ...]:
    """
    Return providers configured in settings (process-local lazy cache).

    Provider configuration is determined by settings at startup and never
    changes during the process lifetime, so we cache the result permanently.
    Call ``_configured_providers.cache_clear()`` in tests if needed.
    """
    providers: list[tuple[str, dict[str, str]]] = []
    for provider, provider_info in SOCIAL_PROVIDERS.items():
        key = getattr(settings, provider_info["key"], "")
        secret = getattr(settings, provider_info["secret"], "")
        if key and secret:
            providers.append((provider, provider_info))
    return tuple(providers)


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
    """
    Return the current user's configured social connections (flat list).

    A user may bind multiple accounts of the same provider (e.g. two GitHub
    accounts), so we expand each ``UserSocialAuth`` row into its own entry
    instead of collapsing one-per-provider. Unconnected providers are not
    included; the SPA's add-account dialog uses ``/auth/social/providers``
    to discover bindable platforms.
    """
    configured = dict(_configured_providers())

    connections: list[SocialConnectionSchema] = []
    user_social_auths = UserSocialAuth.objects.filter(user=request.auth).order_by(
        "provider", "id"
    )
    connected_count = 0
    for social_auth in user_social_auths:
        provider_info = configured.get(social_auth.provider)
        if provider_info is None:
            # Provider 不再启用时，不在绑定列表中展示，但仍计入认证方式总数
            connected_count += 1
            continue
        connections.append(
            SocialConnectionSchema(
                provider=social_auth.provider,
                name=provider_info["name"],
                icon=provider_info["icon"],
                is_connected=True,
                uid=str(social_auth.uid),
                username=_extract_social_username(social_auth),
                profile_url=_extract_social_profile_url(social_auth, provider_info),
                social_auth_id=social_auth.id,
            )
        )
        connected_count += 1

    # 仅 OAuth 鉴权：保留至少 1 个社交绑定即可断开其它绑定
    return SocialConnectionsResponseSchema(
        can_disconnect=connected_count > 1,
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

    other_social_auths = UserSocialAuth.objects.filter(user=request.auth).exclude(
        id=association_id
    )
    if not other_social_auths.exists():
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
    """
    Start a social-login flow that hands off to the frontend callback.

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
