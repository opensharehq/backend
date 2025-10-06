"""Shop test suite - modular test structure."""

from .test_integration import (
    FullUserJourneyTests,
    ShopRedemptionFlowTests,
    ShopViewFlowTests,
)
from .test_models import RedemptionModelTests, ShopItemModelTests
from .test_services import RedeemItemServiceTests

__all__ = [
    "FullUserJourneyTests",
    "RedeemItemServiceTests",
    "RedemptionModelTests",
    "ShopItemModelTests",
    "ShopRedemptionFlowTests",
    "ShopViewFlowTests",
]
