# ruff: noqa: D101, EM101
"""Authenticated user endpoints for API v1."""

from __future__ import annotations

from datetime import date, timedelta

from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema

from config.api_common import (
    ApiError,
    ErrorResponseSchema,
    form_error_detail,
    validate_form,
)
from points import services as points_services
from shenbianyun.models import SignedUser
from shenbianyun.services import SIGN_STATE_SIGNED

from .api_serializers import (
    serialize_account_merge_request,
    serialize_education,
    serialize_profile,
    serialize_shipping_address,
    serialize_work_experience,
)
from .api_v1 import jwt_bearer_auth
from .forms import (
    AccountMergeRequestForm,
    EducationForm,
    ProfileForm,
    ShippingAddressForm,
    WorkExperienceForm,
)
from .models import (
    AccountMergeRequest,
    Education,
    ShippingAddress,
    UserProfile,
    WithdrawalAccount,
    WorkExperience,
)
from .services import AccountMergeError, perform_merge
from .services.masking import mask_card, mask_name
from .views import (
    _build_asset_snapshot,
    _expire_request_if_needed,
    _generate_unique_token,
    _notify_merge_result,
    _send_merge_request_message,
)

router = Router(tags=["me"], auth=jwt_bearer_auth)

PROFILE_FIELDS = [
    "bio",
    "birth_date",
    "github_url",
    "homepage_url",
    "blog_url",
    "twitter_url",
    "linkedin_url",
    "company",
    "location",
]
WORK_FIELDS = ["company_name", "title", "start_date", "end_date", "description"]
EDUCATION_FIELDS = [
    "institution_name",
    "degree",
    "field_of_study",
    "start_date",
    "end_date",
]
ADDRESS_FIELDS = [
    "receiver_name",
    "phone",
    "province",
    "city",
    "district",
    "address",
    "is_default",
]


class ProfileUpdateSchema(Schema):
    bio: str | None = None
    birth_date: date | None = None
    github_url: str | None = None
    homepage_url: str | None = None
    blog_url: str | None = None
    twitter_url: str | None = None
    linkedin_url: str | None = None
    company: str | None = None
    location: str | None = None


class WorkExperienceCreateSchema(Schema):
    company_name: str
    title: str
    start_date: date
    end_date: date | None = None
    description: str = ""


class WorkExperienceUpdateSchema(Schema):
    company_name: str | None = None
    title: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = None


class EducationCreateSchema(Schema):
    institution_name: str
    degree: str = ""
    field_of_study: str
    start_date: date
    end_date: date | None = None


class EducationUpdateSchema(Schema):
    institution_name: str | None = None
    degree: str | None = None
    field_of_study: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class ShippingAddressCreateSchema(Schema):
    receiver_name: str
    phone: str
    province: str
    city: str
    district: str
    address: str
    is_default: bool = False


class ShippingAddressUpdateSchema(Schema):
    receiver_name: str | None = None
    phone: str | None = None
    province: str | None = None
    city: str | None = None
    district: str | None = None
    address: str | None = None
    is_default: bool | None = None


class WithdrawalAccountCreateSchema(Schema):
    account_type: str
    real_name: str
    id_card: str = ""
    phone: str = ""
    bank_card: str = ""
    currency: str = ""
    swift_account: str = ""


class AccountMergeCreateSchema(Schema):
    target_username: str | None = None
    target_email: str | None = None


def _normalize_form_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _merged_form_data(instance, fields: list[str], updates: dict) -> dict:
    data = {}
    for field in fields:
        if field in updates:
            data[field] = _normalize_form_value(updates[field])
        else:
            data[field] = _normalize_form_value(getattr(instance, field))
    return data


def _get_profile(user):
    return UserProfile.objects.get_or_create(user=user)[0]


def _get_profile_or_none(user):
    return UserProfile.objects.filter(user=user).first()


def _profile_payload(profile):
    if profile is None:
        return {
            "bio": "",
            "birth_date": None,
            "github_url": "",
            "homepage_url": "",
            "blog_url": "",
            "twitter_url": "",
            "linkedin_url": "",
            "company": "",
            "location": "",
        }
    return serialize_profile(profile)


