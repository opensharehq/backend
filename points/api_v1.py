# ruff: noqa: D101, EM101, B904, PLR0913
"""Points, wallet, withdrawal, and allocation endpoints for API v1."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from json import JSONDecodeError

from django.contrib.contenttypes.models import ContentType
from django.db.models import Min, Sum
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from accounts.api_v1 import jwt_bearer_auth
from accounts.models import Organization, OrganizationMembership, User
from accounts.services.masking import mask_card, mask_name
from config.api_common import (
    ApiError,
    ErrorResponseSchema,
    build_paginated_response,
    form_error_detail,
    paginate_queryset,
    validate_form,
)
from contributions.services import ContributionDataUnavailableError

from . import services
from .allocation_services import AllocationService
from .forms import WithdrawalRequestForm
from .models import (
    PointAllocation,
    PointSource,
    PointTransaction,
    PointType,
    Tag,
    TransactionType,
    WithdrawalRequest,
)

router = Router(tags=["points"], auth=jwt_bearer_auth)

VALID_TAG_OPERATIONS = {"AND", "OR", "NOT", "XOR"}


class SourceSelectorSchema(Schema):
    owner_type: str
    owner_slug: str | None = None
    point_type: str
    tag_slug: str | None = None


class AllocationScopeSchema(Schema):
    tags: list[str]
    operation: str = "AND"


class AllocationPreviewRequestSchema(Schema):
    source_selector: SourceSelectorSchema
    project_scope: AllocationScopeSchema
    user_scope: AllocationScopeSchema | None = None
    start_month: date
    end_month: date


class AllocationItemSchema(Schema):
    actor_id: str
    actor_login: str
    platform: str
    email: str = ""
    is_registered: bool
    user_id: int | None = None
    contribution_score: float
    amount: int


class AllocationExecuteRequestSchema(Schema):
    source_selector: SourceSelectorSchema
    project_scope: AllocationScopeSchema
    user_scope: AllocationScopeSchema | None = None
    start_month: date
    end_month: date
    adjustment_ratio: float = 1.0
    total_amount: int
    allocations: list[AllocationItemSchema]


def _validation_detail(field: str, message: str, code: str = "invalid") -> dict:
    return {field: [{"message": message, "code": code}]}


def _serialize_transaction(transaction: PointTransaction) -> dict:
    return {
        "id": transaction.id,
        "transaction_type": transaction.transaction_type,
        "point_type": transaction.point_type,
        "amount": transaction.amount,
        "balance_after": transaction.balance_after,
        "description": transaction.description,
        "reference_id": transaction.reference_id,
        "source_id": transaction.source_id,
        "tag": (
            {
                "id": transaction.tag_id,
                "slug": transaction.tag.slug,
                "name": transaction.tag.name,
            }
            if transaction.tag
            else None
        ),
        "created_by": (
            {
                "id": transaction.created_by_id,
                "username": transaction.created_by.username,
            }
            if transaction.created_by
            else None
        ),
        "created_at": transaction.created_at.isoformat(),
    }


def _serialize_withdrawal(withdrawal: WithdrawalRequest) -> dict:
    owner = withdrawal.wallet.owner
    owner_type = "organization" if isinstance(owner, Organization) else "user"
    owner_slug = owner.slug if isinstance(owner, Organization) else None

    # 优先从关联的提现账号读取银行卡号，确保同一账号的记录掩码一致
    if withdrawal.withdrawal_account_id and withdrawal.withdrawal_account:
        raw_bank_account = (
            withdrawal.withdrawal_account.bank_card
            or withdrawal.withdrawal_account.swift_account
        )
    else:
        raw_bank_account = withdrawal.bank_account

    return {
        "id": withdrawal.id,
        "owner_type": owner_type,
        "owner_slug": owner_slug,
        "amount": withdrawal.amount,
        "status": withdrawal.status,
        "real_name": mask_name(withdrawal.real_name),
        "phone": withdrawal.phone,
        "id_card": withdrawal.id_card,
        "bank_name": withdrawal.bank_name,
        "bank_account": mask_card(raw_bank_account),
        "withdrawal_account_id": withdrawal.withdrawal_account_id,
        "invoice_file_url": withdrawal.invoice_file.url
        if withdrawal.invoice_file
        else None,
        "admin_note": withdrawal.admin_note,
        "processed_at": withdrawal.processed_at.isoformat()
        if withdrawal.processed_at
        else None,
        "created_at": withdrawal.created_at.isoformat(),
        "updated_at": withdrawal.updated_at.isoformat(),
    }


def _build_source_selector(owner, point_type: str, tag_slug: str | None) -> dict:
    return {
        "owner_type": "organization" if isinstance(owner, Organization) else "user",
        "owner_slug": owner.slug if isinstance(owner, Organization) else None,
        "point_type": point_type,
        "tag_slug": tag_slug,
    }


def _serialize_pool(
    owner,
    point_type: str,
    tag_slug: str | None,
    tag_name: str | None,
    available_balance: int,
) -> dict:
    return {
        "owner_type": "organization" if isinstance(owner, Organization) else "user",
        "owner_slug": owner.slug if isinstance(owner, Organization) else None,
        "owner_name": owner.name if isinstance(owner, Organization) else owner.username,
        "point_type": point_type,
        "tag": (
            {
                "slug": tag_slug,
                "name": tag_name,
            }
            if point_type == PointType.GIFT
            else None
        ),
        "available_balance": available_balance,
        "source_selector": _build_source_selector(owner, point_type, tag_slug),
    }


def _serialize_allocation(allocation: PointAllocation) -> dict:
    source_owner = allocation.source_pool.wallet.owner
    pending_grants = list(allocation.pending_grants.select_related("tag").all())
    return {
        "id": allocation.id,
        "status": allocation.status,
        "source_selector": _build_source_selector(
            source_owner,
            allocation.source_pool.point_type,
            allocation.source_pool.tag.slug if allocation.source_pool.tag else None,
        ),
        "total_amount": allocation.total_amount,
        "project_scope": allocation.project_scope,
        "user_scope": allocation.user_scope,
        "start_month": allocation.start_month.isoformat(),
        "end_month": allocation.end_month.isoformat(),
        "adjustment_ratio": float(allocation.adjustment_ratio),
        "individual_adjustments": allocation.individual_adjustments,
        "contribution_data": allocation.contribution_data,
        "total_recipients": allocation.total_recipients,
        "registered_recipients": allocation.registered_recipients,
        "unregistered_recipients": allocation.unregistered_recipients,
        "created_at": allocation.created_at.isoformat(),
        "executed_at": allocation.executed_at.isoformat()
        if allocation.executed_at
        else None,
        "pending_grants": [
            {
                "id": grant.id,
                "platform": grant.platform,
                "actor_id": grant.actor_id,
                "actor_login": grant.actor_login,
                "email": grant.email,
                "amount": grant.amount,
                "point_type": grant.point_type,
                "tag": (
                    {
                        "slug": grant.tag.slug,
                        "name": grant.tag.name,
                    }
                    if grant.tag
                    else None
                ),
                "is_claimed": grant.is_claimed,
                "claimed_at": grant.claimed_at.isoformat()
                if grant.claimed_at
                else None,
                "expires_at": grant.expires_at.isoformat()
                if grant.expires_at
                else None,
            }
            for grant in pending_grants
        ],
    }


def _parse_request_data(request) -> tuple[dict, object | None]:
    content_type = request.content_type or ""
    if content_type.startswith("application/json"):
        try:
            data = json.loads(request.body or "{}")
        except JSONDecodeError as exc:
            raise ApiError(
                "invalid_json", 400, "The request body must be valid JSON."
            ) from exc
        if not isinstance(data, dict):
            raise ApiError(
                "invalid_json", 400, "The request body must be a JSON object."
            )
        return data, None
    return request.POST.dict(), request.FILES.get("invoice_file")


def _get_org_membership(
    user, organization: Organization
) -> OrganizationMembership | None:
    return OrganizationMembership.objects.filter(
        user=user,
        organization=organization,
    ).first()


def _get_org_member_or_error(
    user, slug: str
) -> tuple[Organization, OrganizationMembership]:
    organization = get_object_or_404(Organization, slug=slug)
    membership = _get_org_membership(user, organization)
    if membership is None:
        raise ApiError(
            "forbidden",
            403,
            "You are not a member of this organization.",
        )
    return organization, membership


def _get_org_admin_or_error(
    user, slug: str
) -> tuple[Organization, OrganizationMembership]:
    organization, membership = _get_org_member_or_error(user, slug)
    if not membership.is_admin_or_owner():
        raise ApiError(
            "forbidden",
            403,
            "You do not have permission to manage this organization's points.",
        )
    return organization, membership


def _validate_source_selector(payload: SourceSelectorSchema) -> None:
    if payload.owner_type not in {"user", "organization"}:
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            _validation_detail(
                "source_selector.owner_type",
                'owner_type must be "user" or "organization".',
            ),
        )
    if payload.point_type not in {PointType.CASH, PointType.GIFT}:
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            _validation_detail(
                "source_selector.point_type",
                'point_type must be "cash" or "gift".',
            ),
        )
    if payload.point_type == PointType.CASH and payload.tag_slug:
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            _validation_detail(
                "source_selector.tag_slug",
                "Cash point pools cannot be filtered by tag.",
            ),
        )
    if payload.owner_type == "organization" and not payload.owner_slug:
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            _validation_detail(
                "source_selector.owner_slug",
                "owner_slug is required when owner_type is organization.",
            ),
        )


def _resolve_source_pool(
    request_user, selector: SourceSelectorSchema
) -> tuple[PointSource, int]:
    _validate_source_selector(selector)

    if selector.owner_type == "user":
        owner = request_user
    else:
        organization, _membership = _get_org_admin_or_error(
            request_user, selector.owner_slug
        )
        owner = organization

    wallet = services.get_wallet_or_none(owner)
    if wallet is None:
        raise ApiError(
            "not_found",
            404,
            "The requested point pool was not found.",
        )
    sources = PointSource.objects.filter(
        wallet=wallet,
        point_type=selector.point_type,
        remaining_amount__gt=0,
    ).select_related("wallet__content_type", "tag")

    if selector.point_type == PointType.GIFT:
        if selector.tag_slug is None:
            sources = sources.filter(tag__isnull=True)
        else:
            sources = sources.filter(tag__slug=selector.tag_slug)

    representative_source = sources.order_by("created_at", "id").first()
    available_balance = sum(source.remaining_amount for source in sources)

    if representative_source is None or available_balance <= 0:
        raise ApiError(
            "not_found",
            404,
            "The requested point pool was not found.",
        )

    return representative_source, available_balance


def _validate_allocation_scope(
    name: str, scope: AllocationScopeSchema | None, *, required: bool
) -> dict | None:
    if scope is None:
        if required:
            raise ApiError(
                "validation_error",
                422,
                "Request validation failed.",
                _validation_detail(name, f"{name} is required."),
            )
        return None

    if not scope.tags:
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            _validation_detail(f"{name}.tags", "Provide at least one tag."),
        )
    if scope.operation not in VALID_TAG_OPERATIONS:
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            _validation_detail(
                f"{name}.operation",
                'Operation must be one of "AND", "OR", "NOT", or "XOR".',
            ),
        )
    return scope.model_dump()


def _validate_preview_request(payload: AllocationPreviewRequestSchema) -> None:
    if payload.start_month > payload.end_month:
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            _validation_detail(
                "end_month",
                "end_month must be greater than or equal to start_month.",
            ),
        )
    _validate_allocation_scope("project_scope", payload.project_scope, required=True)
    _validate_allocation_scope("user_scope", payload.user_scope, required=False)


def _validate_execute_request(payload: AllocationExecuteRequestSchema) -> None:
    if payload.total_amount <= 0:
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            _validation_detail(
                "total_amount", "total_amount must be greater than zero."
            ),
        )
    if payload.start_month > payload.end_month:
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            _validation_detail(
                "end_month",
                "end_month must be greater than or equal to start_month.",
            ),
        )
    if not payload.allocations:
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            _validation_detail("allocations", "allocations must not be empty."),
        )
    if any(item.amount < 0 for item in payload.allocations):
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            _validation_detail(
                "allocations.amount",
                "Each allocation amount must not be negative.",
            ),
        )
    computed_total = sum(item.amount for item in payload.allocations)
    if computed_total != payload.total_amount:
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            _validation_detail(
                "total_amount",
                f"Sum of allocation amounts ({computed_total}) does not match total_amount ({payload.total_amount}).",
            ),
        )
    _validate_allocation_scope("project_scope", payload.project_scope, required=True)
    _validate_allocation_scope("user_scope", payload.user_scope, required=False)


def _build_unsaved_preview_allocation(
    payload: AllocationPreviewRequestSchema, source_pool: PointSource
) -> PointAllocation:
    return PointAllocation(
        source_pool=source_pool,
        total_amount=0,
        project_scope=payload.project_scope.model_dump(),
        user_scope=payload.user_scope.model_dump() if payload.user_scope else None,
        start_month=payload.start_month,
        end_month=payload.end_month,
        adjustment_ratio=Decimal("1.0"),
        individual_adjustments={},
    )


def _normalize_preview_items(items: list[dict]) -> list[dict]:
    normalized = []
    for item in items:
        current = item.copy()
        contribution_score = current.get("contribution_score")
        if isinstance(contribution_score, Decimal):
            current["contribution_score"] = float(contribution_score)
        normalized.append(current)
    return normalized


def _raise_points_service_error(message: str) -> None:
    normalized = message.strip()
    exact_patterns = [
        (
            re.compile(
                r"^现金积分不足：需要 (?P<required>\d+)，可用 (?P<available>\d+)$"
            ),
            lambda m: (
                "Not enough cash points. "
                f"Required: {m['required']}, available: {m['available']}."
            ),
        ),
        (
            re.compile(r"^提现申请不存在: (?P<withdrawal_id>\d+)$"),
            lambda m: f"Withdrawal request {m['withdrawal_id']} was not found.",
        ),
        (
            re.compile(r"^只能取消待审核的提现申请，当前状态: (?P<status>.+)$"),
            lambda m: (
                "Only pending withdrawal requests can be cancelled. "
                f"Current status: {m['status']}."
            ),
        ),
        (
            re.compile(r"^提现申请状态无效: (?P<status>.+)$"),
            lambda m: f"Invalid withdrawal request status: {m['status']}.",
        ),
    ]
    for pattern, formatter in exact_patterns:
        match = pattern.match(normalized)
        if match:
            raise ApiError("operation_failed", 409, formatter(match.groupdict()))

    message_map = {
        "您有待处理的提现申请，请等待处理完成后再申请": (
            "pending_withdrawal_exists",
            409,
            "A pending withdrawal request already exists for this wallet.",
        ),
        "您没有权限取消此提现申请": (
            "forbidden",
            403,
            "You do not have permission to cancel this withdrawal request.",
        ),
        "提现金额必须大于 0": (
            "validation_error",
            422,
            "The withdrawal amount must be greater than zero.",
        ),
    }
    mapped = message_map.get(normalized)
    if mapped:
        code, status_code, message = mapped
        raise ApiError(code, status_code, message)
    raise ApiError(
        "operation_failed",
        409,
        "The requested points operation could not be completed.",
    )


def _wallet_response(owner) -> dict:
    wallet = services.get_wallet_or_none(owner)
    recent_transactions = []
    wallet_id = None
    if wallet is not None:
        wallet_id = wallet.id
        recent_transactions = list(
            wallet.transactions.select_related("tag", "created_by").order_by(
                "-created_at"
            )[:10]
        )
    return {
        "balance": services.get_detailed_balance_or_zero(owner),
        "wallet_id": wallet_id,
        "recent_transactions": [
            _serialize_transaction(txn) for txn in recent_transactions
        ],
    }


@router.get("/me/wallet", response={200: dict, 401: ErrorResponseSchema})
def current_user_wallet_endpoint(request):
    """Return the current user's wallet summary."""
    return _wallet_response(request.auth)


