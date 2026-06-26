# ruff: noqa: PLR0913
"""Talent outreach service layer."""

import logging
import math
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.db import OperationalError, close_old_connections, transaction
from django.db.models import F, QuerySet
from django.utils import timezone
from social_django.models import UserSocialAuth

from chdb.services import query_developers_for_outreach
from messages.models import Message, UserMessage
from messages.services import send_message
from points.models import PointType
from points.services import grant_points, spend_points

from .models import OutreachCampaign, OutreachDraft, OutreachRecipient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Draft management
# ---------------------------------------------------------------------------


def create_draft(
    author, title: str, content: str, title_zh: str = "", content_zh: str = ""
) -> OutreachDraft:
    """Create a new outreach draft."""
    return OutreachDraft.objects.create(
        author=author,
        title=title,
        content=content,
        title_zh=title_zh,
        content_zh=content_zh,
    )


def update_draft(
    draft_id: int,
    author,
    title: str,
    content: str,
    title_zh: str = "",
    content_zh: str = "",
) -> OutreachDraft:
    """Update an existing outreach draft."""
    draft = OutreachDraft.objects.get(id=draft_id, author=author)
    draft.title = title
    draft.content = content
    draft.title_zh = title_zh
    draft.content_zh = content_zh
    draft.save(
        update_fields=["title", "content", "title_zh", "content_zh", "updated_at"]
    )
    return draft


def delete_draft(draft_id: int, author) -> None:
    """Delete a draft belonging to the author."""
    OutreachDraft.objects.filter(id=draft_id, author=author).delete()


def list_drafts(author) -> QuerySet:
    """List all drafts for the given author."""
    return OutreachDraft.objects.filter(author=author)


def get_draft(draft_id: int, author) -> OutreachDraft:
    """Get a single draft belonging to the author."""
    return OutreachDraft.objects.get(id=draft_id, author=author)


# ---------------------------------------------------------------------------
# Preview recipients
# ---------------------------------------------------------------------------


def _match_registered_users(developers: list[dict]) -> list[dict]:
    """
    Cross-reference ClickHouse developers with locally registered users.

    Matches are based on (provider, uid) in social_django's UserSocialAuth table.
    Returns only developers who have a registered account.
    """
    if not developers:
        return []

    # Build lookup: (provider_lower, actor_id) -> developer dict
    lookup = {}
    for dev in developers:
        platform = (dev.get("platform") or "").lower()
        actor_id = str(dev.get("actor_id", ""))
        lookup[(platform, actor_id)] = dev

    # Query UserSocialAuth for matching (provider, uid) pairs
    # social_django stores provider as e.g. "github", uid as string
    platforms = list({k[0] for k in lookup})
    actor_ids = list({k[1] for k in lookup})

    social_auths = UserSocialAuth.objects.filter(
        provider__in=platforms,
        uid__in=actor_ids,
    ).select_related("user")

    matched = []
    seen_users = set()
    for sa in social_auths:
        key = (sa.provider.lower(), str(sa.uid))
        dev = lookup.get(key)
        if dev and sa.user_id not in seen_users:
            seen_users.add(sa.user_id)
            matched.append(
                {
                    "user_id": sa.user_id,
                    "username": sa.user.username,
                    "platform": dev["platform"],
                    "actor_id": dev["actor_id"],
                    "openrank_score": dev.get("openrank_score", 0.0),
                }
            )
    return matched


def preview_recipients(
    tag_ids: list[str],
    languages: list[str] | None = None,
    countries: list[str] | None = None,
    regions: list[str] | None = None,
    top_n: int | None = None,
) -> dict:
    """
    Preview reachable registered users matching the given criteria.

    Returns cost estimates and developer list.
    """
    developers = query_developers_for_outreach(
        tag_ids=tag_ids,
        languages=languages,
        countries=countries,
        regions=regions,
        top_n=top_n,
    )

    matched = _match_registered_users(developers)
    registered_count = len(matched)
    cost_per_user = settings.OUTREACH_COST_PER_USER
    reward_ratio = settings.OUTREACH_REWARD_RATIO

    estimated_cost = registered_count * cost_per_user
    reward_pool = int(estimated_cost * reward_ratio)

    return {
        "reachable_users": registered_count,
        "estimated_cost": estimated_cost,
        "reward_pool": reward_pool,
        "reward_ratio": reward_ratio,
        "developers": matched,
    }


