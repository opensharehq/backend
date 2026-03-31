# ruff: noqa: D101, EM101
"""Organization management endpoints for API v1."""

from __future__ import annotations

import re

from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from config.api_common import ApiError, ErrorResponseSchema
from points import services as points_services

from .api_serializers import serialize_membership, serialize_organization
from .api_v1 import jwt_bearer_auth
from .models import Organization, OrganizationMembership

router = Router(tags=["organizations"], auth=jwt_bearer_auth)

SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


class OrganizationCreateSchema(Schema):
    name: str
    slug: str
    description: str = ""
    website: str = ""
    location: str = ""


class OrganizationUpdateSchema(Schema):
    name: str | None = None
    slug: str | None = None
    description: str | None = None
    website: str | None = None
    location: str | None = None


class OrganizationMemberCreateSchema(Schema):
    username: str
    role: str = OrganizationMembership.Role.MEMBER


class OrganizationMemberUpdateSchema(Schema):
    role: str


def _validation_detail(field: str, message: str, code: str = "invalid") -> dict:
    return {field: [{"message": message, "code": code}]}


def _merge_validation_details(*details: dict) -> dict:
    merged: dict = {}
    for detail in details:
        for field, errors in detail.items():
            merged.setdefault(field, []).extend(errors)
    return merged


def _get_membership_or_error(
    user, organization: Organization
) -> OrganizationMembership:
    membership = (
        OrganizationMembership.objects.filter(
            user=user,
            organization=organization,
        )
        .select_related("user", "organization")
        .first()
    )
    if membership is None:
        raise ApiError(
            "forbidden",
            403,
            "You are not a member of this organization.",
        )
    return membership


def _get_admin_membership_or_error(
    user, organization: Organization
) -> OrganizationMembership:
    membership = _get_membership_or_error(user, organization)
    if not membership.is_admin_or_owner():
        raise ApiError(
            "forbidden",
            403,
            "You do not have permission to manage this organization.",
        )
    return membership


def _get_owner_membership_or_error(
    user, organization: Organization
) -> OrganizationMembership:
    membership = _get_membership_or_error(user, organization)
    if membership.role != OrganizationMembership.Role.OWNER:
        raise ApiError(
            "forbidden",
            403,
            "Only organization owners can perform this action.",
        )
    return membership


def _ensure_owner_role_management_allowed(
    actor_membership: OrganizationMembership,
    *,
    current_role: str | None = None,
    target_role: str | None = None,
) -> None:
    owner_role = OrganizationMembership.Role.OWNER
    if owner_role in {current_role, target_role}:
        if actor_membership.role != owner_role:
            raise ApiError(
                "forbidden",
                403,
                "Only organization owners can manage owner roles.",
            )


def _validate_role(role: str) -> None:
    valid_roles = {choice[0] for choice in OrganizationMembership.Role.choices}
    if role not in valid_roles:
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            _validation_detail("role", "The specified organization role is invalid."),
        )


def _validate_organization_payload(
    payload, organization: Organization | None = None
) -> dict:
    name = payload.name.strip()
    slug = payload.slug.strip()
    errors = []

    if not name:
        errors.append(_validation_detail("name", "The organization name is required."))

    if not slug:
        errors.append(_validation_detail("slug", "The organization slug is required."))
    elif not SLUG_PATTERN.match(slug):
        errors.append(
            _validation_detail(
                "slug",
                "The organization slug may only contain letters, numbers, hyphens, "
                "and underscores.",
            )
        )
    else:
        existing = Organization.objects.filter(slug=slug)
        if organization is not None:
            existing = existing.exclude(id=organization.id)
        if existing.exists():
            errors.append(
                _validation_detail("slug", "The organization slug is already in use.")
            )

    if errors:
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            _merge_validation_details(*errors),
        )

    return {
        "name": name,
        "slug": slug,
        "description": payload.description.strip(),
        "website": payload.website.strip(),
        "location": payload.location.strip(),
    }


def _get_organization_or_404(slug: str) -> Organization:
    return get_object_or_404(Organization, slug=slug)


def _get_member_or_404(
    organization: Organization, member_id: int
) -> OrganizationMembership:
    return get_object_or_404(
        OrganizationMembership.objects.select_related("user", "organization"),
        id=member_id,
        organization=organization,
    )


