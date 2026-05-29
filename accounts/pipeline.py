"""Social auth pipeline functions for accounts app."""

import logging
import secrets

from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)

# AtomGit 用户名前缀；为避免与本地 GitHub 用户名冲突，AtomGit 用户名一律带前缀
ATOMGIT_USERNAME_PREFIX = "ag-"
# 冲突时追加的随机数字位数（严格 3 位）
RANDOM_SUFFIX_DIGITS = 3


def _extract_base_username(details, response, backend) -> str:
    """Pick the source username from social-auth details/response."""
    candidates = (
        details.get("username") if details else None,
        (response or {}).get("login") if response else None,
        (response or {}).get("preferred_username") if response else None,
        (response or {}).get("screen_name") if response else None,
    )
    for value in candidates:
        if value:
            text = str(value).strip()
            if text:
                return text
    # Fallback：使用 backend 名称 + 随机后缀，理论上不会触发
    return backend.name


def _build_candidate_username(base: str, backend_name: str) -> str:
    """Apply provider-specific naming rules to the raw username."""
    if backend_name == "atomgit":
        return f"{ATOMGIT_USERNAME_PREFIX}{base}"
    return base


def _random_suffix() -> str:
    """Generate a strict 3-digit random numeric suffix (100-999)."""
    return f"{secrets.randbelow(900) + 100}"


def assign_social_username(
    strategy,
    details,
    backend,
    user=None,
    *args,
    **kwargs,
):
    """
    Assign the new account's username based on provider-specific rules.

    - GitHub: directly use GitHub login; on conflict append ``-NNN`` (3 digits).
    - AtomGit: use ``ag-<login>``; on conflict append ``-NNN`` (3 digits).
    - Other providers: use the raw login; on conflict append ``-NNN``.

    Existing users (binding/relogin) keep their current username.
    """
    if user is not None:
        # 已有用户走绑定/复登流程，不再重新分配 username
        return None

    base = _extract_base_username(
        details, response=kwargs.get("response"), backend=backend
    )
    candidate = _build_candidate_username(base, backend.name)

    UserModel = get_user_model()
    if not UserModel.objects.filter(username=candidate).exists():
        return {"username": candidate}

    # 冲突时严格使用 3 位随机数字后缀，循环重试直到无冲突
    while True:
        attempt = f"{candidate}-{_random_suffix()}"
        if not UserModel.objects.filter(username=attempt).exists():
            logger.info(
                "Resolved social username conflict for provider %s: %s -> %s",
                backend.name,
                candidate,
                attempt,
            )
            return {"username": attempt}


def update_user_profile_from_github(
    backend, details, response, user=None, *args, **kwargs
):
    """
    Update user profile with GitHub data if user logs in via GitHub.

    Only updates fields that are currently empty to avoid overwriting user-modified data.
    This pipeline function is called after user authentication.

    Args:
        backend: Social auth backend instance
        details: Dict with user details from provider
        response: Dict with full provider response
        user: User instance (may be None)
        *args: Additional positional arguments
        **kwargs: Additional keyword arguments

    Returns:
        None or dict to update pipeline data

    """
    # Only process for GitHub backend
    if backend.name != "github":
        return

    # Skip if no user (shouldn't happen in normal flow)
    if not user:
        return

    # Import here to avoid circular imports
    from accounts.models import UserProfile

    # Get or create user profile
    profile, created = UserProfile.objects.get_or_create(user=user)

    # Track if any changes were made
    updated = False

    # Update bio if empty
    if not profile.bio and response.get("bio"):
        profile.bio = response["bio"]
        updated = True
        logger.info(
            "Updated bio for user %s from GitHub",
            user.username,
            extra={"user_id": user.id, "field": "bio"},
        )

    # Update location if empty
    if not profile.location and response.get("location"):
        profile.location = response["location"]
        updated = True
        logger.info(
            "Updated location for user %s from GitHub",
            user.username,
            extra={"user_id": user.id, "field": "location"},
        )

    # Update company if empty
    if not profile.company and response.get("company"):
        # GitHub company field may start with @ symbol, remove it
        company = response["company"]
        if company.startswith("@"):
            company = company[1:]
        profile.company = company
        updated = True
        logger.info(
            "Updated company for user %s from GitHub",
            user.username,
            extra={"user_id": user.id, "field": "company"},
        )

    # Update GitHub URL if empty
    if not profile.github_url and response.get("html_url"):
        profile.github_url = response["html_url"]
        updated = True
        logger.info(
            "Updated github_url for user %s from GitHub",
            user.username,
            extra={"user_id": user.id, "field": "github_url"},
        )

    # Update homepage/blog URL if empty
    if not profile.homepage_url and response.get("blog"):
        # GitHub blog field can be a URL or empty string
        blog = response["blog"].strip()
        if blog:
            # Add https:// if no protocol specified
            if not blog.startswith(("http://", "https://")):
                blog = f"https://{blog}"
            profile.homepage_url = blog
            updated = True
            logger.info(
                "Updated homepage_url for user %s from GitHub",
                user.username,
                extra={"user_id": user.id, "field": "homepage_url"},
            )

    # Save profile if any changes were made
    if updated:
        profile.save()
        logger.info(
            "Saved profile updates for user %s from GitHub",
            user.username,
            extra={"user_id": user.id, "profile_created": created},
        )
