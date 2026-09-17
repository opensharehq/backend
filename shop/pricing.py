"""Developer-tier pricing for shop items."""

import logging
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from accounts.services.profile_completion_reward import calculate_reward_points

from .models import DeveloperTierDiscountConfig

logger = logging.getLogger(__name__)

FULL_PRICE_MULTIPLIER = Decimal("1.00")


@dataclass(frozen=True, slots=True)
class UserTierDiscount:
    """Resolved discount entitlement for one user."""

    tier: str | None = None
    tier_year: int | None = None
    multiplier: Decimal = FULL_PRICE_MULTIPLIER

    @property
    def is_discounted(self) -> bool:
        """Return whether this entitlement reduces the item price."""
        return self.tier is not None and self.multiplier < FULL_PRICE_MULTIPLIER


@dataclass(frozen=True, slots=True)
class ShopItemPricing:
    """Original and effective price plus the entitlement used to derive it."""

    original_cost: int
    cost: int
    tier: str | None
    tier_year: int | None
    multiplier: Decimal


def resolve_user_tier_discount(user) -> UserTierDiscount:
    """Resolve the user's highest historical tier and configured multiplier."""
    try:
        reward = calculate_reward_points(user)
    except Exception:
        logger.exception(
            "Unable to resolve developer tier discount for user_id=%s",
            getattr(user, "id", None),
        )
        return UserTierDiscount()

    tier = reward.get("highest_level")
    tier_year = reward.get("highest_level_year")
    if tier not in DeveloperTierDiscountConfig.MULTIPLIER_FIELDS:
        return UserTierDiscount()

    config = DeveloperTierDiscountConfig.objects.filter(
        pk=DeveloperTierDiscountConfig.SINGLETON_PK
    ).first()
    multiplier = (
        config.multiplier_for_tier(tier)
        if config is not None
        else DeveloperTierDiscountConfig.DEFAULT_MULTIPLIERS[tier]
    )
    return UserTierDiscount(
        tier=tier,
        tier_year=int(tier_year) if tier_year is not None else None,
        multiplier=Decimal(multiplier),
    )


def calculate_shop_item_pricing(
    original_cost: int,
    discount: UserTierDiscount,
) -> ShopItemPricing:
    """Apply a multiplier to an integer point cost, always rounding upward."""
    effective_cost = int(
        (Decimal(original_cost) * discount.multiplier).to_integral_value(
            rounding=ROUND_CEILING
        )
    )
    return ShopItemPricing(
        original_cost=original_cost,
        cost=effective_cost,
        tier=discount.tier,
        tier_year=discount.tier_year,
        multiplier=discount.multiplier,
    )


def full_price(original_cost: int) -> ShopItemPricing:
    """Return a full-price snapshot for contexts without user-specific pricing."""
    return calculate_shop_item_pricing(original_cost, UserTierDiscount())
