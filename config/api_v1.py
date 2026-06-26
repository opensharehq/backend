"""Django Ninja API configuration for v1."""

from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, ValidationError

from accounts.api_me_v1 import router as accounts_me_router
from accounts.api_orgs_v1 import router as organizations_router
from accounts.api_v1 import router as accounts_auth_router
from common.api_v1 import router as common_router
from homepage.api_v1 import router as homepage_router
from messages.api_v1 import router as messages_router
from points.api_v1 import router as points_router
from shop.api_v1 import router as shop_router
from talent_reach.api_v1 import router as talent_reach_router

from .api_common import ApiError, translate_error_detail

api_v1 = NinjaAPI(title="OpenShare API", version="1.0.0", urls_namespace="api-v1")


def _authentication_error_handler(request: HttpRequest, exc: AuthenticationError):
    """Return a consistent JWT auth failure payload."""
    return api_v1.create_response(
        request,
        {"code": "invalid_token", "message": "The token is invalid or has expired."},
        status=exc.status_code,
    )


def _validation_error_handler(request: HttpRequest, exc: ValidationError):
    """Return a consistent payload for request validation failures."""
    return api_v1.create_response(
        request,
        {
            "code": "validation_error",
            "message": "Request validation failed.",
            "detail": exc.errors,
        },
        status=422,
    )


def _api_error_handler(request: HttpRequest, exc: ApiError):
    """Return a structured payload for application-level API errors."""
    return api_v1.create_response(
        request,
        {
            "code": exc.code,
            "message": exc.message,
            "detail": translate_error_detail(exc.detail),
        },
        status=exc.status_code,
    )


def _permission_denied_handler(request: HttpRequest, exc: PermissionDenied):
    """Normalize permission failures to the shared error shape."""
    return api_v1.create_response(
        request,
        {
            "code": "forbidden",
            "message": "You do not have permission to perform this action.",
        },
        status=403,
    )


def _not_found_handler(request: HttpRequest, exc: Http404):
    """Normalize not-found errors to the shared error shape."""
    return api_v1.create_response(
        request,
        {"code": "not_found", "message": "The requested resource was not found."},
        status=404,
    )


api_v1.add_exception_handler(ApiError, _api_error_handler)
api_v1.add_exception_handler(AuthenticationError, _authentication_error_handler)
api_v1.add_exception_handler(Http404, _not_found_handler)
api_v1.add_exception_handler(PermissionDenied, _permission_denied_handler)
api_v1.add_exception_handler(ValidationError, _validation_error_handler)
api_v1.add_router("/auth/", accounts_auth_router)
api_v1.add_router("/common/", common_router)
api_v1.add_router("/me/", accounts_me_router)
api_v1.add_router("/organizations/", organizations_router)
api_v1.add_router("/public/", homepage_router)
api_v1.add_router("/messages/", messages_router)
api_v1.add_router("/shop/", shop_router)
api_v1.add_router("/points/", points_router)
api_v1.add_router("/talent-reach/", talent_reach_router)
