"""Social auth pipeline functions for accounts app."""

import logging

logger = logging.getLogger(__name__)


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


def sync_organizations(backend, details, response, user=None, *args, **kwargs):
    """
    Trigger background task to sync user's organizations from OAuth provider.

    Instead of blocking the OAuth callback, this function schedules a background
    task to fetch and sync organizations from GitHub/Gitee/HuggingFace.

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
    # Only process for supported backends
    if backend.name not in ("github", "gitee", "huggingface"):
        return

    # Skip if no user
    if not user:
        return

    # Import here to avoid circular imports
    from accounts.tasks import sync_user_organizations

    # Trigger background task to sync organizations
    try:
        sync_user_organizations.enqueue(user.id, backend.name)
        logger.info(
            "Scheduled background organization sync for user %s from %s",
            user.username,
            backend.name,
            extra={"user_id": user.id, "provider": backend.name},
        )
    except Exception as e:
        logger.exception(
            "Error scheduling organization sync for user %s: %s",
            user.username,
            e,
            extra={"user_id": user.id, "provider": backend.name},
        )


def _fetch_github_orgs(access_token):
    """
    Fetch organizations from GitHub API.

    Args:
        access_token: GitHub OAuth access token

    Returns:
        List of organization dicts with standardized fields

    """
    import requests
    from django.utils.text import slugify

    from accounts.models import OrganizationMembership

    headers = {
        "Authorization": f"token {access_token}",
        "Accept": "application/vnd.github.v3+json",
    }

    orgs_data = []

    # Fetch user's organizations
    response = requests.get(
        "https://api.github.com/user/orgs", headers=headers, timeout=30
    )
    response.raise_for_status()
    orgs = response.json()

    for org in orgs:
        # Fetch detailed organization info
        org_response = requests.get(org["url"], headers=headers, timeout=30)
        org_response.raise_for_status()
        org_detail = org_response.json()

        # Get user's membership details to determine role
        membership_url = f"https://api.github.com/user/memberships/orgs/{org['login']}"
        membership_response = requests.get(membership_url, headers=headers, timeout=30)

        role = OrganizationMembership.Role.MEMBER
        if membership_response.status_code == 200:
            membership_data = membership_response.json()
            if membership_data.get("role") == "admin":
                role = OrganizationMembership.Role.ADMIN
            # Note: GitHub doesn't distinguish between owner and admin in the API
            # We could check org ownership separately if needed

        orgs_data.append(
            {
                "id": str(org_detail["id"]),
                "name": org_detail.get("name") or org_detail["login"],
                "slug": slugify(org_detail["login"]),
                "description": org_detail.get("description") or "",
                "avatar_url": org_detail.get("avatar_url", ""),
                "website": org_detail.get("blog", ""),
                "location": org_detail.get("location", ""),
                "login": org_detail["login"],
                "role": role,
            }
        )

    return orgs_data


def _fetch_gitee_orgs(access_token):
    """
    Fetch organizations from Gitee API.

    Args:
        access_token: Gitee OAuth access token

    Returns:
        List of organization dicts with standardized fields

    """
    import requests
    from django.utils.text import slugify

    from accounts.models import OrganizationMembership

    orgs_data = []

    # Fetch user's organizations
    response = requests.get(
        f"https://gitee.com/api/v5/user/orgs?access_token={access_token}", timeout=30
    )
    response.raise_for_status()
    orgs = response.json()

    for org in orgs:
        # Gitee returns role in the organization list
        role = OrganizationMembership.Role.MEMBER
        if org.get("role") == "admin":
            role = OrganizationMembership.Role.ADMIN
        elif org.get("role") == "owner":
            role = OrganizationMembership.Role.OWNER

        orgs_data.append(
            {
                "id": str(org["id"]),
                "name": org.get("name") or org["login"],
                "slug": slugify(org["login"]),
                "description": org.get("description") or "",
                "avatar_url": org.get("avatar_url", ""),
                "website": org.get("url", ""),
                "location": "",
                "login": org["login"],
                "role": role,
            }
        )

    return orgs_data


def _fetch_huggingface_orgs(access_token):
    """
    Fetch organizations from HuggingFace API.

    Args:
        access_token: HuggingFace OAuth access token

    Returns:
        List of organization dicts with standardized fields

    """
    import requests
    from django.utils.text import slugify

    from accounts.models import OrganizationMembership

    headers = {"Authorization": f"Bearer {access_token}"}

    orgs_data = []

    # Fetch user's organizations
    response = requests.get(
        "https://huggingface.co/api/organizations", headers=headers, timeout=30
    )
    response.raise_for_status()
    orgs = response.json()

    for org in orgs:
        # HuggingFace returns role in the organization list
        role = OrganizationMembership.Role.MEMBER
        if org.get("roleInOrganization") == "admin":
            role = OrganizationMembership.Role.ADMIN
        elif org.get("roleInOrganization") == "write":
            role = OrganizationMembership.Role.ADMIN  # Treat write as admin

        orgs_data.append(
            {
                "id": org["name"],  # HuggingFace uses name as ID
                "name": org.get("fullname") or org["name"],
                "slug": slugify(org["name"]),
                "description": "",
                "avatar_url": org.get("avatarUrl", ""),
                "website": "",
                "location": "",
                "login": org["name"],
                "role": role,
            }
        )

    return orgs_data
