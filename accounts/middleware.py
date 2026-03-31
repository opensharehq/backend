"""Custom middleware for social-auth error handling."""

from __future__ import annotations

from django.urls import reverse
from social_django.middleware import (
    SocialAuthExceptionMiddleware as BaseSocialAuthExceptionMiddleware,
)

from .social_auth import (
    EMAIL_CONFLICT_ERROR_CODE,
    EmailConflictRequiresBinding,
    FrontendSocialCallbackNotConfigured,
    build_frontend_social_callback_url,
    is_api_social_callback_target,
)

EMAIL_CONFLICT_MESSAGE = (
    "该邮箱已绑定现有账号，请先使用原账号登录，再到社交账号页面完成绑定"
)


class SocialAuthExceptionMiddleware(BaseSocialAuthExceptionMiddleware):
    """Handle known social-auth exceptions with product-specific redirects."""

    def get_message(self, request, exception):
        """Return a user-facing message for a social-auth exception."""
        if isinstance(exception, EmailConflictRequiresBinding):
            return EMAIL_CONFLICT_MESSAGE
        return super().get_message(request, exception)

    def get_redirect_uri(self, request, exception):
        """Route social-auth failures back to the correct frontend surface."""
        if not isinstance(exception, EmailConflictRequiresBinding):
            return super().get_redirect_uri(request, exception)

        backend = getattr(request, "backend", None)
        provider = getattr(backend, "name", "")
        strategy = getattr(request, "social_strategy", None)
        next_target = None
        if strategy is not None:
            next_target = strategy.session_get("next")
        next_target = next_target or request.GET.get("next")

        if provider and is_api_social_callback_target(next_target, provider):
            try:
                return build_frontend_social_callback_url(
                    provider,
                    error=EMAIL_CONFLICT_ERROR_CODE,
                )
            except FrontendSocialCallbackNotConfigured:
                pass

        return reverse("accounts:sign_in")