# ---------------------------------------------------------------------------
# Largest remainder method for reward allocation
# ---------------------------------------------------------------------------


def _largest_remainder_allocation(scores: list[float], total: int) -> list[int]:
    """
    Allocate integer amounts proportional to scores, summing exactly to total.

    Uses the largest remainder method (Hamilton's method).
    """
    if not scores or total <= 0:
        return [0] * len(scores)

    total_score = sum(scores)
    if total_score <= 0:
        # Equal distribution if all scores are zero
        base = total // len(scores)
        remainder = total - base * len(scores)
        return [base + (1 if i < remainder else 0) for i in range(len(scores))]

    # Compute exact quotas
    quotas = [(s / total_score) * total for s in scores]
    # Floor values
    floors = [math.floor(q) for q in quotas]
    # Remainders
    remainders = [q - f for q, f in zip(quotas, floors, strict=True)]

    # Distribute remaining units to largest remainders
    remaining = total - sum(floors)
    # Get indices sorted by remainder descending
    indices = sorted(range(len(remainders)), key=lambda i: remainders[i], reverse=True)
    for i in range(remaining):
        floors[indices[i]] += 1

    return floors


# ---------------------------------------------------------------------------
# Send outreach
# ---------------------------------------------------------------------------


def send_outreach(
    draft_id: int,
    author,
    tag_ids: list[str],
    tag_names: list[str],
    languages: list[str] | None,
    countries: list[str] | None,
    regions: list[str] | None,
    top_n: int | None,
    point_type: str,
) -> OutreachCampaign:
    """
    Execute the outreach campaign.

    Synchronous part: validate, deduct points, create campaign.
    Async part: send messages in background thread.
    """
    # 1. Validate draft
    draft = OutreachDraft.objects.get(id=draft_id, author=author)

    # 2. Query developers (reuse preview logic)
    preview = preview_recipients(
        tag_ids=tag_ids,
        languages=languages,
        countries=countries,
        regions=regions,
        top_n=top_n,
    )

    developers = preview["developers"]
    if not developers:
        msg = "No reachable registered users found for the given criteria."
        raise ValueError(msg)

    # 3. Validate point_type
    if point_type not in (PointType.CASH, PointType.GIFT):
        msg = "point_type must be 'cash' or 'gift'."
        raise ValueError(msg)

    # 4. Calculate costs
    cost_per_user = settings.OUTREACH_COST_PER_USER
    reward_ratio = settings.OUTREACH_REWARD_RATIO
    reward_expiry_days = settings.OUTREACH_REWARD_EXPIRY_DAYS
    total_cost = len(developers) * cost_per_user
    reward_pool = int(total_cost * reward_ratio)

    # 5. Create campaign record first to get its ID for reference_id
    campaign = OutreachCampaign.objects.create(
        author=author,
        title=draft.title,
        content=draft.content,
        title_zh=draft.title_zh,
        content_zh=draft.content_zh,
        tag_ids=tag_ids,
        tag_names=tag_names,
        languages=languages or [],
        countries=countries or [],
        regions=regions or [],
        top_n=top_n,
        point_type=point_type,
        cost_per_user=cost_per_user,
        total_cost=total_cost,
        reward_ratio=reward_ratio,
        reward_pool=reward_pool,
        reward_expiry_days=reward_expiry_days,
        total_recipients=len(developers),
        status=OutreachCampaign.Status.SENDING,
    )

    reference_id = f"outreach_{campaign.id}"
    campaign.reference_id = reference_id
    campaign.save(update_fields=["reference_id"])

    # 6. Deduct points
    tag_is_null = point_type == PointType.GIFT
    try:
        spend_points(
            owner=author,
            amount=total_cost,
            point_type=point_type,
            description=f"Talent outreach: {draft.title}",
            tag_is_null=tag_is_null,
            reference_id=reference_id,
        )
    except Exception:
        campaign.status = OutreachCampaign.Status.FAILED
        campaign.save(update_fields=["status"])
        raise

    # 7. Calculate reward_amount for each user using largest remainder method
    scores = [d["openrank_score"] for d in developers]
    reward_amounts = _largest_remainder_allocation(scores, reward_pool)

    # 8. Pre-fetch recipient users in the main thread (avoids transaction isolation
    #    issues in the background thread where the test DB may not be visible).
    from accounts.models import User

    user_ids = [d["user_id"] for d in developers]
    recipient_users = list(User.objects.filter(id__in=user_ids))
    user_map = {u.id: u for u in recipient_users}

    # 9. Delete draft
    draft.delete()

    # 10. Send messages asynchronously (or synchronously in test environment)
    # Run synchronously in test environment to avoid SQLite/transaction issues
    if settings.TESTING:
        _send_outreach_async(
            campaign, developers, reward_amounts, author, recipient_users, user_map
        )
    else:
        thread = threading.Thread(
            target=_send_outreach_async,
            args=(
                campaign,
                developers,
                reward_amounts,
                author,
                recipient_users,
                user_map,
            ),
            daemon=True,
        )
        thread.start()

    return campaign


