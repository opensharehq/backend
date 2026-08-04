"""
Profile completion reward service.

Handles checking profile completeness, calculating reward points based on
OpenRank contribution history, and granting one-time profile completion rewards.
"""

import logging
from datetime import date

import requests
from django.core.cache import cache

from chdb.services import query_user_yearly_openrank
from points.models import PointSource, PointWallet
from points.services import grant_points

logger = logging.getLogger(__name__)

# Cache keys and TTL
OPENRANK_CACHE_PREFIX = "profile_reward:openrank"
BASELINE_CACHE_KEY = "profile_reward:baseline"
CACHE_TTL = 86400  # 24 hours

# CDN URL for talent baseline data
TALENT_BASELINE_URL = "https://oss.open-digger.cn/talent_baseline.json"

# Tier-to-points mapping
TIER_POINTS = {
    "SSS": 200,
    "SS": 100,
    "S": 60,
    "A": 40,
    "B": 20,
    "C": 10,
    "D": 0,
}

# Ordered tier labels (highest to lowest)
TIER_LABELS = ["SSS", "SS", "S", "A", "B", "C", "D"]


def is_profile_complete(user) -> tuple[bool, list[str]]:
    """
    Check whether a user's profile information is complete.

    Args:
        user: User instance with related profile, work_experiences, educations.

    Returns:
        Tuple of (is_complete, missing_fields) where missing_fields contains
        keys like 'location', 'birth_date', 'work_experience', 'education'.

    """
    missing = []
    profile = user.profile

    # Location check
    if not profile.location_country_id:
        missing.append("location")

    # Birth date check
    if not profile.birth_date:
        missing.append("birth_date")

    # Work experience check (exempt if age < 25)
    work_exempt = False
    if profile.birth_date:
        today = date.today()
        age = (
            today.year
            - profile.birth_date.year
            - (
                (today.month, today.day)
                < (profile.birth_date.month, profile.birth_date.day)
            )
        )
        if age < 25:
            work_exempt = True

    if not work_exempt and not profile.work_experiences.exists():
        missing.append("work_experience")

    # Education check
    if not profile.educations.exists():
        missing.append("education")

    return (len(missing) == 0, missing)


def has_claimed_reward(user) -> bool:
    """
    Check whether the user has already claimed the profile completion reward.

    Prioritizes the fast boolean field on the profile, then falls back to
    querying PointSource records.

    Args:
        user: User instance.

    Returns:
        True if reward has been claimed, False otherwise.

    """
    # Fast path: check the denormalized flag on the profile
    if user.profile.profile_completion_rewarded:
        return True

    # Fallback: query PointSource by reference_id
    reference_id = f"profile_completion_reward:{user.id}"
    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(user)
    wallet = PointWallet.objects.filter(content_type=ct, object_id=user.pk).first()
    if wallet is None:
        return False

    return PointSource.objects.filter(wallet=wallet, reference_id=reference_id).exists()


def _get_user_platform_ids(user) -> list[tuple[str, str]]:
    """
    Retrieve the user's bound social platform accounts.

    Returns:
        List of (platform, uid) tuples from UserSocialAuth.

    """
    from social_django.models import UserSocialAuth

    social_auths = UserSocialAuth.objects.filter(user=user)
    platform_ids = []
    for auth in social_auths:
        provider = auth.provider  # e.g. 'github', 'gitee'
        uid = str(auth.uid)
        platform_ids.append((provider, uid))
    return platform_ids