def _get_reviewable_merge_request(user, token: str) -> AccountMergeRequest:
    return get_object_or_404(
        AccountMergeRequest.objects.select_related("source_user", "target_user"),
        approve_token=token,
        target_user=user,
    )


@router.get("/profile", response=dict)
def current_profile_endpoint(request):
    """Return the authenticated user's profile summary."""
    profile = _get_profile_or_none(request.auth)
    balance = points_services.get_detailed_balance_or_zero(request.auth)
    return {
        "user": {
            "id": request.auth.id,
            "username": request.auth.username,
            "email": request.auth.email,
        },
        "profile": _profile_payload(profile),
        "balance": balance,
    }


@router.patch("/profile", response={200: dict, 422: ErrorResponseSchema})
def update_profile_endpoint(request, payload: ProfileUpdateSchema):
    """Patch the authenticated user's profile."""
    profile = _get_profile(request.auth)
    updates = payload.model_dump(exclude_unset=True)
    form = ProfileForm(
        _merged_form_data(profile, PROFILE_FIELDS, updates), instance=profile
    )
    if not validate_form(form):
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            form_error_detail(form),
        )

    form.save()
    profile.refresh_from_db()
    return {"profile": serialize_profile(profile)}


@router.get("/work-experiences", response=dict)
def work_experience_list_endpoint(request):
    """List the authenticated user's work experiences."""
    profile = _get_profile_or_none(request.auth)
    return {
        "items": [
            serialize_work_experience(item)
            for item in (profile.work_experiences.all() if profile else [])
        ]
    }


@router.post(
    "/work-experiences",
    response={201: dict, 422: ErrorResponseSchema},
)
def work_experience_create_endpoint(request, payload: WorkExperienceCreateSchema):
    """Create a work experience row."""
    profile = _get_profile(request.auth)
    form = WorkExperienceForm(payload.model_dump())
    if not validate_form(form):
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            form_error_detail(form),
        )

    experience = form.save(commit=False)
    experience.profile = profile
    experience.save()
    return 201, serialize_work_experience(experience)


@router.patch(
    "/work-experiences/{experience_id}",
    response={200: dict, 404: ErrorResponseSchema, 422: ErrorResponseSchema},
)
def work_experience_update_endpoint(
    request,
    experience_id: int,
    payload: WorkExperienceUpdateSchema,
):
    """Update a work experience row."""
    profile = _get_profile(request.auth)
    experience = get_object_or_404(WorkExperience, id=experience_id, profile=profile)
    updates = payload.model_dump(exclude_unset=True)
    form = WorkExperienceForm(
        _merged_form_data(experience, WORK_FIELDS, updates),
        instance=experience,
    )
    if not validate_form(form):
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            form_error_detail(form),
        )

    form.save()
    experience.refresh_from_db()
    return serialize_work_experience(experience)


@router.delete(
    "/work-experiences/{experience_id}",
    response={204: None, 404: ErrorResponseSchema},
)
def work_experience_delete_endpoint(request, experience_id: int):
    """Delete a work experience row."""
    profile = _get_profile(request.auth)
    experience = get_object_or_404(WorkExperience, id=experience_id, profile=profile)
    experience.delete()
    return 204, None


@router.get("/educations", response=dict)
def education_list_endpoint(request):
    """List the authenticated user's education rows."""
    profile = _get_profile_or_none(request.auth)
    return {
        "items": [
            serialize_education(item)
            for item in (profile.educations.all() if profile else [])
        ]
    }


@router.post(
    "/educations",
    response={201: dict, 422: ErrorResponseSchema},
)
def education_create_endpoint(request, payload: EducationCreateSchema):
    """Create an education row."""
    profile = _get_profile(request.auth)
    form = EducationForm(payload.model_dump())
    if not validate_form(form):
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            form_error_detail(form),
        )

    education = form.save(commit=False)
    education.profile = profile
    education.save()
    return 201, serialize_education(education)