@router.get("/me/transactions")
def current_user_transactions_endpoint(
    request,
    point_type: str = "",
    transaction_type: str = "",
    page: int = 1,
    page_size: int = 20,
):
    """List the current user's points transactions."""
    wallet = services.get_wallet_or_none(request.auth)
    transactions = PointTransaction.objects.none()
    if wallet is not None:
        transactions = wallet.transactions.select_related("tag", "created_by").order_by(
            "-created_at"
        )
    if point_type:
        transactions = transactions.filter(point_type=point_type)
    if transaction_type:
        transactions = transactions.filter(transaction_type=transaction_type)
    page_obj = paginate_queryset(
        transactions, page=page, page_size=page_size, max_page_size=100
    )
    response = build_paginated_response(
        page_obj,
        [_serialize_transaction(txn) for txn in page_obj.object_list],
    )
    response["filters"] = {
        "point_type": point_type,
        "transaction_type": transaction_type,
    }
    return response


@router.get("/me/withdrawals")
def current_user_withdrawals_endpoint(request, page: int = 1, page_size: int = 20):
    """List the current user's withdrawal requests."""
    wallet = services.get_wallet_or_none(request.auth)
    withdrawals = (
        wallet.withdrawals.select_related("withdrawal_account").order_by("-created_at")
        if wallet is not None
        else WithdrawalRequest.objects.none()
    )
    page_obj = paginate_queryset(
        withdrawals, page=page, page_size=page_size, max_page_size=100
    )
    return build_paginated_response(
        page_obj,
        [_serialize_withdrawal(item) for item in page_obj.object_list],
    )


