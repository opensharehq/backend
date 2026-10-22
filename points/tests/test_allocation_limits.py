"""Recipient limit regression tests for allocation previews."""

from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase

from points.allocation_services import AllocationService
from points.models import PointAllocation


class AllocationRecipientLimitTests(SimpleTestCase):
    def test_preview_recipient_boundaries(self):
        allocation = PointAllocation(
            project_scope={"tags": ["repo:test"]},
            start_month=date(2024, 1, 1),
            end_month=date(2024, 1, 31),
        )
        contributions = [{"contribution_score": 1}] * 300_002
        cases = [
            ({}, 300_000),
            ({"top_n": 300_001}, 300_000),
            ({"top_n": 1}, 1),
            ({"max_recipients": None}, 300_002),
            ({"max_recipients": None, "top_n": 300_001}, 300_001),
            ({"max_recipients": None, "top_n": 1}, 1),
        ]
        with patch.object(
            AllocationService, "_get_contributions", return_value=contributions
        ):
            for kwargs, expected in cases:
                with self.subTest(**kwargs):
                    preview = AllocationService.preview_allocation(allocation, **kwargs)
                    self.assertEqual(len(preview), expected)

    def test_unlimited_preview_applies_top_n_after_user_scope(self):
        allocation = PointAllocation(
            project_scope={"tags": ["repo:test"]},
            user_scope={"tags": ["user:test"], "operation": "AND"},
        )
        contributions = [
            {"actor_id": "1", "contribution_score": 3},
            {"actor_id": "2", "contribution_score": 2},
            {"actor_id": "3", "contribution_score": 1},
        ]
        with (
            patch.object(
                AllocationService, "_get_contributions", return_value=contributions
            ),
            patch(
                "points.allocation_services.TagOperation.evaluate_user_tags",
                return_value={"2", "3"},
            ),
        ):
            preview = AllocationService.preview_allocation(
                allocation, max_recipients=None, top_n=1
            )
        self.assertEqual([item["actor_id"] for item in preview], ["2"])