@router.patch(
    "/educations/{education_id}",
    response={200: dict, 404: ErrorResponseSchema, 422: ErrorResponseSchema},
)
def education_update_endpoint(
    request, education_id: int, payload: EducationUpdateSchema
):
    """Update an education row."""
    profile = _get_profile(request.auth)
    education = get_object_or_404(Education, id=education_id, profile=profile)
    updates = payload.model_dump(exclude_unset=True)
    form = EducationForm(
        _merged_form_data(education, EDUCATION_FIELDS, updates),
        instance=education,
    )
    if not validate_form(form):
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            form_error_detail(form),
        )

    form.save()
    education.refresh_from_db()
    return serialize_education(education)


@router.delete(
    "/educations/{education_id}",
    response={204: None, 404: ErrorResponseSchema},
)
def education_delete_endpoint(request, education_id: int):
    """Delete an education row."""
    profile = _get_profile(request.auth)
    education = get_object_or_404(Education, id=education_id, profile=profile)
    education.delete()
    return 204, None


@router.get("/shipping-addresses", response=dict)
def shipping_address_list_endpoint(request):
    """List the authenticated user's shipping addresses."""
    return {
        "items": [
            serialize_shipping_address(address)
            for address in ShippingAddress.objects.filter(user=request.auth)
        ]
    }


@router.post(
    "/shipping-addresses",
    response={201: dict, 422: ErrorResponseSchema},
)
def shipping_address_create_endpoint(request, payload: ShippingAddressCreateSchema):
    """Create a shipping address."""
    form = ShippingAddressForm(payload.model_dump())
    if not validate_form(form):
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            form_error_detail(form),
        )

    address = form.save(commit=False)
    address.user = request.auth
    address.save()
    return 201, serialize_shipping_address(address)


@router.patch(
    "/shipping-addresses/{address_id}",
    response={200: dict, 404: ErrorResponseSchema, 422: ErrorResponseSchema},
)
def shipping_address_update_endpoint(
    request,
    address_id: int,
    payload: ShippingAddressUpdateSchema,
):
    """Update a shipping address."""
    address = get_object_or_404(ShippingAddress, id=address_id, user=request.auth)
    updates = payload.model_dump(exclude_unset=True)
    form = ShippingAddressForm(
        _merged_form_data(address, ADDRESS_FIELDS, updates),
        instance=address,
    )
    if not validate_form(form):
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            form_error_detail(form),
        )

    form.save()
    address.refresh_from_db()
    return serialize_shipping_address(address)


@router.delete(
    "/shipping-addresses/{address_id}",
    response={204: None, 404: ErrorResponseSchema},
)
def shipping_address_delete_endpoint(request, address_id: int):
    """Delete a shipping address."""
    address = get_object_or_404(ShippingAddress, id=address_id, user=request.auth)
    address.delete()
    return 204, None


@router.post(
    "/shipping-addresses/{address_id}/set-default",
    response={200: dict, 404: ErrorResponseSchema},
)
def shipping_address_set_default_endpoint(request, address_id: int):
    """Set a shipping address as the default address."""
    address = get_object_or_404(ShippingAddress, id=address_id, user=request.auth)
    address.is_default = True
    address.save(update_fields=["is_default"])
    address.refresh_from_db()
    return serialize_shipping_address(address)


# ---------------------------------------------------------------------------
# Withdrawal Accounts
# ---------------------------------------------------------------------------


def serialize_withdrawal_account(account):
    """Serialize a withdrawal account with sensitive fields masked."""
    data = {
        "id": account.id,
        "account_type": account.account_type,
        "real_name": mask_name(account.real_name),
        "created_at": account.created_at.isoformat(),
    }
    if account.account_type == "domestic":
        data.update(
            {
                "id_card": mask_card(account.id_card),
                "phone": mask_card(account.phone),
                "bank_card": mask_card(account.bank_card),
            }
        )
    else:
        data.update(
            {
                "currency": account.currency,
                "swift_account": mask_card(account.swift_account),
            }
        )
    return data