@router.post(
    "/me/withdrawals",
    response={
        201: dict,
        401: ErrorResponseSchema,
        409: ErrorResponseSchema,
        422: ErrorResponseSchema,
    },
)
def current_user_withdrawal_create_endpoint(request):
    """Create a withdrawal request for the current user."""
    data, invoice_file = _parse_request_data(request)

    # 新流程：通过 withdrawal_account_id + amount 提交
    withdrawal_account_id = data.get("withdrawal_account_id")
    if withdrawal_account_id is not None:
        try:
            amount = int(data.get("amount", 0))
        except (TypeError, ValueError):
            raise ApiError("validation_error", 422, "amount must be a valid integer.")
        if amount < services.MINIMUM_WITHDRAWAL_AMOUNT:
            raise ApiError(
                "validation_error",
                422,
                f"Minimum withdrawal amount is {services.MINIMUM_WITHDRAWAL_AMOUNT} points.",
            )
        try:
            withdrawal = services.create_withdrawal_request(
                owner=request.auth,
                amount=amount,
                invoice_file=invoice_file,
                withdrawal_account_id=int(withdrawal_account_id),
            )
        except ValueError as exc:
            raise ApiError("validation_error", 422, str(exc))
        except (services.InsufficientPointsError, services.WithdrawalError) as exc:
            _raise_points_service_error(str(exc))
            raise AssertionError("unreachable")
        return 201, _serialize_withdrawal(withdrawal)

    # 旧流程：直接传参方式（向后兼容）
    form = WithdrawalRequestForm(request.auth, data=data, files=request.FILES or None)
    if not validate_form(form):
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            form_error_detail(form),
        )
    try:
        withdrawal = services.create_withdrawal_request(
            owner=request.auth,
            amount=form.cleaned_data["amount"],
            real_name=form.cleaned_data["real_name"],
            phone=form.cleaned_data["phone"],
            id_card=form.cleaned_data["id_card"],
            bank_name=form.cleaned_data["bank_name"],
            bank_account=form.cleaned_data["bank_account"],
            invoice_file=invoice_file or form.cleaned_data.get("invoice_file"),
        )
    except (services.InsufficientPointsError, services.WithdrawalError) as exc:
        _raise_points_service_error(str(exc))
        raise AssertionError("unreachable")
    except ValueError as exc:
        raise ApiError("validation_error", 422, str(exc))
    return 201, _serialize_withdrawal(withdrawal)


