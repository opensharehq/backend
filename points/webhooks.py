"""Webhook endpoints for external integrations."""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from points.models import WithdrawalContractSigning
from points.services import WithdrawalError
from points.withdrawal_contracts import handle_withdrawal_contract_webhook

logger = logging.getLogger(__name__)


def _read_json_body(request) -> dict[str, Any]:
    if not request.body:
        return {}
    payload = json.loads(request.body.decode("utf-8"))
    if not isinstance(payload, dict):
        msg = "JSON body must be an object."
        raise ValueError(msg)
    return payload


@csrf_exempt
def fdd_withdrawal_contract_webhook(request):
    """Webhook receiver for FaDaDa signing callbacks."""
    status = 200
    body: dict[str, Any] = {"ok": False}

    if request.method != "POST":
        status = 405
        body = {"detail": "Method not allowed."}
    else:
        expected_token = getattr(settings, "FDD_WEBHOOK_TOKEN", "")
        if expected_token:
            received = request.headers.get("X-FDD-Webhook-Token", "")
            if received != expected_token:
                status = 403
                body = {"detail": "Forbidden."}
        if status == 200:
            try:
                payload = _read_json_body(request)
            except (json.JSONDecodeError, ValueError):
                status = 400
                body = {"detail": "Invalid JSON."}
            else:
                try:
                    record = handle_withdrawal_contract_webhook(payload)
                except WithdrawalContractSigning.DoesNotExist:
                    status = 404
                    body = {"detail": "Signing record not found."}
                except WithdrawalError as exc:
                    status = 400
                    body = {"detail": str(exc)}
                except Exception:  # pragma: no cover - defensive
                    logger.exception("Unhandled error processing FaDaDa webhook")
                    status = 500
                    body = {"detail": "Internal error."}
                else:
                    body = {
                        "ok": True,
                        "record_id": record.id,
                        "status": record.status,
                    }

    return JsonResponse(body, status=status)
