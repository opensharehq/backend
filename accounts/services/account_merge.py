"""Account merge execution service."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from social_django.models import UserSocialAuth

from accounts.models import (
    AccountMergeLog,
    AccountMergeRequest,
    OrganizationMembership,
    ShippingAddress,
    UserProfile,
)
from shop.models import Redemption

logger = logging.getLogger(__name__)
User = get_user_model()

ROLE_PRIORITY = {
    OrganizationMembership.Role.OWNER: 3,
    OrganizationMembership.Role.ADMIN: 2,
    OrganizationMembership.Role.MEMBER: 1,
}


class AccountMergeError(Exception):
    """Raised when merge cannot be performed."""


def _log(request: AccountMergeRequest, table: str, counts=None, notes: str = ""):
    """Persist a single merge log entry with aggregated counts."""
    counts = counts or {}
    AccountMergeLog.objects.create(
        request=request,
        table_name=table,
        migrated_count=counts.get("migrated", 0),
        skipped_count=counts.get("skipped", 0),
        conflict_count=counts.get("conflict", 0),
        notes=notes,
    )


def _copy_profile_fields(source_profile: UserProfile, target_profile: UserProfile):
    """Fill blank target profile fields using source values."""
    if not source_profile:
        return 0

    copied = 0
    updatable_fields: Iterable[str] = (
        "bio",
        "birth_date",
        "github_url",
        "homepage_url",
        "blog_url",
        "twitter_url",
        "linkedin_url",
        "company",
        "location",
    )
    for field in updatable_fields:
        target_value = getattr(target_profile, field)
        source_value = getattr(source_profile, field)
        if (target_value is None or target_value == "") and source_value:
            setattr(target_profile, field, source_value)
            copied += 1

    if copied:
        target_profile.save()
    return copied


def _migrate_social_accounts(merge_request, source, target):
    """Move social auth bindings while skipping duplicates."""
    target_social_keys = {
        (sa.provider, sa.uid)
        for sa in UserSocialAuth.objects.filter(user=target).select_related("user")
    }
    migrated = 0
    conflicts = 0
    for social in UserSocialAuth.objects.select_for_update().filter(user=source):
        key = (social.provider, social.uid)
        if key in target_social_keys:
            conflicts += 1
            continue
        social.user = target
        social.save(update_fields=["user"])
        migrated += 1
        target_social_keys.add(key)
    _log(
        merge_request,
        "social_auth",
        counts={"migrated": migrated, "conflict": conflicts},
    )


def _migrate_redemptions(merge_request, source, target):
    """Move shop redemptions."""
    redemptions_moved = Redemption.objects.filter(user_profile=source).update(
        user_profile=target
    )
    _log(merge_request, "redemptions", counts={"migrated": redemptions_moved})


def _migrate_shipping_addresses(merge_request, source, target):
    """Move shipping addresses with deduplication."""
    existing_addresses = {
        (
            addr.receiver_name,
            addr.phone,
            addr.province,
            addr.city,
            addr.district,
            addr.address,
        ): addr
        for addr in ShippingAddress.objects.select_for_update().filter(user=target)
    }
    migrated = 0
    skipped = 0
    for address in ShippingAddress.objects.select_for_update().filter(user=source):
        key = (
            address.receiver_name,
            address.phone,
            address.province,
            address.city,
            address.district,
            address.address,
        )
        if key in existing_addresses:
            destination = existing_addresses[key]
            Redemption.objects.filter(shipping_address=address).update(
                shipping_address=destination
            )
            skipped += 1
            address.delete()
            continue
        address.user = target
        address.save(update_fields=["user"])
        existing_addresses[key] = address
        migrated += 1
    _log(
        merge_request,
        "shipping_addresses",
        counts={"migrated": migrated, "skipped": skipped},
        notes="去重后保留目标账号地址优先",
    )


def _migrate_organization_memberships(merge_request, source, target):
    """Move org memberships, resolving conflicts by higher role."""
    target_memberships = {
        membership.organization_id: membership
        for membership in OrganizationMembership.objects.select_for_update().filter(
            user=target
        )
    }
    migrated = 0
    conflicts = 0
    for membership in OrganizationMembership.objects.select_for_update().filter(
        user=source
    ):
        existing = target_memberships.get(membership.organization_id)
        if existing:
            conflicts += 1
            existing_role_weight = ROLE_PRIORITY.get(existing.role, 0)
            incoming_role_weight = ROLE_PRIORITY.get(membership.role, 0)
            if incoming_role_weight > existing_role_weight:
                existing.role = membership.role
                existing.save(update_fields=["role", "updated_at"])
            membership.delete()
            continue
        membership.user = target
        membership.save(update_fields=["user"])
        target_memberships[membership.organization_id] = membership
        migrated += 1
    _log(
        merge_request,
        "organization_memberships",
        counts={"migrated": migrated, "conflict": conflicts},
        notes="若重复组织保留高权限",
    )


def _merge_profiles(merge_request, source, target):
    """Fill blank profile fields on target from source."""
    target_profile, _ = UserProfile.objects.get_or_create(user=target)
    try:
        source_profile = UserProfile.objects.get(user=source)
    except UserProfile.DoesNotExist:
        source_profile = None
    copied_fields = _copy_profile_fields(source_profile, target_profile)
    _log(
        merge_request,
        "profile",
        counts={"migrated": copied_fields},
        notes="仅填充目标空白字段，用户名/邮箱保留目标",
    )


def _deactivate_source(source, target):
    """Mark source inactive and link to target."""
    source.is_active = False
    source.merged_into = target
    source.save(update_fields=["is_active", "merged_into"])


@transaction.atomic
def perform_merge(request_obj: AccountMergeRequest) -> AccountMergeRequest:
    """Execute merge steps inside a single transaction."""
    merge_request = (
        AccountMergeRequest.objects.select_for_update()
        .select_related("source_user", "target_user")
        .get(pk=request_obj.pk)
    )

    if merge_request.status == AccountMergeRequest.Status.ACCEPTED:
        return merge_request

    now = timezone.now()
    if (
        merge_request.expires_at <= now
        and merge_request.status == AccountMergeRequest.Status.PENDING
    ):
        merge_request.status = AccountMergeRequest.Status.EXPIRED
        merge_request.processed_at = now
        merge_request.processed_by = merge_request.target_user
        merge_request.save(update_fields=["status", "processed_at", "processed_by"])
        return merge_request

    if merge_request.status != AccountMergeRequest.Status.PENDING:
        msg = "合并请求已被处理，无法再次执行"
        raise AccountMergeError(msg)

    source = (
        User.objects.select_for_update()
        .select_related("profile")
        .get(pk=merge_request.source_user_id)
    )
    target = (
        User.objects.select_for_update()
        .select_related("profile")
        .get(pk=merge_request.target_user_id)
    )

    if not source.is_active:
        msg = "源账号已停用，无法继续合并"
        raise AccountMergeError(msg)
    if not target.is_active:
        msg = "目标账号已停用，无法继续合并"
        raise AccountMergeError(msg)
    if target.is_staff or target.is_superuser:
        msg = "不允许合并到管理员账号"
        raise AccountMergeError(msg)

    _migrate_social_accounts(merge_request, source, target)
    _migrate_redemptions(merge_request, source, target)
    _migrate_shipping_addresses(merge_request, source, target)
    _migrate_organization_memberships(merge_request, source, target)
    _merge_profiles(merge_request, source, target)
    _deactivate_source(source, target)

    # finalize request
    merge_request.status = AccountMergeRequest.Status.ACCEPTED
    merge_request.processed_at = now
    merge_request.processed_by = target
    merge_request.save(update_fields=["status", "processed_at", "processed_by"])

    logger.info(
        "Account merge completed: %s -> %s, request=%s",
        source.pk,
        target.pk,
        merge_request.id,
    )

    return merge_request
