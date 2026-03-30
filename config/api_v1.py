"""Django Ninja API configuration for v1."""

from django.http import HttpRequest
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, ValidationError

from accounts.api_v1 import router as accounts_auth_router

api_v1 = NinjaAPI(
    title="OpenShare API",
    version="1.0.0",
    urls_namespace="api-v1",
)


def _authentication_error_handler(request: HttpRequest, exc: AuthenticationError):
    """Return a consistent JWT auth failure payload."""
    return api_v1.create_response(
        request,
        {"code": "invalid_token", "message": "Token 无效或已过期"},
        status=exc.status_code,
    )


def _validation_error_handler(request: HttpRequest, exc: ValidationError):
    """Return a consistent payload for request validation failures."""
    return api_v1.create_response(
        request,
        {
            "code": "validation_error",
            "message": "请求参数校验失败",
            "detail": exc.errors,
        },
        status=422,
    )


api_v1.add_exception_handler(AuthenticationError, _authentication_error_handler)
api_v1.add_exception_handler(ValidationError, _validation_error_handler)
api_v1.add_router("/auth/", accounts_auth_router)