def _send_outreach_async(
    campaign: OutreachCampaign,
    developers: list[dict],
    reward_amounts: list[int],
    author,
    recipient_users: list,
    user_map: dict,
) -> None:
    """Background thread: send messages and create recipient records."""
    MAX_RETRIES = 3
    RETRY_DELAY = 0.5  # seconds

    try:
        close_old_connections()

        # Defensive check: abort early if no recipients resolved
        if not recipient_users:
            logger.warning(
                "No recipients for campaign %s, marking as failed", campaign.id
            )
            campaign.status = OutreachCampaign.Status.FAILED
            campaign.save(update_fields=["status"])
            return

        user_ids = [d["user_id"] for d in developers]

        # Retry wrapper for SQLite "database table is locked" errors
        for attempt in range(MAX_RETRIES):
            try:
                # Send message
                message = send_message(
                    title=campaign.title,
                    content=campaign.content,
                    message_type=Message.MessageType.OUTREACH,
                    sender=author,
                    recipients=recipient_users,
                )

                # Link campaign to message
                campaign.message = message
                campaign.save(update_fields=["message"])

                # Get created UserMessage records
                user_messages = UserMessage.objects.filter(
                    message=message, user_id__in=user_ids
                )
                um_map = {um.user_id: um for um in user_messages}

                # Bulk create OutreachRecipient records
                recipients_to_create = []
                for dev, reward_amount in zip(developers, reward_amounts, strict=True):
                    user_id = dev["user_id"]
                    user_obj = user_map.get(user_id)
                    um = um_map.get(user_id)
                    if user_obj:
                        recipients_to_create.append(
                            OutreachRecipient(
                                campaign=campaign,
                                user=user_obj,
                                user_message=um,
                                reward_amount=reward_amount,
                                openrank_score=dev.get("openrank_score", 0.0),
                            )
                        )

                OutreachRecipient.objects.bulk_create(recipients_to_create)

                # Update campaign status
                campaign.status = OutreachCampaign.Status.COMPLETED
                campaign.delivered_count = len(recipients_to_create)
                campaign.completed_at = timezone.now()
                campaign.save(
                    update_fields=["status", "delivered_count", "completed_at"]
                )

                logger.info(
                    "Outreach campaign %d completed: %d messages delivered",
                    campaign.id,
                    len(recipients_to_create),
                )
                break

            except OperationalError as e:
                if "locked" in str(e) and attempt < MAX_RETRIES - 1:
                    logger.warning(
                        "SQLite locked on attempt %d for campaign %d, retrying...",
                        attempt + 1,
                        campaign.id,
                    )
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    close_old_connections()
                else:
                    raise

    except Exception:
        logger.exception("Outreach campaign %d failed", campaign.id)
        campaign.status = OutreachCampaign.Status.FAILED
        campaign.save(update_fields=["status"])
    finally:
        close_old_connections()


