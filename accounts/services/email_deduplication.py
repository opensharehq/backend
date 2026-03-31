"""Duplicate-email planning and execution helpers."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from django.db import transaction

from accounts.email_addresses import (
    build_merged_placeholder_email,
    normalize_email_address,
)

from .account_merge import AccountMergeError, merge_users


def _user_model():
    """Return the configured user model."""
    from django.contrib.auth import get_user_model

    return get_user_model()


@dataclass(slots=True)
class EmailDedupeAction:
    """A single source-account cleanup action inside a duplicate-email group."""

    source: Any
    primary: Any
    archive_only: bool


@dataclass(slots=True)
class EmailDedupePlan:
    """Execution plan for a normalized duplicate-email group."""

    normalized_email: str
    primary: Any
    actions: list[EmailDedupeAction]
    blocking_reason: str | None = None

    @property
    def is_blocked(self) -> bool:
        """Return whether this plan requires manual intervention."""
        return self.blocking_reason is not None


def _primary_sort_key(user: Any) -> tuple[int, int, int, int]:
    """Pick the preferred primary account for a duplicate-email group."""
    return (
        0 if user.merged_into_id is None else 1,
        0 if user.is_active else 1,
        0 if user.has_usable_password() else 1,
        user.pk,
    )


def _blocking_reason(users: list[Any]) -> str | None:
    """Return the first reason a duplicate-email group should not auto-merge."""
    if any(user.is_staff or user.is_superuser for user in users):
        return "group contains an admin account"

    user_ids = {user.pk for user in users}
    if not any(user.merged_into_id is None for user in users):
        return "group has no unmerged primary candidate"

    for user in users:
        if user.merged_into_id and user.merged_into_id not in user_ids:
            return "group contains a merge chain pointing outside the duplicate set"

    return None


def _build_group_plan(normalized_email: str, users: list[Any]) -> EmailDedupePlan:
    """Build an execution plan for one duplicate-email group."""
    ordered_users = sorted(users, key=_primary_sort_key)
    primary = ordered_users[0]
    blocking_reason = _blocking_reason(ordered_users)
    actions = [
        EmailDedupeAction(
            source=user,
            primary=primary,
            archive_only=user.merged_into_id == primary.pk and not user.is_active,
        )
        for user in ordered_users[1:]
    ]
    return EmailDedupePlan(
        normalized_email=normalized_email,
        primary=primary,
        actions=actions,
        blocking_reason=blocking_reason,
    )


def build_duplicate_email_plans() -> list[EmailDedupePlan]:
    """Return plans for every duplicate non-empty normalized email group."""
    groups: dict[str, list[Any]] = defaultdict(list)
    users = (
        _user_model()
        .objects.exclude(email="")
        .select_related("merged_into")
        .order_by("pk")
    )
    for user in users:
        normalized_email = normalize_email_address(user.email)
        if normalized_email:
            groups[normalized_email].append(user)

    return [
        _build_group_plan(normalized_email, users)
        for normalized_email, users in sorted(groups.items())
        if len(users) > 1
    ]


def _archive_source_email(source: Any) -> None:
    """Rewrite a merged source account email to a unique audit-friendly value."""
    source.email = build_merged_placeholder_email(source.pk)
    source.save(update_fields=["email"])


@transaction.atomic
def apply_duplicate_email_plans(plans: list[EmailDedupePlan]) -> None:
    """Apply all duplicate-email plans inside a single transaction."""
    blocked = [plan for plan in plans if plan.is_blocked]
    if blocked:
        message = "Blocked duplicate-email groups must be resolved first"
        raise AccountMergeError(message)

    UserModel = _user_model()
    for plan in plans:
        primary = UserModel.objects.select_for_update().get(pk=plan.primary.pk)
        for action in plan.actions:
            source = UserModel.objects.select_for_update().get(pk=action.source.pk)
            if action.archive_only:
                _archive_source_email(source)
                continue

            merge_users(source, primary, allow_inactive_source=True)
            source.refresh_from_db(fields=["email"])
            _archive_source_email(source)