def _fetch_baseline_tiers() -> dict | None:
    """
    Fetch openrankTiers from CDN talent_baseline.json with caching.

    Returns:
        Dict of year (str) -> list of thresholds, or None on failure.

    """
    cached = cache.get(BASELINE_CACHE_KEY)
    if cached is not None:
        return cached

    try:
        resp = requests.get(TALENT_BASELINE_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        tiers = data.get("openrankTiers")
        if tiers:
            cache.set(BASELINE_CACHE_KEY, tiers, CACHE_TTL)
        return tiers
    except Exception as e:
        logger.error("Failed to fetch talent_baseline.json: %s", e)
        return None


def _determine_tier(openrank_value: float, thresholds: list) -> str:
    """
    Determine the tier label based on openrank value and thresholds.

    Thresholds are ordered high to low: [SSS, SS, S, A, B, C] and may
    contain a trailing 0 entry for the D tier floor, which is ignored.
    Values >= threshold[0] → SSS, >= threshold[1] → SS, etc.
    Below all thresholds → D.

    """
    tier_labels_without_d = TIER_LABELS[:-1]  # SSS, SS, S, A, B, C
    # Zip guards against threshold lists longer than the label list
    # (e.g. CDN data includes a trailing 0 for the D tier).
    for label, threshold in zip(tier_labels_without_d, thresholds, strict=False):
        if openrank_value >= threshold:
            return label
    return "D"


def calculate_reward_points(user) -> int:
    """
    Calculate the profile completion reward points for a user.

    Steps:
        1. Get user's bound platform accounts.
        2. Query ClickHouse for yearly OpenRank contributions.
        3. Fetch baseline tier thresholds from CDN.
        4. Determine the highest tier from historical max yearly contribution.
        5. Map tier to reward points.

    Args:
        user: User instance.

    Returns:
        Integer reward points (0 if no contribution data or tier is D).

    """
    # Check cache for user openrank data
    openrank_cache_key = f"{OPENRANK_CACHE_PREFIX}:{user.id}"
    cached_points = cache.get(openrank_cache_key)
    if cached_points is not None:
        return cached_points

    # Step 1: Get platform accounts
    platform_ids = _get_user_platform_ids(user)
    if not platform_ids:
        cache.set(openrank_cache_key, 0, CACHE_TTL)
        return 0

    # Step 2: Query yearly openrank from ClickHouse
    yearly_data = query_user_yearly_openrank(platform_ids)
    if not yearly_data:
        cache.set(openrank_cache_key, 0, CACHE_TTL)
        return 0

    # Step 3: Fetch baseline tiers
    tiers = _fetch_baseline_tiers()
    if not tiers:
        cache.set(openrank_cache_key, 0, CACHE_TTL)
        return 0

    # Step 4: Find highest tier across all years
    best_tier = "D"
    best_tier_index = TIER_LABELS.index("D")

    for entry in yearly_data:
        year = str(entry["year"])
        yearly_openrank = entry["yearly_openrank"]

        # Use the thresholds for this year; fall back to the closest available year
        year_thresholds = tiers.get(year)
        if year_thresholds is None:
            # Try closest available year
            available_years = sorted(tiers.keys())
            if not available_years:
                continue
            # Pick the closest year
            closest_year = min(available_years, key=lambda y: abs(int(y) - int(year)))
            year_thresholds = tiers.get(closest_year)
            if year_thresholds is None:
                continue

        tier = _determine_tier(yearly_openrank, year_thresholds)
        tier_index = TIER_LABELS.index(tier)
        if tier_index < best_tier_index:
            best_tier = tier
            best_tier_index = tier_index

    # Step 5: Map tier to points
    points = TIER_POINTS.get(best_tier, 0)
    cache.set(openrank_cache_key, points, CACHE_TTL)
    return points


def grant_profile_completion_reward(user) -> dict | None:
    """
    Attempt to grant the profile completion reward to a user.

    Checks profile completeness, prior claim status, and calculates points.
    If eligible and points > 0, grants the reward.

    Args:
        user: User instance.

    Returns:
        Dict with 'rewarded' and 'points' keys on success, or None if
        ineligible or no points to award.

    """
    # Step 1: Check profile completeness
    complete, _missing = is_profile_complete(user)
    if not complete:
        return None

    # Step 2: Check if already claimed
    if has_claimed_reward(user):
        return None

    # Step 3: Calculate reward points
    points = calculate_reward_points(user)
    if points <= 0:
        return None

    # Step 4: Grant points
    grant_points(
        owner=user,
        amount=points,
        point_type="gift",
        reason="Profile completion reward",
        reference_id=f"profile_completion_reward:{user.id}",
    )

    # Step 5: Mark profile as rewarded
    user.profile.profile_completion_rewarded = True
    user.profile.save(update_fields=["profile_completion_rewarded"])

    return {"rewarded": True, "points": points}


def get_profile_completion_reward_info(user) -> dict:
    """
    Get the current profile completion reward status for a user.

    Intended for API consumption to show users their eligibility and
    potential reward amount.

    Args:
        user: User instance.

    Returns:
        Dict with 'eligible', 'reward_points', and 'missing_fields' keys.

    """
    # Already claimed
    if has_claimed_reward(user):
        return {"eligible": False, "reward_points": 0, "missing_fields": []}

    complete, missing = is_profile_complete(user)
    reward_points = calculate_reward_points(user)

    return {
        "eligible": complete and reward_points > 0,
        "reward_points": reward_points,
        "missing_fields": missing,
    }
