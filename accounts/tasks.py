"""Background tasks for accounts app."""

import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django_tasks import task

logger = logging.getLogger(__name__)


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
    protocol = "https" if use_https else "http"
    reset_url = f"{protocol}://{domain}/accounts/password-reset-confirm/{uid}/{token}/"

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


@task()
def sync_user_organizations(user_id, provider):
    """
    Sync user's organizations from OAuth provider in background.

    Args:
        user_id: User ID
        provider: OAuth provider name (github, gitee, huggingface)

    """
    from django.contrib.auth import get_user_model

    from accounts.pipeline import (
        _fetch_gitee_orgs,
        _fetch_github_orgs,
        _fetch_huggingface_orgs,
    )

    User = get_user_model()

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.error("User %s not found for organization sync", user_id)
        return

    # Get social auth for the provider
    social = user.social_auth.filter(provider=provider).first()
    if not social:
        logger.warning(
            "No social auth found for user %s with provider %s",
            user.username,
            provider,
            extra={"user_id": user.id, "provider": provider},
        )
        return

    access_token = social.extra_data.get("access_token")
    if not access_token:
        logger.warning(
            "No access token found for user %s",
            user.username,
            extra={"user_id": user.id, "provider": provider},
        )
        return

    # Import here to avoid circular imports

    from accounts.models import Organization, OrganizationMembership

    try:
        # Fetch organizations from provider
        orgs_data = []
        if provider == "github":
            orgs_data = _fetch_github_orgs(access_token)
        elif provider == "gitee":
            orgs_data = _fetch_gitee_orgs(access_token)
        elif provider == "huggingface":
            orgs_data = _fetch_huggingface_orgs(access_token)
        else:
            logger.warning("Unsupported provider: %s", provider)
            return

        # Process each organization
        synced_count = 0
        for org_data in orgs_data:
            org, created = Organization.objects.update_or_create(
                provider=provider,
                provider_id=org_data["id"],
                defaults={
                    "name": org_data["name"],
                    "slug": org_data["slug"],
                    "description": org_data.get("description", ""),
                    "avatar_url": org_data.get("avatar_url", ""),
                    "website": org_data.get("website", ""),
                    "location": org_data.get("location", ""),
                    "provider_login": org_data.get("login", ""),
                },
            )

            # Create or update membership
            membership, mem_created = OrganizationMembership.objects.update_or_create(
                user=user,
                organization=org,
                defaults={
                    "role": org_data.get("role", OrganizationMembership.Role.MEMBER)
                },
            )

            synced_count += 1
            logger.info(
                "Synced organization %s for user %s (created: %s, membership created: %s, role: %s)",
                org.name,
                user.username,
                created,
                mem_created,
                membership.role,
                extra={
                    "user_id": user.id,
                    "org_id": org.id,
                    "provider": provider,
                    "role": membership.role,
                },
            )

        logger.info(
            "Background sync completed: %d organizations for user %s from %s",
            synced_count,
            user.username,
            provider,
            extra={
                "user_id": user.id,
                "provider": provider,
                "count": synced_count,
            },
        )

    except Exception as e:
        logger.exception(
            "Error syncing organizations for user %s: %s",
            user.username,
            e,
            extra={"user_id": user.id, "provider": provider},
        )