@router.get("/withdrawal-accounts", response=dict)
def withdrawal_account_list_endpoint(request):
    """List the authenticated user's withdrawal accounts (masked)."""
    return {
        "items": [
            serialize_withdrawal_account(account)
            for account in WithdrawalAccount.objects.filter(user=request.auth)
        ]
    }


@router.post(
    "/withdrawal-accounts",
    response={201: dict, 422: ErrorResponseSchema},
)
def withdrawal_account_create_endpoint(request, payload: WithdrawalAccountCreateSchema):
    """Create a withdrawal account."""
    data = payload.model_dump()
    account_type = data.get("account_type", "")

    # Validate account_type
    if account_type not in ("domestic", "international"):
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            {"account_type": [{"message": "Must be 'domestic' or 'international'."}]},
        )

    # Validate required fields per type
    if account_type == "domestic":
        missing = [
            f for f in ("real_name", "id_card", "phone", "bank_card") if not data.get(f)
        ]
        if missing:
            raise ApiError(
                "validation_error",
                422,
                "Request validation failed.",
                {field: [{"message": "This field is required."}] for field in missing},
            )

        # 银行卡号清洗：去除空格并校验纯数字
        data["bank_card"] = data["bank_card"].replace(" ", "")
        if not data["bank_card"].isdigit():
            raise ApiError(
                "validation_error",
                422,
                "Request validation failed.",
                {
                    "bank_card": [
                        {"message": "Bank card number must contain only digits."}
                    ]
                },
            )

        # 校验身边云签约用户：姓名、手机号、身份证号三字段必须在已签约记录中匹配
        signed_exists = SignedUser.objects.filter(
            name=data["real_name"],
            mobile=data["phone"],
            id_card=data["id_card"],
            state=SIGN_STATE_SIGNED,
        ).exists()
        if not signed_exists:
            raise ApiError(
                "not_signed",
                422,
                "尚未完成签约，请先签约。签约完成后五分钟方可进行绑定，请稍候。",
            )
    else:
        missing = [
            f for f in ("real_name", "currency", "swift_account") if not data.get(f)
        ]
        if missing:
            raise ApiError(
                "validation_error",
                422,
                "Request validation failed.",
                {field: [{"message": "This field is required."}] for field in missing},
            )
        # Validate currency
        if data.get("currency") and data["currency"] != "USD":
            raise ApiError(
                "validation_error",
                422,
                "Request validation failed.",
                {"currency": [{"message": "Only 'USD' is supported."}]},
            )

    account = WithdrawalAccount.objects.create(
        user=request.auth,
        account_type=account_type,
        real_name=data["real_name"],
        id_card=data.get("id_card", ""),
        phone=data.get("phone", ""),
        bank_card=data.get("bank_card", ""),
        currency=data.get("currency", ""),
        swift_account=data.get("swift_account", ""),
    )
    return 201, serialize_withdrawal_account(account)


@router.delete(
    "/withdrawal-accounts/{account_id}",
    response={204: None, 404: ErrorResponseSchema},
)
def withdrawal_account_delete_endpoint(request, account_id: int):
    """Delete a withdrawal account."""
    account = get_object_or_404(WithdrawalAccount, id=account_id, user=request.auth)
    account.delete()
    return 204, None


@router.get("/account-merges", response=dict)
def account_merge_list_endpoint(request):
    """Return sent and received account merge requests."""
    sent_requests = AccountMergeRequest.objects.filter(
        source_user=request.auth
    ).select_related(
        "source_user",
        "target_user",
    )
    incoming_requests = AccountMergeRequest.objects.filter(
        target_user=request.auth
    ).select_related("source_user", "target_user")
    return {
        "sent": [serialize_account_merge_request(item) for item in sent_requests],
        "incoming": [
            serialize_account_merge_request(item) for item in incoming_requests
        ],
    }