def _serialize_organization_summary(organization: Organization, membership) -> dict:
    payload = serialize_organization(organization, membership)
    payload["member_count"] = organization.memberships.count()
    return payload


@router.get("", response=dict)
def organization_list_endpoint(request):
    """List organizations the current user belongs to."""
    memberships = (
        OrganizationMembership.objects.filter(user=request.auth)
        .select_related("organization")
        .order_by("-joined_at")
    )
    return {
        "items": [
            _serialize_organization_summary(membership.organization, membership)
            for membership in memberships
        ]
    }


@router.post("", response={201: dict, 422: ErrorResponseSchema})
def organization_create_endpoint(request, payload: OrganizationCreateSchema):
    """Create a new organization and add the current user as owner."""
    validated = _validate_organization_payload(payload)
    with transaction.atomic():
        organization = Organization.objects.create(**validated)
        membership = OrganizationMembership.objects.create(
            user=request.auth,
            organization=organization,
            role=OrganizationMembership.Role.OWNER,
        )
    return 201, {
        **serialize_organization(organization, membership),
        "member_count": 1,
    }


@router.get(
    "/{slug}", response={200: dict, 403: ErrorResponseSchema, 404: ErrorResponseSchema}
)
def organization_detail_endpoint(request, slug: str):
    """Return organization details for a current member."""
    organization = _get_organization_or_404(slug)
    membership = _get_membership_or_error(request.auth, organization)
    balance = points_services.get_detailed_balance_or_zero(organization)
    return {
        "organization": serialize_organization(organization, membership),
        "membership": serialize_membership(membership),
        "balance": balance,
        "member_count": organization.memberships.count(),
        "is_admin": membership.is_admin_or_owner(),
    }


@router.patch(
    "/{slug}",
    response={
        200: dict,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
        422: ErrorResponseSchema,
    },
)
def organization_update_endpoint(request, slug: str, payload: OrganizationUpdateSchema):
    """Update organization settings."""
    organization = _get_organization_or_404(slug)
    _get_admin_membership_or_error(request.auth, organization)
    current_payload = OrganizationCreateSchema(
        name=payload.name if payload.name is not None else organization.name,
        slug=payload.slug if payload.slug is not None else organization.slug,
        description=(
            payload.description
            if payload.description is not None
            else organization.description
        ),
        website=payload.website
        if payload.website is not None
        else organization.website,
        location=payload.location
        if payload.location is not None
        else organization.location,
    )
    validated = _validate_organization_payload(current_payload, organization)
    for field, value in validated.items():
        setattr(organization, field, value)
    organization.save()
    membership = _get_membership_or_error(request.auth, organization)
    return {"organization": serialize_organization(organization, membership)}


@router.post(
    "/{slug}/avatar",
    response={
        200: dict,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
        422: ErrorResponseSchema,
    },
)
def organization_avatar_upload_endpoint(request, slug: str):
    """Upload or replace an organization avatar."""
    organization = _get_organization_or_404(slug)
    _get_admin_membership_or_error(request.auth, organization)
    avatar = request.FILES.get("avatar")
    if avatar is None:
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            _validation_detail("avatar", "An avatar file is required."),
        )

    if organization.avatar:
        organization.avatar.delete(save=False)
    organization.avatar = avatar
    organization.save(update_fields=["avatar", "updated_at"])
    membership = _get_membership_or_error(request.auth, organization)
    return {"organization": serialize_organization(organization, membership)}


@router.delete(
    "/{slug}/avatar",
    response={204: None, 403: ErrorResponseSchema, 404: ErrorResponseSchema},
)
def organization_avatar_delete_endpoint(request, slug: str):
    """Remove an organization avatar."""
    organization = _get_organization_or_404(slug)
    _get_admin_membership_or_error(request.auth, organization)
    if organization.avatar:
        organization.avatar.delete(save=False)
        organization.avatar = None
        organization.save(update_fields=["avatar", "updated_at"])
    return 204, None