@router.post("/me/withdrawals/{withdrawal_id}/cancel")
def current_user_withdrawal_cancel_endpoint(request, withdrawal_id: int):
    """Cancel a pending withdrawal request for the current user."""
    try:
        withdrawal = services.cancel_withdrawal(withdrawal_id, request.auth)
    except services.WithdrawalError as exc:
        _raise_points_service_error(str(exc))
        raise AssertionError("unreachable")
    return _serialize_withdrawal(withdrawal)


@router.get(
    "/organizations/{slug}/wallet",
    response={
        200: dict,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
    },
)
def organization_wallet_endpoint(request, slug: str):
    """Return wallet summary for an organization the current user belongs to."""
    organization, membership = _get_org_member_or_error(request.auth, slug)
    response = _wallet_response(organization)
    response["organization"] = {
        "id": organization.id,
        "slug": organization.slug,
        "name": organization.name,
    }
    response["membership"] = {
        "id": membership.id,
        "role": membership.role,
        "is_admin_or_owner": membership.is_admin_or_owner(),
    }
    return response


@router.get("/organizations/{slug}/transactions")
def organization_transactions_endpoint(
    request,
    slug: str,
    point_type: str = "",
    transaction_type: str = "",
    page: int = 1,
    page_size: int = 20,
):
    """List organization transactions for current members."""
    organization, membership = _get_org_member_or_error(request.auth, slug)
    wallet = services.get_wallet_or_none(organization)
    transactions = PointTransaction.objects.none()
    if wallet is not None:
        transactions = wallet.transactions.select_related("tag", "created_by").order_by(
            "-created_at"
        )
    if point_type:
        transactions = transactions.filter(point_type=point_type)
    if transaction_type:
        transactions = transactions.filter(transaction_type=transaction_type)
    page_obj = paginate_queryset(
        transactions, page=page, page_size=page_size, max_page_size=100
    )
    response = build_paginated_response(
        page_obj,
        [_serialize_transaction(txn) for txn in page_obj.object_list],
    )
    response["organization"] = {"slug": organization.slug, "name": organization.name}
    response["membership"] = {
        "id": membership.id,
        "role": membership.role,
        "is_admin_or_owner": membership.is_admin_or_owner(),
    }
    response["filters"] = {
        "point_type": point_type,
        "transaction_type": transaction_type,
    }
    return response


