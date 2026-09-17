"""Tests for developer-tier shop pricing."""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from shop.models import DeveloperTierDiscountConfig
from shop.pricing import calculate_shop_item_pricing, resolve_user_tier_discount


class DeveloperTierPricingTests(TestCase):
    """Validate tier resolution, configuration, and upward rounding."""

    def setUp(self):
        """Create a user and restore the singleton defaults."""
        self.user = get_user_model().objects.create_user(username="discount-user")
        self.config, _ = DeveloperTierDiscountConfig.objects.update_or_create(
            pk=DeveloperTierDiscountConfig.SINGLETON_PK,
            defaults={
                "sss_multiplier": Decimal("0.80"),
                "ss_multiplier": Decimal("0.85"),
                "s_multiplier": Decimal("0.90"),
                "a_multiplier": Decimal("0.95"),
                "b_multiplier": Decimal("0.95"),
            },
        )

    @patch("shop.pricing.calculate_reward_points")
    def test_sss_price_is_rounded_up(self, mock_calculate_reward_points):
        """A fractional discounted point price always rounds toward positive infinity."""
        mock_calculate_reward_points.return_value = {
            "highest_level": "SSS",
            "highest_level_year": 2025,
            "points": 200,
        }

        discount = resolve_user_tier_discount(self.user)
        pricing = calculate_shop_item_pricing(101, discount)

        self.assertEqual(pricing.original_cost, 101)
        self.assertEqual(pricing.cost, 81)
        self.assertEqual(pricing.tier, "SSS")
        self.assertEqual(pricing.tier_year, 2025)
        self.assertEqual(pricing.multiplier, Decimal("0.80"))

    @patch("shop.pricing.calculate_reward_points")
    def test_admin_multiplier_is_used(self, mock_calculate_reward_points):
        """Pricing reads the current database configuration instead of constants."""
        self.config.s_multiplier = Decimal("0.75")
        self.config.save()
        mock_calculate_reward_points.return_value = {
            "highest_level": "S",
            "highest_level_year": 2026,
            "points": 60,
        }

        discount = resolve_user_tier_discount(self.user)
        pricing = calculate_shop_item_pricing(101, discount)

        self.assertEqual(pricing.cost, 76)
        self.assertEqual(pricing.multiplier, Decimal("0.75"))

    @patch("shop.pricing.calculate_reward_points")
    def test_c_and_d_tiers_pay_full_price(self, mock_calculate_reward_points):
        """Only SSS through B are eligible for a configured discount."""
        mock_calculate_reward_points.return_value = {
            "highest_level": "C",
            "highest_level_year": 2026,
            "points": 10,
        }

        discount = resolve_user_tier_discount(self.user)
        pricing = calculate_shop_item_pricing(101, discount)

        self.assertEqual(pricing.cost, 101)
        self.assertIsNone(pricing.tier)
        self.assertEqual(pricing.multiplier, Decimal("1.00"))

    @patch("shop.pricing.calculate_reward_points", side_effect=RuntimeError("offline"))
    def test_tier_lookup_failure_falls_back_to_full_price(self, _mock_calculate):
        """A dependency failure does not expose an unverified discount."""
        discount = resolve_user_tier_discount(self.user)
        pricing = calculate_shop_item_pricing(100, discount)

        self.assertEqual(pricing.cost, 100)
        self.assertIsNone(pricing.tier)