@router.delete(
    "/{slug}",
    response={
        204: None,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
        422: ErrorResponseSchema,
    },
)
def organization_delete_endpoint(request, slug: str, confirm_slug: str):
    """Delete an organization after confirming its slug."""
    organization = _get_organization_or_404(slug)
    _get_owner_membership_or_error(request.auth, organization)
    if confirm_slug.strip() != organization.slug:
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            _validation_detail(
                "confirm_slug",
                "The confirmation slug does not match this organization.",
            ),
        )

    avatar = organization.avatar if organization.avatar else None
    with transaction.atomic():
        organization.delete()
        if avatar:
            transaction.on_commit(lambda f=avatar: f.delete(save=False))
    return 204, None


@router.get(
    "/{slug}/members",
    response={200: dict, 403: ErrorResponseSchema, 404: ErrorResponseSchema},
)
def organization_members_endpoint(request, slug: str):
    """List organization members."""
    organization = _get_organization_or_404(slug)
    _get_admin_membership_or_error(request.auth, organization)
    memberships = (
        OrganizationMembership.objects.filter(organization=organization)
        .select_related("user")
        .order_by("-role", "joined_at")
    )
    return {
        "items": [serialize_membership(membership) for membership in memberships],
        "owner_count": memberships.filter(
            role=OrganizationMembership.Role.OWNER
        ).count(),
    }


@router.post(
    "/{slug}/members",
    response={
        201: dict,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
        409: ErrorResponseSchema,
        422: ErrorResponseSchema,
    },
)
def organization_member_add_endpoint(
    request,
    slug: str,
    payload: OrganizationMemberCreateSchema,
):
    """Add a member to an organization by username."""
    organization = _get_organization_or_404(slug)
    actor_membership = _get_admin_membership_or_error(request.auth, organization)
    _validate_role(payload.role)
    _ensure_owner_role_management_allowed(
        actor_membership,
        target_role=payload.role,
    )

    UserModel = get_user_model()
    user_to_add = UserModel.objects.filter(username=payload.username.strip()).first()
    if user_to_add is None:
        raise ApiError("not_found", 404, "The specified user was not found.")

    if OrganizationMembership.objects.filter(
        user=user_to_add,
        organization=organization,
    ).exists():
        raise ApiError(
            "member_exists",
            409,
            "The specified user is already a member of this organization.",
        )

    membership = OrganizationMembership.objects.create(
        user=user_to_add,
        organization=organization,
        role=payload.role,
    )
    return 201, serialize_membership(membership)


@router.patch(
    "/{slug}/members/{member_id}",
    response={
        200: dict,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
        409: ErrorResponseSchema,
        422: ErrorResponseSchema,
    },
)
def organization_member_update_endpoint(
    request,
    slug: str,
    member_id: int,
    payload: OrganizationMemberUpdateSchema,
):
    """Update a member's organization role."""
    organization = _get_organization_or_404(slug)
    actor_membership = _get_admin_membership_or_error(request.auth, organization)
    _validate_role(payload.role)
    member = _get_member_or_404(organization, member_id)
    _ensure_owner_role_management_allowed(
        actor_membership,
        current_role=member.role,
        target_role=payload.role,
    )

    if (
        member.role == OrganizationMembership.Role.OWNER
        and payload.role != OrganizationMembership.Role.OWNER
    ):
        owner_count = OrganizationMembership.objects.filter(
            organization=organization,
            role=OrganizationMembership.Role.OWNER,
        ).count()
        if owner_count <= 1:
            raise ApiError(
                "last_owner",
                409,
                "The last organization owner cannot be demoted.",
            )

    member.role = payload.role
    member.save(update_fields=["role", "updated_at"])
    member.refresh_from_db()
    return serialize_membership(member)


@router.delete(
    "/{slug}/members/{member_id}",
    response={
        204: None,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
        409: ErrorResponseSchema,
    },
)
def organization_member_remove_endpoint(request, slug: str, member_id: int):
    """Remove a member from the organization."""
    organization = _get_organization_or_404(slug)
    actor_membership = _get_admin_membership_or_error(request.auth, organization)
    member = _get_member_or_404(organization, member_id)
    _ensure_owner_role_management_allowed(
        actor_membership,
        current_role=member.role,
    )

    if member.role == OrganizationMembership.Role.OWNER:
        owner_count = OrganizationMembership.objects.filter(
            organization=organization,
            role=OrganizationMembership.Role.OWNER,
        ).count()
        if owner_count <= 1:
            raise ApiError(
                "last_owner",
                409,
                "The last organization owner cannot be removed.",
            )

    member.delete()
    return 204, None
