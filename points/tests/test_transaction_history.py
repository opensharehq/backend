"""Transaction history groups allocation debits before applying pagination."""

from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from accounts.models import Organization, OrganizationMembership, User
from accounts.services.jwt_tokens import create_access_token
from points.models import PointSource, PointTransaction, PointWallet


class TransactionHistoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="history-owner")
        self.outsider = User.objects.create_user(username="history-outsider")
        self.organization = Organization.objects.create(
            name="History Org", slug="history"
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.user,
            role=OrganizationMembership.Role.OWNER,
        )
        self.wallet = self.wallet_for(self.user)
        self.org_wallet = self.wallet_for(self.organization)
        self.source = PointSource.objects.create(
            wallet=self.wallet,
            point_type="gift",
            original_amount=10000,
            remaining_amount=10000,
            reason="Fixture",
        )
        self.headers = self.headers_for(self.user)
        self.url = "/api/v1/points/me/transactions"
        self.org_url = "/api/v1/points/organizations/history/transactions"

    @staticmethod
    def wallet_for(owner):
        return PointWallet.objects.create(
            content_type=ContentType.objects.get_for_model(owner), object_id=owner.pk
        )

    @staticmethod
    def headers_for(user):
        return {"HTTP_AUTHORIZATION": f"Bearer {create_access_token(user)}"}

    def add_transactions(self, count, **overrides):
        defaults = {
            "wallet": self.wallet,
            "source": self.source,
            "transaction_type": "spend",
            "point_type": "gift",
            "reference_id": "allocation_7",
            "amount": -3,
            "description": "Allocation fixture",
        }
        defaults.update(overrides)
        return PointTransaction.objects.bulk_create(
            [
                PointTransaction(balance_after=10000 - 3 * (index + 1), **defaults)
                for index in range(count)
            ]
        )

    def read(self, url=None, **params):
        response = self.client.get(
            url or self.url, {"group_allocations": "true", **params}, **self.headers
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_one_allocation_spanning_six_raw_pages_occupies_one_display_row(self):
        self.add_transactions(25, reference_id="", description="Other spending")
        debits = self.add_transactions(116)
        self.add_transactions(1, transaction_type="earn", amount=308)
        original_count = PointTransaction.objects.count()

        first = self.read()
        second = self.read(page=2)
        self.assertEqual(first["pagination"]["total_items"], 27)
        self.assertEqual(first["pagination"]["total_pages"], 2)
        self.assertEqual(len(first["items"]), 20)
        self.assertEqual(len(second["items"]), 7)
        self.assertEqual(first["items"][0]["transaction_type"], "earn")
        merged = first["items"][1]
        self.assertEqual(merged["amount"], -348)
        self.assertEqual(merged["merged_count"], 116)
        self.assertEqual(merged["id"], debits[-1].pk)
        self.assertEqual(merged["balance_after"], debits[-1].balance_after)
        self.assertFalse(
            any(item["reference_id"] == "allocation_7" for item in second["items"])
        )
        raw = self.client.get(self.url, **self.headers).json()
        self.assertEqual(raw["pagination"]["total_items"], original_count)
        self.assertNotIn("merged_count", raw["items"][0])
        self.assertEqual(PointTransaction.objects.count(), original_count)

    def test_different_sources_merge_and_keep_latest_transaction_balance(self):
        first = self.add_transactions(1)[0]
        other_source = PointSource.objects.create(
            wallet=self.wallet,
            point_type="gift",
            original_amount=100,
            remaining_amount=100,
        )
        self.add_transactions(1, source=other_source)
        # Creation time, rather than the largest ID or smallest balance, defines latest.
        PointTransaction.objects.filter(pk=first.pk).update(
            created_at=timezone.now() + timedelta(seconds=1)
        )
        result = self.read()
        self.assertEqual(result["pagination"]["total_items"], 1)
        self.assertEqual(result["items"][0]["id"], first.pk)
        self.assertEqual(result["items"][0]["amount"], -6)
        self.assertEqual(result["items"][0]["merged_count"], 2)
        self.assertEqual(result["items"][0]["balance_after"], first.balance_after)

    def test_filters_do_not_mix_credits_point_types_or_unrelated_references(self):
        self.add_transactions(2)
        self.add_transactions(2, reference_id="allocation_8")
        self.add_transactions(2, transaction_type="earn", amount=10)
        self.add_transactions(2, point_type="cash", source=None)
        self.add_transactions(2, reference_id="allocation_7_invalid")
        self.add_transactions(2, reference_id="shop_order_7")
        all_rows = self.read()["items"]
        self.assertEqual(len(all_rows), 9)
        self.assertEqual(sum(row["merged_count"] for row in all_rows), 12)
        gift_spends = self.read(point_type="gift", transaction_type="spend")
        self.assertEqual(gift_spends["pagination"]["total_items"], 6)
        self.assertTrue(all(row["amount"] < 0 for row in gift_spends["items"]))
        cash = self.read(point_type="cash")
        self.assertEqual(cash["items"][0]["merged_count"], 2)
        earned = self.read(transaction_type="earn")
        self.assertEqual(len(earned["items"]), 2)
        self.assertTrue(all(row["merged_count"] == 1 for row in earned["items"]))

    def test_organization_pagination_and_wallet_isolation(self):
        self.add_transactions(30, wallet=self.org_wallet, source=None)
        self.add_transactions(2, wallet=self.org_wallet, source=None, reference_id="")
        self.add_transactions(50)
        org_first = self.read(self.org_url, page_size=2)
        org_second = self.read(self.org_url, page_size=2, page=2)
        self.assertEqual(org_first["pagination"]["total_items"], 3)
        self.assertEqual(len(org_first["items"]), 2)
        self.assertEqual(org_second["items"][0]["merged_count"], 30)
        self.assertEqual(org_second["items"][0]["amount"], -90)
        self.assertEqual(self.read()["items"][0]["merged_count"], 50)
        self.assertEqual(org_first["organization"]["slug"], "history")
        denied = self.client.get(
            self.org_url,
            {"group_allocations": "true"},
            **self.headers_for(self.outsider),
        )
        self.assertEqual(denied.status_code, 403)

    def test_empty_history_and_page_size_limits(self):
        empty = self.read()
        self.assertEqual(empty["items"], [])
        self.assertEqual(empty["pagination"]["total_items"], 0)
        self.add_transactions(105, reference_id="")
        capped = self.read(page=-1, page_size=10000)
        self.assertEqual(capped["pagination"]["page"], 1)
        self.assertEqual(capped["pagination"]["page_size"], 100)
        self.assertEqual(len(capped["items"]), 100)
        last = self.read(page=999, page_size=100)
        self.assertEqual(last["pagination"]["page"], 2)
        self.assertEqual(len(last["items"]), 5)