@router.get("/organizations/{slug}/withdrawals")
def organization_withdrawals_endpoint(
    request, slug: str, page: int = 1, page_size: int = 20
):
    """List withdrawal requests for an organization."""
    organization, membership = _get_org_admin_or_error(request.auth, slug)
    wallet = services.get_wallet_or_none(organization)
    page_obj = paginate_queryset(
        wallet.withdrawals.order_by("-created_at")
        if wallet is not None
        else WithdrawalRequest.objects.none(),
        page=page,
        page_size=page_size,
        max_page_size=100,
    )
    response = build_paginated_response(
        page_obj,
        [_serialize_withdrawal(item) for item in page_obj.object_list],
    )
    response["organization"] = {"slug": organization.slug, "name": organization.name}
    response["membership"] = {
        "id": membership.id,
        "role": membership.role,
        "is_admin_or_owner": membership.is_admin_or_owner(),
    }
    return response


@router.post(
    "/organizations/{slug}/withdrawals",
    response={
        201: dict,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        404: ErrorResponseSchema,
        409: ErrorResponseSchema,
        422: ErrorResponseSchema,
    },
)
def organization_withdrawal_create_endpoint(request, slug: str):
    """Create a withdrawal request for an organization."""
    organization, _membership = _get_org_admin_or_error(request.auth, slug)
    data, invoice_file = _parse_request_data(request)
    form = WithdrawalRequestForm(organization, data=data, files=request.FILES or None)
    if not validate_form(form):
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            form_error_detail(form),
        )
    try:
        withdrawal = services.create_withdrawal_request(
            owner=organization,
            amount=form.cleaned_data["amount"],
            real_name=form.cleaned_data["real_name"],
            phone=form.cleaned_data["phone"],
            id_card=form.cleaned_data["id_card"],
            bank_name=form.cleaned_data["bank_name"],
            bank_account=form.cleaned_data["bank_account"],
            invoice_file=invoice_file or form.cleaned_data.get("invoice_file"),
        )
    except (services.InsufficientPointsError, services.WithdrawalError) as exc:
        _raise_points_service_error(str(exc))
        raise AssertionError("unreachable")
    except ValueError as exc:
        raise ApiError("validation_error", 422, str(exc))
    return 201, _serialize_withdrawal(withdrawal)


