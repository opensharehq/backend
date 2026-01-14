"""Withdrawal contract signing flow (pre-withdrawal signing)."""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from points.fadada import (
    FadadaClient,
    FadadaClientError,
    FadadaNotConfiguredError,
    FadadaRequestError,
)
from points.models import WithdrawalContractSigning
from points.services import (
    WithdrawalData,
    WithdrawalError,
    create_batch_withdrawal_requests,
    create_withdrawal_request,
)

logger = logging.getLogger(__name__)


def get_latest_signed_contract(
    user,
) -> WithdrawalContractSigning | None:
    """Return the most recent signed contract for the given user, if any."""
    return (
        WithdrawalContractSigning.objects.filter(
            user=user, status=WithdrawalContractSigning.Status.SIGNED
        )
        .order_by("-signed_at", "-created_at")
        .first()
    )


def get_latest_pending_contract(
    user,
) -> WithdrawalContractSigning | None:
    """Return the latest pending signing record for the given user, if any."""
    return (
        WithdrawalContractSigning.objects.filter(
            user=user, status=WithdrawalContractSigning.Status.PENDING
        )
        .order_by("-created_at")
        .first()
    )


def _extract_signing_record_id(payload: dict[str, Any]) -> int | None:
    candidates = (
        "signing_record_id",
        "signRecordId",
        "record_id",
        "bizId",
        "biz_id",
        "businessId",
        "business_id",
    )
    nested = payload.get("data") if isinstance(payload.get("data"), dict) else {}

    for key in candidates:
        raw = payload.get(key) or nested.get(key)
        if raw is None:
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


def _payload_indicates_signed(payload: dict[str, Any]) -> bool:
    def _upper(value: Any) -> str:
        return str(value or "").strip().upper()

    event = _upper(payload.get("event") or payload.get("type"))
    status = _upper(payload.get("status") or payload.get("signStatus"))
    result = _upper(payload.get("result") or payload.get("signResult"))

    nested = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    event = event or _upper(nested.get("event") or nested.get("type"))
    status = status or _upper(nested.get("status") or nested.get("signStatus"))
    result = result or _upper(nested.get("result") or nested.get("signResult"))

    signed_events = {
        "SIGN_FINISH",
        "SIGN_FINISHED",
        "SIGN_COMPLETE",
        "SIGN_COMPLETED",
        "CONTRACT_SIGNED",
    }
    signed_statuses = {"SIGNED", "COMPLETED", "FINISHED", "SUCCESS", "OK"}

    return (
        event in signed_events or status in signed_statuses or result in signed_statuses
    )


def _payload_indicates_failed(payload: dict[str, Any]) -> bool:
    def _upper(value: Any) -> str:
        return str(value or "").strip().upper()

    status = _upper(payload.get("status") or payload.get("signStatus"))
    nested = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    status = status or _upper(nested.get("status") or nested.get("signStatus"))

    return status in {"FAILED", "FAIL", "REJECTED", "CANCELLED", "CANCELED"}


def _withdrawal_data_from_contract(
    contract: WithdrawalContractSigning,
) -> WithdrawalData:
    return WithdrawalData(
        real_name=contract.real_name,
        id_number=contract.id_number,
        phone_number=contract.phone_number,
        bank_name=contract.bank_name,
        bank_account=contract.bank_account,
    )