# ---------------------------------------------------------------------------
# Reading reward
# ---------------------------------------------------------------------------


def claim_reading_reward(user, user_message_id: int) -> dict | None:
    """
    Claim reading reward when a user marks an outreach message as read.

    Returns reward info dict or None if not applicable.
    """
    try:
        recipient = OutreachRecipient.objects.select_related("campaign").get(
            user_message_id=user_message_id, user=user
        )
    except OutreachRecipient.DoesNotExist:
        return None

    # Already rewarded or expired
    if recipient.is_rewarded or recipient.reward_expired:
        return None

    # Check expiry
    campaign = recipient.campaign
    expiry_date = campaign.created_at + timedelta(days=campaign.reward_expiry_days)
    if timezone.now() > expiry_date:
        recipient.reward_expired = True
        recipient.save(update_fields=["reward_expired"])
        return None

    # Zero reward amount means no reward to grant
    if recipient.reward_amount <= 0:
        return None

    # Atomically claim the reward by conditionally updating is_rewarded.
    # Only one concurrent request can succeed because the UPDATE filters on
    # is_rewarded=False; if another request already flipped it, updated==0.
    now = timezone.now()
    with transaction.atomic():
        updated = OutreachRecipient.objects.filter(
            id=recipient.id, is_rewarded=False
        ).update(is_rewarded=True, rewarded_at=now)

        if not updated:
            # Another request already claimed the reward
            return None

        # Grant points inside the transaction so it rolls back on failure
        grant_points(
            owner=user,
            amount=recipient.reward_amount,
            point_type=campaign.point_type,
            reason=f"Outreach reading reward: {campaign.title}",
            reference_id=f"outreach_reward_{campaign.id}",
        )

        # Update campaign counters atomically
        OutreachCampaign.objects.filter(id=campaign.id).update(
            read_count=F("read_count") + 1,
            rewarded_count=F("rewarded_count") + 1,
        )

    return {
        "reward_amount": recipient.reward_amount,
        "point_type": campaign.point_type,
    }


# ---------------------------------------------------------------------------
# History queries
# ---------------------------------------------------------------------------


def list_campaigns(author) -> QuerySet:
    """List all campaigns for the given author."""
    return OutreachCampaign.objects.filter(author=author)


def get_campaign_detail(campaign_id: int, author) -> dict:
    """Get campaign with live stats."""
    campaign = OutreachCampaign.objects.get(id=campaign_id, author=author)

    recipients_qs = campaign.recipient_records.all()
    delivered_count = recipients_qs.count()
    rewarded_count = recipients_qs.filter(is_rewarded=True).count()
    read_count = campaign.read_count

    return {
        "id": campaign.id,
        "title": campaign.title,
        "content": campaign.content,
        "title_zh": campaign.title_zh,
        "content_zh": campaign.content_zh,
        "tag_ids": campaign.tag_ids,
        "tag_names": campaign.tag_names,
        "languages": campaign.languages,
        "countries": campaign.countries,
        "regions": campaign.regions,
        "top_n": campaign.top_n,
        "point_type": campaign.point_type,
        "cost_per_user": campaign.cost_per_user,
        "total_cost": campaign.total_cost,
        "reward_ratio": campaign.reward_ratio,
        "reward_pool": campaign.reward_pool,
        "reward_expiry_days": campaign.reward_expiry_days,
        "total_recipients": campaign.total_recipients,
        "delivered_count": delivered_count,
        "read_count": read_count,
        "rewarded_count": rewarded_count,
        "status": campaign.status,
        "created_at": campaign.created_at.isoformat(),
        "completed_at": campaign.completed_at.isoformat()
        if campaign.completed_at
        else None,
    }