@router.post("/organizations/{slug}/withdrawals/{withdrawal_id}/cancel")
def organization_withdrawal_cancel_endpoint(request, slug: str, withdrawal_id: int):
    """Cancel a pending organization withdrawal request."""
    organization, _membership = _get_org_admin_or_error(request.auth, slug)
    wallet = services.get_wallet_or_none(organization)
    if (
        wallet is None
        or not WithdrawalRequest.objects.filter(
            id=withdrawal_id,
            wallet=wallet,
        ).exists()
    ):
        raise ApiError("not_found", 404, "The requested withdrawal was not found.")
    try:
        withdrawal = services.cancel_withdrawal(withdrawal_id, request.auth)
    except services.WithdrawalError as exc:
        _raise_points_service_error(str(exc))
        raise AssertionError("unreachable")
    return _serialize_withdrawal(withdrawal)


@router.get("/pools")
def point_pools_endpoint(request):
    """List aggregated point pools available to the current user."""
    owners = [request.auth]
    owners.extend(
        membership.organization
        for membership in request.auth.organization_memberships.filter(
            role__in=["owner", "admin"]
        ).select_related("organization")
    )

    items = []
    for owner in owners:
        wallet = services.get_wallet_or_none(owner)
        if wallet is None:
            continue
        rows = (
            PointSource.objects.filter(wallet=wallet, remaining_amount__gt=0)
            .values("point_type", "tag__slug", "tag__name")
            .annotate(available_balance=Sum("remaining_amount"), first_id=Min("id"))
            .order_by("point_type", "tag__slug")
        )
        for row in rows:
            items.append(
                _serialize_pool(
                    owner,
                    row["point_type"],
                    row["tag__slug"],
                    row["tag__name"],
                    row["available_balance"],
                )
            )
    return {"items": items}


