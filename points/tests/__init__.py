"""Tests for the points app."""

from .test_commands import GrantPointsCommandTests
from .test_integration import (
    PointsGrantingFlowTests,
    PointsManagementCommandFlowTests,
    PointsSpendingFlowTests,
    PointsViewFlowTests,
)
from .test_models import (
    PointSourceModelTests,
    PointTransactionModelTests,
    TagModelTests,
)
from .test_services import GrantPointsTests, SpendPointsTests
from .test_urls import URLTests
from .test_views import MyPointsViewTests

__all__ = [
    "GrantPointsCommandTests",
    "GrantPointsTests",
    "MyPointsViewTests",
    "PointSourceModelTests",
    "PointTransactionModelTests",
    "PointsGrantingFlowTests",
    "PointsManagementCommandFlowTests",
    "PointsSpendingFlowTests",
    "PointsViewFlowTests",
    "SpendPointsTests",
    "TagModelTests",
    "URLTests",
]
