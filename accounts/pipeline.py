"""Social auth pipeline functions for accounts app."""

import logging

from accounts.email_addresses import email_in_use, normalize_email_address
from accounts.social_auth import EmailConflictRequiresBinding

logger = logging.getLogger(__name__)


def prevent_duplicate_email_signup(
    backend,
    details,
    response,
    user=None,
    new_association=False,
    *args,
    **kwargs,
):
    """Block social-auth account creation when the email is already owned."""
    if not new_association:
        return

    email = normalize_email_address(details.get("email") or response.get("email"))
    if not email:
        return

    if email_in_use(email, exclude_user=user):
        raise EmailConflictRequiresBinding(backend)


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