@transaction.atomic
def start_withdrawal_contract_signing(
    *,
    user,
    withdrawal_data: WithdrawalData,
    withdrawal_payload: dict[str, Any],
) -> WithdrawalContractSigning:
    """Create a pending signing record and trigger the external signing workflow."""
    pending = (
        WithdrawalContractSigning.objects.select_for_update()
        .filter(user=user, status=WithdrawalContractSigning.Status.PENDING)
        .first()
    )
    if pending:
        return pending

    contract = WithdrawalContractSigning.objects.create(
        user=user,
        status=WithdrawalContractSigning.Status.PENDING,
        real_name=withdrawal_data.real_name,
        id_number=withdrawal_data.id_number,
        phone_number=withdrawal_data.phone_number,
        bank_name=withdrawal_data.bank_name,
        bank_account=withdrawal_data.bank_account,
        withdrawal_payload=withdrawal_payload,
        fdd_request_payload={
            "real_name": withdrawal_data.real_name,
            "id_number": withdrawal_data.id_number,
            "phone_number": withdrawal_data.phone_number,
            "bank_name": withdrawal_data.bank_name,
            "bank_account": withdrawal_data.bank_account,
            "signing_record_id": None,
        },
    )
    contract.fdd_request_payload["signing_record_id"] = contract.id
    contract.save(update_fields=["fdd_request_payload", "updated_at"])

    try:
        client = FadadaClient.from_settings()
        response = client.sign_with_template(
            withdrawal_data=withdrawal_data,
            signing_record_id=contract.id,
        )
        contract.fdd_response_payload = response
        contract.save(update_fields=["fdd_response_payload", "updated_at"])
    except NotImplementedError as exc:
        logger.exception(
            "提现合同签署接口未实现: user_id=%s, record_id=%s", user.id, contract.id
        )
        contract.status = WithdrawalContractSigning.Status.FAILED
        contract.fdd_response_payload = {
            "error": str(exc),
            "error_type": "NOT_IMPLEMENTED",
        }
        contract.save(update_fields=["status", "fdd_response_payload", "updated_at"])
        msg = f"合同签署接口尚未接入（记录ID: #{contract.id}），请联系管理员。"
        raise WithdrawalError(msg) from exc
    except FadadaNotConfiguredError as exc:
        logger.exception(
            "法大大配置缺失，无法发起提现合同签署: user_id=%s, record_id=%s",
            user.id,
            contract.id,
        )
        contract.status = WithdrawalContractSigning.Status.FAILED
        contract.fdd_response_payload = {
            "error": str(exc),
            "error_type": "NOT_CONFIGURED",
        }
        contract.save(update_fields=["status", "fdd_response_payload", "updated_at"])
        msg = f"合同签署服务未配置（记录ID: #{contract.id}），请联系管理员。"
        raise WithdrawalError(msg) from exc
    except FadadaRequestError as exc:
        logger.exception(
            "法大大请求失败，无法发起提现合同签署: user_id=%s, record_id=%s",
            user.id,
            contract.id,
        )
        contract.status = WithdrawalContractSigning.Status.FAILED
        contract.fdd_response_payload = {
            "error": str(exc),
            "error_type": "REQUEST_ERROR",
        }
        contract.save(update_fields=["status", "fdd_response_payload", "updated_at"])
        msg = "发起提现合同签署失败，请稍后重试。"
        raise WithdrawalError(msg) from exc
    except FadadaClientError as exc:
        logger.exception(
            "发起提现合同签署失败: user_id=%s, record_id=%s",
            user.id,
            contract.id,
        )
        contract.status = WithdrawalContractSigning.Status.FAILED
        contract.fdd_response_payload = {
            "error": str(exc),
            "error_type": "CLIENT_ERROR",
        }
        contract.save(update_fields=["status", "fdd_response_payload", "updated_at"])
        msg = "发起提现合同签署失败，请稍后重试或联系管理员。"
        raise WithdrawalError(msg) from exc

    return contract


@transaction.atomic
def handle_withdrawal_contract_webhook(
    payload: dict[str, Any],
) -> WithdrawalContractSigning:
    """Handle FaDaDa webhook payload and create withdrawal requests on success."""
    record_id = _extract_signing_record_id(payload)
    if not record_id:
        msg = "Webhook payload missing signing record id."
        raise WithdrawalError(msg)

    contract = WithdrawalContractSigning.objects.select_for_update().get(id=record_id)
    contract.fdd_webhook_payload = payload
    contract.save(update_fields=["fdd_webhook_payload", "updated_at"])

    if contract.status == WithdrawalContractSigning.Status.SIGNED:
        return contract

    if _payload_indicates_failed(payload):
        contract.status = WithdrawalContractSigning.Status.FAILED
        contract.save(update_fields=["status", "updated_at"])
        return contract

    if not _payload_indicates_signed(payload):
        return contract

    contract.status = WithdrawalContractSigning.Status.SIGNED
    contract.signed_at = timezone.now()
    contract.save(update_fields=["status", "signed_at", "updated_at"])

    if contract.created_withdrawal_request_ids:
        return contract

    created_ids: list[int] = []
    try:
        wd = _withdrawal_data_from_contract(contract)
        payload = contract.withdrawal_payload or {}
        if isinstance(payload.get("withdrawal_amounts"), dict):
            withdrawal_amounts = {
                int(key): int(value)
                for key, value in payload["withdrawal_amounts"].items()
            }
            requests = create_batch_withdrawal_requests(
                user=contract.user,
                withdrawal_amounts=withdrawal_amounts,
                withdrawal_data=wd,
            )
            created_ids = [req.id for req in requests]
        elif (
            payload.get("point_source_id") is not None
            and payload.get("points") is not None
        ):
            req = create_withdrawal_request(
                user=contract.user,
                point_source_id=int(payload["point_source_id"]),
                points=int(payload["points"]),
                withdrawal_data=wd,
            )
            created_ids = [req.id]
    except Exception as exc:  # pragma: no cover - defensive, depends on business state
        logger.exception(
            "签署完成后创建提现申请失败: record_id=%s, user_id=%s",
            contract.id,
            contract.user_id,
        )
        contract.withdrawal_error = str(exc)
        contract.save(update_fields=["withdrawal_error", "updated_at"])
        return contract

    if created_ids:
        contract.created_withdrawal_request_ids = created_ids
        contract.save(update_fields=["created_withdrawal_request_ids", "updated_at"])

    return contract