@router.post(
    "/account-merges",
    response={201: dict, 409: ErrorResponseSchema, 422: ErrorResponseSchema},
)
def account_merge_create_endpoint(request, payload: AccountMergeCreateSchema):
    """Create an account merge request."""
    form = AccountMergeRequestForm(user=request.auth, data=payload.model_dump())
    if not validate_form(form):
        raise ApiError(
            "validation_error",
            422,
            "Request validation failed.",
            form_error_detail(form),
        )

    try:
        merge_request = AccountMergeRequest.objects.create(
            source_user=request.auth,
            target_user=form.target_user,
            target_email_input=form.cleaned_data.get("target_email", ""),
            target_username_input=form.cleaned_data.get("target_username", ""),
            status=AccountMergeRequest.Status.PENDING,
            approve_token=_generate_unique_token(),
            expires_at=timezone.now() + timedelta(days=7),
            asset_snapshot=_build_asset_snapshot(request.auth),
        )
    except IntegrityError as exc:
        raise ApiError(
            "merge_request_conflict",
            409,
            "A pending merge request already exists for this account.",
        ) from exc

    _send_merge_request_message(merge_request, request)
    merge_request.refresh_from_db()
    return 201, serialize_account_merge_request(merge_request)


@router.get(
    "/account-merges/review/{token}",
    response={200: dict, 404: ErrorResponseSchema},
)
def account_merge_review_endpoint(request, token: str):
    """Return a merge request for review by the target account."""
    merge_request = _get_reviewable_merge_request(request.auth, token)
    _expire_request_if_needed(merge_request, request.auth, request)
    merge_request.refresh_from_db()
    return {
        **serialize_account_merge_request(merge_request, include_logs=True),
        "can_accept": merge_request.status == AccountMergeRequest.Status.PENDING,
        "can_reject": merge_request.status == AccountMergeRequest.Status.PENDING,
    }


@router.post(
    "/account-merges/review/{token}/accept",
    response={200: dict, 404: ErrorResponseSchema, 409: ErrorResponseSchema},
)
def account_merge_accept_endpoint(request, token: str):
    """Accept a merge request as the target account."""
    merge_request = _get_reviewable_merge_request(request.auth, token)
    if _expire_request_if_needed(merge_request, request.auth, request):
        raise ApiError(
            "merge_request_expired",
            409,
            "This merge request has expired.",
        )

    if merge_request.status != AccountMergeRequest.Status.PENDING:
        raise ApiError(
            "merge_request_not_pending",
            409,
            "This merge request can no longer be accepted.",
            {"status": merge_request.status},
        )

    try:
        perform_merge(merge_request)
    except AccountMergeError as exc:
        raise ApiError(
            "merge_failed",
            409,
            "The merge request could not be completed.",
            {"reason": str(exc)},
        ) from exc

    _notify_merge_result(merge_request, accepted=True, request=request)
    merge_request.refresh_from_db()
    return serialize_account_merge_request(merge_request, include_logs=True)


@router.post(
    "/account-merges/review/{token}/reject",
    response={200: dict, 404: ErrorResponseSchema, 409: ErrorResponseSchema},
)
def account_merge_reject_endpoint(request, token: str):
    """Reject a merge request as the target account."""
    merge_request = _get_reviewable_merge_request(request.auth, token)
    if _expire_request_if_needed(merge_request, request.auth, request):
        raise ApiError(
            "merge_request_expired",
            409,
            "This merge request has expired.",
        )

    if merge_request.status != AccountMergeRequest.Status.PENDING:
        raise ApiError(
            "merge_request_not_pending",
            409,
            "This merge request can no longer be rejected.",
            {"status": merge_request.status},
        )

    merge_request.status = AccountMergeRequest.Status.REJECTED
    merge_request.processed_by = request.auth
    merge_request.processed_at = timezone.now()
    merge_request.save(update_fields=["status", "processed_by", "processed_at"])
    _notify_merge_result(
        merge_request,
        accepted=False,
        request=request,
        reason="The target account rejected the merge request.",
    )

    merge_request.refresh_from_db()
    return serialize_account_merge_request(merge_request, include_logs=True)
