"""Background tasks for accounts app."""

import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django_tasks import task

logger = logging.getLogger(__name__)


def _build_password_reset_url(
    domain: str, use_https: bool, uid: str, token: str
) -> str:
    """Build the password-reset URL for either the frontend or Django pages."""
    if settings.FRONTEND_APP_URL:
        query = urlencode({"uid": uid, "token": token})
        return (
            f"{settings.FRONTEND_APP_URL.rstrip('/')}"
            f"{settings.FRONTEND_PASSWORD_RESET_PATH}?{query}"
        )

    protocol = "https" if use_https else "http"
    return f"{protocol}://{domain}/accounts/password-reset-confirm/{uid}/{token}/"


@task()
def send_password_reset_email(user_id, domain, use_https=False):
    """Send password reset email to user."""
    from django.contrib.auth import get_user_model

    User = get_user_model()

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return

    # 生成重置令牌
    token = default_token_generator.make_token(user)
    uid = urlsafe_base64_encode(force_bytes(user.pk))

    # 构建重置链接
    reset_url = _build_password_reset_url(domain, use_https, uid, token)

    # 渲染邮件内容
    context = {
        "user": user,
        "reset_url": reset_url,
        "domain": domain,
    }

    subject = "重置您的 Open Share 密码"
    html_message = render_to_string("emails/password_reset_email.html", context)
    text_message = render_to_string("emails/password_reset_email.txt", context)

    # 发送邮件
    send_mail(
        subject=subject,
        message=text_message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        html_message=html_message,
    )
