"""Serialization helpers shared by accounts-related API routers."""

from __future__ import annotations


def _serialize_user_identity(user) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_active": user.is_active,
    }


def serialize_profile(profile) -> dict:
    """Serialize a user profile."""
    return {
        "bio": profile.bio,
        "birth_date": profile.birth_date.isoformat() if profile.birth_date else None,
        "github_url": profile.github_url,
        "homepage_url": profile.homepage_url,
        "blog_url": profile.blog_url,
        "twitter_url": profile.twitter_url,
        "linkedin_url": profile.linkedin_url,
        "company": profile.company,
        "location": profile.location,
    }


def serialize_work_experience(experience) -> dict:
    """Serialize a work experience row."""
    return {
        "id": experience.id,
        "company_name": experience.company_name,
        "title": experience.title,
        "start_date": experience.start_date.isoformat(),
        "end_date": experience.end_date.isoformat() if experience.end_date else None,
        "description": experience.description,
    }


def serialize_education(education) -> dict:
    """Serialize an education row."""
    return {
        "id": education.id,
        "institution_name": education.institution_name,
        "degree": education.degree,
        "field_of_study": education.field_of_study,
        "start_date": education.start_date.isoformat(),
        "end_date": education.end_date.isoformat() if education.end_date else None,
    }


def serialize_shipping_address(address) -> dict:
    """Serialize a shipping address."""
    return {
        "id": address.id,
        "receiver_name": address.receiver_name,
        "phone": address.phone,
        "province": address.province,
        "city": address.city,
        "district": address.district,
        "address": address.address,
        "is_default": address.is_default,
        "created_at": address.created_at.isoformat(),
        "updated_at": address.updated_at.isoformat(),
    }


def serialize_organization(organization, membership=None) -> dict:
    """Serialize an organization."""
    return {
        "id": organization.id,
        "name": organization.name,
        "slug": organization.slug,
        "description": organization.description,
        "website": organization.website,
        "location": organization.location,
        "avatar_url": organization.avatar.url if organization.avatar else None,
        "created_at": organization.created_at.isoformat(),
        "updated_at": organization.updated_at.isoformat(),
        "membership": serialize_membership(membership) if membership else None,
    }


def serialize_membership(membership) -> dict:
    """Serialize an organization membership."""
    return {
        "id": membership.id,
        "role": membership.role,
        "role_display": membership.get_role_display(),
        "joined_at": membership.joined_at.isoformat(),
        "user": _serialize_user_identity(membership.user),
        "is_admin_or_owner": membership.is_admin_or_owner(),
    }


def serialize_account_merge_log(log) -> dict:
    """Serialize an account merge execution log row."""
    return {
        "id": log.id,
        "table_name": log.table_name,
        "migrated_count": log.migrated_count,
        "skipped_count": log.skipped_count,
        "conflict_count": log.conflict_count,
        "notes": log.notes,
        "created_at": log.created_at.isoformat(),
    }


def serialize_account_merge_request(
    merge_request, *, include_logs: bool = False
) -> dict:
    """Serialize an account merge request."""
    payload = {
        "id": str(merge_request.id),
        "status": merge_request.status,
        "source_user": _serialize_user_identity(merge_request.source_user),
        "target_user": _serialize_user_identity(merge_request.target_user),
        "target_email_input": merge_request.target_email_input,
        "target_username_input": merge_request.target_username_input,
        "asset_snapshot": merge_request.asset_snapshot,
        "expires_at": merge_request.expires_at.isoformat(),
        "processed_at": (
            merge_request.processed_at.isoformat()
            if merge_request.processed_at
            else None
        ),
        "created_at": merge_request.created_at.isoformat(),
        "updated_at": merge_request.updated_at.isoformat(),
        "is_expired": merge_request.is_expired,
    }
    if include_logs:
        payload["logs"] = [
            serialize_account_merge_log(log) for log in merge_request.logs.all()
        ]
    return payload