@router.get("/tags")
def point_tags_endpoint(
    request, tag_type: str | None = None, official: bool | None = None
):
    """List point tags."""
    tags = Tag.objects.all().order_by("name")
    if tag_type:
        tags = tags.filter(tag_type=tag_type)
    if official is not None:
        tags = tags.filter(is_official=official)
    return {
        "items": [
            {
                "id": tag.id,
                "slug": tag.slug,
                "name": tag.name,
                "description": tag.description,
                "tag_type": tag.tag_type,
                "entity_identifier": tag.entity_identifier,
                "is_official": tag.is_official,
                "created_at": tag.created_at.isoformat(),
            }
            for tag in tags
        ]
    }


@router.get("/tags/search")
def point_tag_search_endpoint(request, q: str = ""):
    """Search external tags for allocation workflows."""
    keyword = q.strip()
    if not keyword:
        return {"items": []}
    try:
        from chdb import services as chdb_services

        return {"items": chdb_services.search_tags(keyword)}
    except Exception as exc:  # pragma: no cover - external dependency
        raise ApiError(
            "tag_search_unavailable",
            503,
            "Tag search is currently unavailable.",
        ) from exc


@router.post(
    "/allocations/preview",
    response={
        200: dict,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        409: ErrorResponseSchema,
        422: ErrorResponseSchema,
        503: ErrorResponseSchema,
    },
)
def allocation_preview_endpoint(request, payload: AllocationPreviewRequestSchema):
    """Preview a points allocation run without executing it."""
    _validate_preview_request(payload)
    source_pool, available_balance = _resolve_source_pool(
        request.auth, payload.source_selector
    )

    allocation = _build_unsaved_preview_allocation(payload, source_pool)
    try:
        preview = _normalize_preview_items(
            AllocationService.preview_allocation(allocation)
        )
    except ContributionDataUnavailableError as exc:
        raise ApiError(
            "contribution_data_unavailable",
            503,
            "Contribution data is currently unavailable.",
        ) from exc
    return {
        "source_selector": payload.source_selector.model_dump(),
        "available_balance": available_balance,
        "contribution_to_points_ratio": AllocationService.CONTRIBUTION_TO_POINTS_RATIO,
        "total_recipients": len(preview),
        "preview": preview,
    }


@router.post(
    "/allocations",
    response={
        201: dict,
        401: ErrorResponseSchema,
        403: ErrorResponseSchema,
        409: ErrorResponseSchema,
        422: ErrorResponseSchema,
        503: ErrorResponseSchema,
    },
)
def allocation_execute_endpoint(request, payload: AllocationExecuteRequestSchema):
    """Create and execute a points allocation."""
    _validate_execute_request(payload)
    source_pool, available_balance = _resolve_source_pool(
        request.auth, payload.source_selector
    )
    if payload.total_amount > available_balance:
        raise ApiError(
            "insufficient_points",
            409,
            "The selected point pool does not have enough balance for this allocation.",
            {"available_balance": available_balance},
        )

    # initiator_type/initiator_id 同时起“发起者”与“执行操作者”作用,
    # 始终记录当前登录用户(request.auth), 等价于 created_by / operator.
    initiator_type = ContentType.objects.get_for_model(request.auth)
    # adjustment_ratio 语义: 实际发放积分总量 / 理论应发放积分总量,
    # 理论应发放 = sum(floor(contribution_score *
    # AllocationService.CONTRIBUTION_TO_POINTS_RATIO)).
    # 由前端依照该定义计算后传入, 后端原样持久化以用于详情展示.
    allocation = PointAllocation.objects.create(
        initiator_type=initiator_type,
        initiator_id=request.auth.id,
        source_pool=source_pool,
        total_amount=payload.total_amount,
        project_scope=payload.project_scope.model_dump(),
        user_scope=payload.user_scope.model_dump() if payload.user_scope else None,
        start_month=payload.start_month,
        end_month=payload.end_month,
        adjustment_ratio=Decimal(str(payload.adjustment_ratio)),
        individual_adjustments={},
    )

    allocations_data = [item.model_dump() for item in payload.allocations]
    try:
        result = AllocationService.execute_allocation(allocation, allocations_data)
    except (services.InsufficientPointsError, RuntimeError, ValueError) as exc:
        raise ApiError(
            "allocation_failed",
            409,
            "The allocation could not be executed.",
        ) from exc

    allocation.refresh_from_db()
    return 201, {"result": result, "allocation": _serialize_allocation(allocation)}


