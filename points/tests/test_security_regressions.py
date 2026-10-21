"""Regression tests for the points security audit, using isolated provider stubs."""

from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from social_django.models import UserSocialAuth

from accounts.models import (
    AccountMergeRequest,
    Education,
    Organization,
    ProfileRewardIdentity,
    User,
    UserProfile,
    WithdrawalAccount,
)
from accounts.services import profile_completion_reward as rewards
from accounts.services.account_merge import perform_merge
from accounts.services.jwt_tokens import create_access_token
from points import services as points
from points.models import (
    PendingPointGrant,
    PointSource,
    PointTransaction,
    PointType,
    Tag,
    WithdrawalRefund,
    WithdrawalRequest,
    WithdrawalStatus,
)
from shenbianyun import services as payments
from shenbianyun.models import PaymentRecord, PaymentState
from shop.models import Redemption, ShopItem
from shop.pricing import UserTierDiscount
from shop.services import RedemptionError, redeem_item
from talent_reach import services as outreach
from talent_reach.models import OutreachRecipient


@override_settings(
    SBY_TASK_ID="1",
    SBY_PROVIDER_ID="1",
    OUTREACH_COST_PER_USER=2,
    OUTREACH_REWARD_RATIO=0.5,
    OUTREACH_REWARD_EXPIRY_DAYS=30,
)
class PointsSecurityTests(TestCase):
    def user(self, name, staff=False, complete=False):
        u = User.objects.create_user(
            username=name, email=f"{name}@audit.invalid", is_active=True, is_staff=staff
        )
        p = UserProfile.objects.create(
            user=u,
            location_country_id=":divisions/CN",
            birth_date=date.today() - timedelta(days=20 * 365),
        )
        if complete:
            Education.objects.create(
                profile=p,
                institution_name="Audit",
                field_of_study="CS",
                start_date=date(2020, 1, 1),
            )
        return u

    def item(self, cost=100):
        return ShopItem.objects.create(
            name_zh="Audit item",
            name_en="Audit item",
            description_zh="Audit",
            cost=cost,
            stock=10,
        )

    def approved(self, name, amount=200):
        u = self.user(name)
        points.grant_points(u, amount, PointType.CASH, "test fixture")
        wr = points.create_withdrawal_request(
            u,
            amount,
            real_name="Audit",
            bank_account="000000",
            phone="13000000000",
            id_card="000000000000000000",
        )
        points.approve_withdrawal(wr.id, self.user(f"{name}_reviewer", staff=True))
        return u, wr

    def record(self, wr, order, state=PaymentState.INITIATED, batch="audit-batch"):
        return PaymentRecord.objects.create(
            mer_batch_id=batch,
            mer_order_id=order,
            order_no=f"provider-{order}",
            withdrawal_request=wr,
            amount=wr.amount * 10,
            state=state,
            payee_name="Audit",
            payee_acc="000000",
            id_card="000000000000000000",
            mobile="13000000000",
        )

    def test_staff_without_grant_permission_cannot_mint_cash(self):
        u = self.user("limited_staff", staff=True)
        self.assertFalse(u.has_perm("points.add_pointsource"))
        self.assertFalse(u.is_superuser)
        c = Client()
        c.force_login(u)
        response = c.post(
            f"/admin/points/grant-to-users/?ids={u.pk}",
            {"point_type": "cash", "amount": 100000, "reason": "audit"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(points.get_balance(u, PointType.CASH), 0)

    def test_reward_api_interleaving_grants_once(self):
        u = self.user("reward_race", complete=True)
        headers = {
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(u)}",
            "content_type": "application/json",
        }
        nested_response = []
        calls = 0

        def external_tier_lookup(_user):
            nonlocal calls
            calls += 1
            if calls == 1:
                # Pause request A after its real has_claimed_reward returned False;
                # request B now completes before A resumes. No guards are mocked.
                nested_response.append(
                    Client().patch("/api/v1/me/profile", {"bio": "B"}, **headers)
                )
            return {"points": 200, "highest_level": "SSS", "highest_level_year": 2025}

        with patch.object(
            rewards, "calculate_reward_points", side_effect=external_tier_lookup
        ):
            response = Client().patch("/api/v1/me/profile", {"bio": "A"}, **headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(nested_response[0].status_code, 200)
        count = PointSource.objects.filter(
            reference_id=f"profile_completion_reward:{u.pk}"
        ).count()
        self.assertEqual(count, 1)
        self.assertEqual(points.get_balance(u), 200)

    def test_replayed_batch_failure_refunds_once(self):
        u, failed_wr = self.approved("failed")
        _, pending_wr = self.approved("pending")
        failed = self.record(failed_wr, "failed")
        pending = self.record(pending_wr, "pending")
        response = {
            "res_data": {
                "queryItems": [
                    {
                        "orderNo": failed.order_no,
                        "state": int(PaymentState.FAILED),
                        "resMsg": "declined",
                    },
                    {"orderNo": pending.order_no, "state": int(PaymentState.PAYING)},
                ]
            }
        }
        with patch.object(payments.ShenbianyunClient, "request", return_value=response):
            payments.check_payment_status()
            balance_first = points.get_balance(u)
            payments.check_payment_status()
        self.assertEqual(balance_first, 200)
        self.assertEqual(points.get_balance(u), 200)
        self.assertEqual(
            PointSource.objects.filter(
                reference_id=f"refund:withdrawal:{failed_wr.pk}"
            ).count(),
            1,
        )

    def test_ambiguous_payment_is_reconciled_without_refund(self):
        u, wr = self.approved("timeout")
        with patch.object(
            payments.ShenbianyunClient,
            "request",
            side_effect=payments.ShenbianyunRequestError("lost response"),
        ):
            payments.batch_payment()
        record = PaymentRecord.objects.get(withdrawal_request=wr)
        self.assertEqual(points.get_balance(u), 0)
        self.assertEqual(record.state, PaymentState.UNKNOWN)
        response = {
            "res_data": {
                "queryItems": [
                    {
                        "merOrderId": record.mer_order_id,
                        "orderNo": "recovered-order",
                        "state": PaymentState.SUCCESS,
                    }
                ]
            }
        }
        with patch.object(
            payments.ShenbianyunClient, "request", return_value=response
        ) as provider:
            self.assertEqual(payments.check_payment_status()["checked"], 1)
            self.assertEqual(payments.batch_payment()["batched"], 0)
        self.assertEqual(provider.call_count, 1)
        wr.refresh_from_db()
        self.assertEqual(wr.status, WithdrawalStatus.COMPLETED)
        self.assertEqual(points.get_balance(u), 0)

    def test_expired_points_cannot_redeem(self):
        u = self.user("expired")
        points.grant_points(
            u,
            100,
            PointType.GIFT,
            "expired fixture",
            expires_at=timezone.now() - timedelta(days=1),
        )
        with patch(
            "shop.services.resolve_user_tier_discount", return_value=UserTierDiscount()
        ):
            with self.assertRaises(RedemptionError):
                redeem_item(u, self.item().pk)
        self.assertEqual(points.get_balance(u), 0)
        self.assertFalse(Redemption.objects.filter(user_profile=u).exists())

    def test_outreach_preserves_restricted_tag(self):
        u = self.user("tagged_sender")
        recipient = self.user("tagged_receiver")
        tag = Tag.objects.create(name="Restricted Audit", slug="restricted-audit")
        points.grant_points(u, 2, PointType.GIFT, "tagged fixture", tag_slug=tag.slug)
        draft = outreach.create_draft(author=u, title="Audit", content="Audit")
        preview = {"developers": [{"user_id": recipient.pk, "openrank_score": 1.0}]}
        with patch.object(outreach, "preview_recipients", return_value=preview):
            campaign = outreach.send_outreach(
                draft.id,
                u,
                ["audit"],
                ["audit"],
                None,
                None,
                None,
                1,
                PointType.GIFT,
                tag_slug=tag.slug,
            )
        grant_recipient = OutreachRecipient.objects.get(
            campaign=campaign, user=recipient
        )
        outreach.claim_reading_reward(recipient, grant_recipient.user_message_id)
        source = PointSource.objects.get(wallet=points.get_or_create_wallet(recipient))
        self.assertEqual(source.tag_id, tag.pk)
        with patch(
            "shop.services.resolve_user_tier_discount", return_value=UserTierDiscount()
        ):
            with self.assertRaises(RedemptionError):
                redeem_item(recipient, self.item(cost=1).pk, tag_slug=tag.slug)

    def test_admin_status_cannot_bypass_debit(self):
        u = self.user("status_owner")
        points.grant_points(u, 200, PointType.CASH, "fixture")
        wr = points.create_withdrawal_request(u, 200)
        staff = self.user("status_staff", staff=True)
        staff.user_permissions.add(
            Permission.objects.get(codename="change_withdrawalrequest")
        )
        c = Client()
        c.force_login(staff)
        response = c.post(
            f"/admin/points/withdrawalrequest/{wr.pk}/change/",
            {"status": "approved", "admin_note": "Audit", "_save": "Save"},
        )
        self.assertEqual(response.status_code, 302, response.content[:2000])
        wr.refresh_from_db()
        self.assertEqual(wr.status, WithdrawalStatus.PENDING)
        self.assertIsNone(wr.transaction_id)
        with patch.object(
            payments.ShenbianyunClient, "request", return_value={"res_data": {}}
        ) as provider:
            payments.batch_payment()
        self.assertEqual(provider.call_count, 0)
        self.assertEqual(points.get_balance(u), 200)

    def test_payment_dispatch_is_unique_and_replay_does_not_resubmit(self):
        u, wr = self.approved("double_pay")
        with patch.object(
            payments.ShenbianyunClient, "request", return_value={"res_data": {}}
        ) as provider:
            payments.batch_payment()
            payments.batch_payment()
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(PaymentRecord.objects.filter(withdrawal_request=wr).count(), 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.record(wr, "duplicate")
        self.assertEqual(points.get_balance(u), 0)

    def test_merge_preserves_reward_claim_after_spending(self):
        source = self.user("merge_source", complete=True)
        target = self.user("merge_target", complete=True)
        UserSocialAuth.objects.create(
            user=source, provider="github", uid="audit-identity"
        )
        # The external contribution oracle always describes the same verified UID.
        with (
            patch.object(
                rewards,
                "query_user_yearly_openrank",
                return_value=[{"year": 2025, "yearly_openrank": 1000}],
            ),
            patch.object(
                rewards,
                "_fetch_baseline_tiers",
                return_value={"2025": [100, 90, 80, 70, 60, 50]},
            ),
        ):
            first = rewards.grant_profile_completion_reward(source)
            with patch(
                "shop.services.resolve_user_tier_discount",
                return_value=UserTierDiscount(),
            ):
                redeem_item(source, self.item(cost=200).pk)
            req = AccountMergeRequest.objects.create(
                source_user=source,
                target_user=target,
                status=AccountMergeRequest.Status.PENDING,
                approve_token="audit-merge",
                expires_at=timezone.now() + timedelta(days=1),
            )
            perform_merge(req)
            target = User.objects.get(pk=target.pk)
            self.assertTrue(rewards.has_claimed_reward(target))
            second = rewards.grant_profile_completion_reward(target)
        self.assertEqual(first["points"], 200)
        self.assertIsNone(second)
        self.assertEqual(points.get_balance(target), 0)

    def allocation_payload(self, receiver, amount=100, selector=None):
        return {
            "source_selector": selector
            or {"owner_type": "user", "point_type": "gift", "tag_slug": None},
            "project_scope": {"tags": ["audit-project"], "operation": "AND"},
            "start_month": "2025-01-01",
            "end_month": "2025-02-01",
            "total_amount": amount,
            "allocations": [
                {
                    "actor_id": "audit-recipient",
                    "actor_login": receiver.username,
                    "platform": "github",
                    "is_registered": True,
                    "user_id": receiver.pk,
                    "contribution_score": 1,
                    "amount": amount,
                }
            ],
        }

    def test_allocation_preserves_expiry(self):
        sender = self.user("expiry_sender")
        receiver = self.user("expiry_receiver")
        source = points.grant_points(
            sender,
            100,
            PointType.GIFT,
            "finite grant",
            expires_at=timezone.now() + timedelta(days=1),
        )
        response = Client().post(
            "/api/v1/points/allocations",
            self.allocation_payload(receiver),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {create_access_token(sender)}",
        )
        self.assertEqual(response.status_code, 201, response.content)
        received = PointSource.objects.get(wallet=points.get_or_create_wallet(receiver))
        self.assertEqual(received.expires_at, source.expires_at)

    def test_unauthorized_and_invalid_allocations_fail(self):
        from accounts.models import Organization, OrganizationMembership

        sender = self.user("allocation_sender")
        receiver = self.user("allocation_receiver")
        points.grant_points(sender, 100, PointType.GIFT, "fixture")
        headers = {
            "content_type": "application/json",
            "HTTP_AUTHORIZATION": f"Bearer {create_access_token(sender)}",
        }
        payload = self.allocation_payload(receiver)
        payload["allocations"][0]["amount"] = -100
        response_negative = Client().post(
            "/api/v1/points/allocations", payload, **headers
        )
        self.assertEqual(response_negative.status_code, 422)
        payload = self.allocation_payload(receiver, amount=101)
        response_over = Client().post("/api/v1/points/allocations", payload, **headers)
        self.assertEqual(response_over.status_code, 409)
        org = Organization.objects.create(name="Audit org", slug="audit-org")
        OrganizationMembership.objects.create(
            user=sender, organization=org, role="member"
        )
        points.grant_points(org, 100, PointType.GIFT, "org fixture")
        selector = {
            "owner_type": "organization",
            "owner_slug": org.slug,
            "point_type": "gift",
            "tag_slug": None,
        }
        response_org = Client().post(
            "/api/v1/points/allocations",
            self.allocation_payload(receiver, selector=selector),
            **headers,
        )
        self.assertEqual(response_org.status_code, 403)
        self.assertEqual(points.get_balance(sender), 100)
        self.assertEqual(points.get_balance(receiver), 0)
        self.assertEqual(points.get_balance(org), 100)

    def test_tag_balance_stock_and_price_checks(self):
        u = self.user("redemption_controls")
        tag = Tag.objects.create(name="Control restricted", slug="control-restricted")
        points.grant_points(u, 100, PointType.GIFT, "fixture", tag_slug=tag.slug)
        item = self.item(cost=100)
        with patch(
            "shop.services.resolve_user_tier_discount", return_value=UserTierDiscount()
        ):
            with self.assertRaises(RedemptionError):
                redeem_item(u, item.pk, tag_slug=tag.slug)
            with self.assertRaises(RedemptionError):
                redeem_item(u, item.pk)
            item.allowed_tags.add(tag)
            with self.assertRaises(RedemptionError):
                redeem_item(u, item.pk, tag_slug=tag.slug, expected_points_cost=1)
            item.stock = 0
            item.save(update_fields=["stock"])
            with self.assertRaises(RedemptionError):
                redeem_item(u, item.pk, tag_slug=tag.slug)
        self.assertEqual(points.get_balance(u), 100)
        self.assertFalse(Redemption.objects.filter(user_profile=u).exists())

    def test_grant_permission_required_for_users_and_organizations(self):
        staff = self.user("grant_staff", staff=True)
        org = Organization.objects.create(name="Permission org", slug="permission-org")
        client = Client()
        client.force_login(staff)
        urls = [
            f"/admin/points/grant-to-users/?ids={staff.pk}",
            f"/admin/points/grant-to-orgs/?ids={org.pk}",
        ]
        for url in urls:
            self.assertEqual(client.get(url).status_code, 403)
            self.assertEqual(
                client.post(
                    url, {"point_type": "cash", "amount": 10, "reason": "test"}
                ).status_code,
                403,
            )
        staff.user_permissions.add(Permission.objects.get(codename="grant_points"))
        for url in urls:
            self.assertEqual(
                client.post(
                    url, {"point_type": "cash", "amount": 10, "reason": "test"}
                ).status_code,
                302,
            )
        self.assertEqual(points.get_balance(staff), 10)
        self.assertEqual(points.get_balance(org), 10)

    def test_refund_requires_exact_debit_and_rolls_back_on_failure(self):
        user = self.user("refund_validation")
        points.grant_points(user, 200, PointType.CASH, "test")
        withdrawal = points.create_withdrawal_request(user, 200)
        with self.assertRaises(points.WithdrawalError):
            points.refund_withdrawal(withdrawal)
        WithdrawalRequest.objects.filter(pk=withdrawal.pk).update(
            status=WithdrawalStatus.APPROVED
        )
        with self.assertRaises(points.WithdrawalError):
            points.refund_withdrawal(withdrawal)
        with patch.object(payments.ShenbianyunClient, "request") as provider:
            self.assertEqual(payments.batch_payment()["batched"], 0)
        provider.assert_not_called()
        WithdrawalRequest.objects.filter(pk=withdrawal.pk).update(
            status=WithdrawalStatus.PENDING
        )
        points.approve_withdrawal(withdrawal.pk, self.user("refund_admin", staff=True))
        with patch.object(
            PointTransaction.objects,
            "create",
            side_effect=RuntimeError("ledger unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                points.refund_withdrawal(withdrawal)
        self.assertFalse(
            WithdrawalRefund.objects.filter(withdrawal=withdrawal).exists()
        )
        self.assertEqual(points.get_balance(user), 0)
        self.assertTrue(points.refund_withdrawal(withdrawal))
        self.assertFalse(points.refund_withdrawal(withdrawal))
        self.assertEqual(points.get_balance(user), 200)

    def test_refund_preserves_each_debit_expiry(self):
        user = self.user("refund_expiry")
        expiry = timezone.now() + timedelta(days=1)
        points.grant_points(user, 50, PointType.CASH, "finite", expires_at=expiry)
        points.grant_points(user, 150, PointType.CASH, "permanent")
        withdrawal = points.create_withdrawal_request(user, 200)
        points.approve_withdrawal(
            withdrawal.pk, self.user("refund_expiry_admin", staff=True)
        )
        points.refund_withdrawal(withdrawal)
        lots = PointSource.objects.filter(
            reference_id=f"refund:withdrawal:{withdrawal.pk}"
        )
        self.assertCountEqual(
            list(lots.values_list("original_amount", "expires_at")),
            [(50, expiry), (150, None)],
        )
        self.assertEqual(
            WithdrawalRefund.objects.filter(withdrawal=withdrawal).count(), 1
        )

    def test_legacy_refund_is_not_reissued(self):
        user, withdrawal = self.approved("legacy_refund")
        points.grant_points(
            user,
            200,
            PointType.CASH,
            "legacy refund",
            reference_id=f"refund:withdrawal:{withdrawal.pk}",
        )
        self.assertFalse(points.refund_withdrawal(withdrawal))
        self.assertEqual(points.get_balance(user), 200)
        self.assertTrue(WithdrawalRefund.objects.filter(withdrawal=withdrawal).exists())

    def test_completed_withdrawal_cannot_be_refunded(self):
        user, withdrawal = self.approved("completed_no_refund")
        points.complete_withdrawal(withdrawal.pk, self.user("manual_admin", staff=True))
        with self.assertRaises(points.WithdrawalError):
            points.refund_withdrawal(withdrawal)
        self.assertEqual(points.get_balance(user), 0)

    def test_missing_or_cross_batch_order_ids_do_not_match(self):
        _, first = self.approved("id_first")
        _, second = self.approved("id_second")
        a = self.record(first, "id_a", batch="a")
        b = self.record(second, "id_b", batch="b")
        a.order_no = ""
        a.save(update_fields=["order_no"])
        self.assertIsNone(payments._find_payment_record("a", {}))
        self.assertIsNone(
            payments._find_payment_record("a", {"merOrderId": b.mer_order_id})
        )
        self.assertIsNone(
            payments._find_payment_record(
                "b", {"merOrderId": b.mer_order_id, "orderNo": "unrecognized"}
            )
        )
        self.assertEqual(
            payments._find_payment_record("a", {"merOrderId": a.mer_order_id}).pk, a.pk
        )

    def test_terminal_payment_is_not_downgraded_or_refunded(self):
        user, withdrawal = self.approved("terminal")
        record = self.record(withdrawal, "terminal")
        self.assertTrue(
            payments._settle_payment(record, {"state": PaymentState.SUCCESS})
        )
        self.assertFalse(
            payments._settle_payment(record, {"state": PaymentState.FAILED})
        )
        self.assertEqual(points.get_balance(user), 0)
        self.assertFalse(
            WithdrawalRefund.objects.filter(withdrawal=withdrawal).exists()
        )

    def test_invalid_payment_end_time_warns_without_blocking_settlement(self):
        for state in (PaymentState.SUCCESS, PaymentState.FAILED):
            for index, invalid_time in enumerate(("invalid-time", 123456)):
                with self.subTest(state=state, end_time=invalid_time):
                    name = f"invalid_time_{state}_{index}"
                    user, withdrawal = self.approved(name)
                    record = self.record(withdrawal, name)
                    previous_time = timezone.now() - timedelta(days=1)
                    record.end_time = previous_time
                    record.save(update_fields=["end_time"])
                    with self.assertLogs(
                        "shenbianyun.services", level="WARNING"
                    ) as logs:
                        settled = payments._settle_payment(
                            record, {"state": state, "endTime": invalid_time}
                        )
                    self.assertTrue(settled)
                    self.assertEqual(len(logs.records), 1)
                    self.assertIn(f"payment_id={record.pk}", logs.output[0])
                    record.refresh_from_db()
                    withdrawal.refresh_from_db()
                    self.assertEqual(record.end_time, previous_time)
                    self.assertEqual(record.state, state)
                    failed = state == PaymentState.FAILED
                    self.assertEqual(
                        withdrawal.status,
                        WithdrawalStatus.REJECTED
                        if failed
                        else WithdrawalStatus.COMPLETED,
                    )
                    self.assertEqual(points.get_balance(user), 200 if failed else 0)
                    self.assertEqual(
                        WithdrawalRefund.objects.filter(withdrawal=withdrawal).count(),
                        int(failed),
                    )

    def test_valid_payment_end_time_is_saved_as_aware_datetime(self):
        _, withdrawal = self.approved("valid_time")
        record = self.record(withdrawal, "valid_time")
        with self.assertNoLogs("shenbianyun.services", level="WARNING"):
            self.assertTrue(
                payments._settle_payment(
                    record,
                    {"state": PaymentState.SUCCESS, "endTime": "2026-10-21 12:34:56"},
                )
            )
        record.refresh_from_db()
        self.assertTrue(timezone.is_aware(record.end_time))
        self.assertEqual(
            timezone.localtime(record.end_time).strftime("%Y-%m-%d %H:%M:%S"),
            "2026-10-21 12:34:56",
        )

    def test_payment_uses_frozen_withdrawal_account(self):
        user, withdrawal = self.approved("snapshot")
        account = WithdrawalAccount.objects.create(
            user=user,
            real_name="Changed",
            bank_card="changed-bank",
            phone="13900000000",
            id_card="changed-id",
        )
        WithdrawalRequest.objects.filter(pk=withdrawal.pk).update(
            withdrawal_account=account
        )
        with patch.object(
            payments.ShenbianyunClient, "request", return_value={"res_data": {}}
        ) as provider:
            payments.batch_payment()
        item = provider.call_args.kwargs["req_data"]["payItems"][0]
        self.assertEqual(item["payeeAcc"], withdrawal.bank_account)
        self.assertEqual(item["payeeName"], withdrawal.real_name)

    def test_reward_failure_rolls_back_identity_and_flag(self):
        user = self.user("reward_rollback", complete=True)
        UserSocialAuth.objects.create(
            user=user, provider="github", uid="rollback-identity"
        )
        with (
            patch.object(
                rewards, "calculate_reward_points", return_value={"points": 200}
            ),
            patch.object(
                rewards, "grant_points", side_effect=RuntimeError("ledger unavailable")
            ),
        ):
            with self.assertRaises(RuntimeError):
                rewards.grant_profile_completion_reward(user)
        user.profile.refresh_from_db()
        self.assertFalse(user.profile.profile_completion_rewarded)
        self.assertFalse(
            ProfileRewardIdentity.objects.filter(uid="rollback-identity").exists()
        )
        self.assertEqual(points.get_balance(user), 0)

    def test_unlink_and_relink_cannot_reset_reward_identity(self):
        source = self.user("unlink_source", complete=True)
        target = self.user("unlink_target", complete=True)
        social = UserSocialAuth.objects.create(
            user=source, provider="github", uid="permanent-identity"
        )
        with patch.object(
            rewards, "calculate_reward_points", return_value={"points": 200}
        ):
            rewards.grant_profile_completion_reward(source)
            social.delete()
            UserSocialAuth.objects.create(
                user=target, provider="github", uid="permanent-identity"
            )
            self.assertIsNone(rewards.grant_profile_completion_reward(target))
        self.assertEqual(points.get_balance(target), 0)

    def test_binding_change_during_calculation_discards_stale_reward(self):
        user = self.user("binding_change", complete=True)
        identity = UserSocialAuth.objects.create(
            user=user, provider="github", uid="old-identity"
        )

        def change_binding(_user):
            identity.delete()
            return {"points": 200}

        with patch.object(
            rewards, "calculate_reward_points", side_effect=change_binding
        ):
            self.assertIsNone(rewards.grant_profile_completion_reward(user))
        self.assertEqual(points.get_balance(user), 0)

    def test_expiry_applies_to_all_balance_and_spending_views(self):
        user = self.user("expiry_all_paths")
        now = timezone.now()
        for kind in (PointType.CASH, PointType.GIFT):
            points.grant_points(user, 100, kind, "expired", expires_at=now)
        self.assertEqual(points.get_detailed_balance(user)["total"], 0)
        self.assertEqual(points.get_detailed_balance_or_zero(user)["total"], 0)
        with self.assertRaises(points.InsufficientPointsError):
            points.spend_points(
                user, 1, PointType.GIFT, "no expired spending", tag_is_null=True
            )
        with self.assertRaises(points.InsufficientPointsError):
            points.spend_points_with_fallback(
                user, 1, PointType.GIFT, "no expired fallback", use_cash=True
            )
        with self.assertRaises(points.InsufficientPointsError):
            points.create_withdrawal_request(user, 200)

    def test_mixed_expiry_allocation_and_pending_claim_preserve_lots(self):
        from points.allocation_services import AllocationService

        sender = self.user("mixed_sender")
        receiver = self.user("mixed_receiver")
        expiry = timezone.now() + timedelta(days=1)
        points.grant_points(sender, 60, PointType.GIFT, "finite", expires_at=expiry)
        points.grant_points(sender, 40, PointType.GIFT, "permanent")
        payload = self.allocation_payload(receiver)
        payload["allocations"][0].update(
            is_registered=False, user_id=None, actor_id="pending-mixed"
        )
        response = Client().post(
            "/api/v1/points/allocations",
            payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {create_access_token(sender)}",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertCountEqual(
            list(PendingPointGrant.objects.values_list("amount", "expires_at")),
            [(60, expiry), (40, None)],
        )
        UserSocialAuth.objects.create(
            user=receiver, provider="github", uid="pending-mixed"
        )
        self.assertEqual(points.get_balance(receiver), 100)
        self.assertEqual(PendingPointGrant.objects.filter(is_claimed=True).count(), 2)
        lots = PointSource.objects.filter(wallet=points.get_or_create_wallet(receiver))
        self.assertCountEqual(
            list(lots.values_list("original_amount", "expires_at")),
            [(60, expiry), (40, None)],
        )
        self.assertEqual(
            AllocationService.claim_pending_points(receiver)["total_amount"], 0
        )
        self.assertEqual(points.get_balance(sender), 0)

    def test_outreach_reward_preserves_mixed_expiry_and_excludes_expired_share(self):
        user = self.user("mixed_outreach_sender")
        receiver = self.user("mixed_outreach_receiver")
        tag = Tag.objects.create(name="Mixed outreach", slug="mixed-outreach")
        early = timezone.now() + timedelta(days=1)
        late = timezone.now() + timedelta(days=3)
        points.grant_points(
            user, 1, PointType.GIFT, "early", tag_slug=tag.slug, expires_at=early
        )
        points.grant_points(
            user, 3, PointType.GIFT, "late", tag_slug=tag.slug, expires_at=late
        )
        draft = outreach.create_draft(user, "Mixed", "Mixed")
        with (
            override_settings(OUTREACH_COST_PER_USER=4),
            patch.object(
                outreach,
                "preview_recipients",
                return_value={
                    "developers": [{"user_id": receiver.pk, "openrank_score": 1.0}]
                },
            ),
        ):
            campaign = outreach.send_outreach(
                draft.pk,
                user,
                ["audit"],
                ["audit"],
                None,
                None,
                None,
                1,
                PointType.GIFT,
                tag_slug=tag.slug,
            )
        recipient = OutreachRecipient.objects.get(campaign=campaign)
        with patch(
            "talent_reach.services.timezone.now",
            return_value=early + timedelta(seconds=1),
        ):
            result = outreach.claim_reading_reward(receiver, recipient.user_message_id)
        self.assertEqual(result["reward_amount"], 1)
        granted = PointSource.objects.get(wallet=points.get_or_create_wallet(receiver))
        self.assertEqual(granted.expires_at, late)
        self.assertEqual(granted.tag_id, tag.pk)
        self.assertIsNone(
            outreach.claim_reading_reward(receiver, recipient.user_message_id)
        )

    def test_payment_admin_cannot_edit_or_delete_dispatch_evidence(self):
        _, withdrawal = self.approved("admin_payment")
        record = self.record(withdrawal, "admin-payment")
        admin = self.user("payment_admin", staff=True)
        admin.is_superuser = True
        admin.save(update_fields=["is_superuser"])
        client = Client()
        client.force_login(admin)
        base = f"/admin/shenbianyun/paymentrecord/{record.pk}/"
        self.assertEqual(client.get(f"{base}change/").status_code, 200)
        self.assertEqual(
            client.post(
                f"{base}change/", {"state": PaymentState.FAILED, "_save": "Save"}
            ).status_code,
            403,
        )
        self.assertEqual(
            client.post(f"{base}delete/", {"post": "yes"}).status_code, 403
        )
        record.refresh_from_db()
        self.assertEqual(record.state, PaymentState.INITIATED)

    def test_registered_allocation_splits_lots_without_extending_expiry(self):
        sender = self.user("split_sender")
        first = self.user("split_first")
        second = self.user("split_second")
        expiry = timezone.now() + timedelta(days=1)
        points.grant_points(sender, 50, PointType.GIFT, "finite", expires_at=expiry)
        points.grant_points(sender, 50, PointType.GIFT, "permanent")
        payload = self.allocation_payload(first, 35)
        payload["total_amount"] = 100
        payload["allocations"] += self.allocation_payload(second, 65)["allocations"]
        response = Client().post(
            "/api/v1/points/allocations",
            payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {create_access_token(sender)}",
        )
        self.assertEqual(response.status_code, 201, response.content)
        first_lots = PointSource.objects.filter(
            wallet=points.get_or_create_wallet(first)
        )
        second_lots = PointSource.objects.filter(
            wallet=points.get_or_create_wallet(second)
        )
        self.assertCountEqual(
            list(first_lots.values_list("original_amount", "expires_at")),
            [(35, expiry)],
        )
        self.assertCountEqual(
            list(second_lots.values_list("original_amount", "expires_at")),
            [(15, expiry), (50, None)],
        )
        self.assertEqual(points.get_balance(sender), 0)

    def test_merge_during_reward_calculation_cannot_reward_deactivated_source(self):
        source = self.user("racing_merge_source", complete=True)
        target = self.user("racing_merge_target", complete=True)
        request = AccountMergeRequest.objects.create(
            source_user=source,
            target_user=target,
            approve_token="racing-merge",
            expires_at=timezone.now() + timedelta(days=1),
        )

        def merge_while_calculating(_user):
            perform_merge(request)
            return {"points": 200}

        with patch.object(
            rewards, "calculate_reward_points", side_effect=merge_while_calculating
        ):
            self.assertIsNone(rewards.grant_profile_completion_reward(source))
        self.assertEqual(points.get_balance(source), 0)
        self.assertEqual(points.get_balance(target), 0)