def _user_can_access_allocation(user, allocation: PointAllocation) -> bool:
    if (
        allocation.initiator_type == ContentType.objects.get_for_model(user)
        and allocation.initiator_id == user.id
    ):
        return True
    owner = allocation.source_pool.wallet.owner
    if isinstance(owner, User):
        return owner.id == user.id
    if isinstance(owner, Organization):
        return OrganizationMembership.objects.filter(
            user=user,
            organization=owner,
            role__in=[
                OrganizationMembership.Role.OWNER,
                OrganizationMembership.Role.ADMIN,
            ],
        ).exists()
    return False


def _user_is_allocation_beneficiary(user, allocation: PointAllocation) -> bool:
    """
    判断 user 是否为该次分配的受益人.

    依据当前用户钱包中是否存在 reference_id=allocation_{id} 的 EARN 类型交易,
    覆盖以下两种场景:
    1. 分配执行时即被直接发放积分的已注册受益人
    2. 分配生成的待领取记录被该用户后续认领后发放的积分
    """
    user_ct = ContentType.objects.get_for_model(user)
    return PointTransaction.objects.filter(
        wallet__content_type=user_ct,
        wallet__object_id=user.id,
        transaction_type=TransactionType.EARN,
        reference_id=f"allocation_{allocation.id}",
    ).exists()


def _serialize_allocation_summary(allocation: PointAllocation) -> dict:
    """
    返回受益人可见的有限分配信息.

    仅暴露与受益人自身权益相关的元数据:
    - 积分池来源 (个人/组织、名称、积分类型、标签)
    - 项目范围/用户范围标签
    - 时间区间
    - 全局调整比例
    - 状态与执行时间

    刻意排除以下敏感字段, 避免泄露其他受益人或资金细节:
    - total_amount (本次分配总额)
    - contribution_data (其他开发者贡献度与分配明细)
    - pending_grants (待领取列表)
    - total_recipients / registered_recipients / unregistered_recipients
    """
    source_owner = allocation.source_pool.wallet.owner
    source_tag = allocation.source_pool.tag
    is_org = isinstance(source_owner, Organization)
    return {
        "id": allocation.id,
        "status": allocation.status,
        "source_pool": {
            "owner_type": "organization" if is_org else "user",
            "owner_slug": source_owner.slug if is_org else None,
            "owner_name": source_owner.name if is_org else source_owner.username,
            "point_type": allocation.source_pool.point_type,
            "tag": (
                {"slug": source_tag.slug, "name": source_tag.name}
                if source_tag
                else None
            ),
        },
        "project_scope": allocation.project_scope,
        "user_scope": allocation.user_scope,
        "start_month": allocation.start_month.isoformat(),
        "end_month": allocation.end_month.isoformat(),
        "adjustment_ratio": float(allocation.adjustment_ratio),
        "created_at": allocation.created_at.isoformat(),
        "executed_at": allocation.executed_at.isoformat()
        if allocation.executed_at
        else None,
    }


@router.get("/allocations/{allocation_id}")
def allocation_detail_endpoint(request, allocation_id: int):
    """Return a single allocation record."""
    allocation = get_object_or_404(
        PointAllocation.objects.select_related(
            "source_pool__wallet__content_type", "source_pool__tag"
        ),
        id=allocation_id,
    )
    if not _user_can_access_allocation(request.auth, allocation):
        raise ApiError(
            "forbidden",
            403,
            "You do not have permission to view this allocation.",
        )
    return _serialize_allocation(allocation)


@router.get("/allocations/{allocation_id}/summary")
def allocation_summary_endpoint(request, allocation_id: int):
    """
    Return limited allocation info visible to beneficiaries.

    访问条件 (满足任一):
    1. 该用户为分配发起者 / 积分池所有者 / 组织 OWNER|ADMIN (复用 _user_can_access_allocation)
    2. 该用户为该次分配的受益人 (拥有 reference_id=allocation_{id} 的 EARN 交易)

    返回字段刻意精简, 避免受益人看到他人收入或本次分配总额.
    """
    allocation = get_object_or_404(
        PointAllocation.objects.select_related(
            "source_pool__wallet__content_type", "source_pool__tag"
        ),
        id=allocation_id,
    )
    if not (
        _user_can_access_allocation(request.auth, allocation)
        or _user_is_allocation_beneficiary(request.auth, allocation)
    ):
        raise ApiError(
            "forbidden",
            403,
            "You do not have permission to view this allocation.",
        )
    return _serialize_allocation_summary(allocation)
