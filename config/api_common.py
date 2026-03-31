"""Shared helpers for versioned JSON APIs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from django.core.paginator import Paginator
from django.utils import translation
from ninja import Schema


class ErrorResponseSchema(Schema):
    """Standardized error payload."""

    code: str
    message: str
    detail: Any | None = None


class PaginationSchema(Schema):
    """Shared pagination metadata."""

    page: int
    page_size: int
    total_items: int
    total_pages: int
    has_next: bool
    has_previous: bool


@dataclass(slots=True)
class ApiError(Exception):
    """Structured API exception handled centrally by Ninja."""

    code: str
    status_code: int
    message: str
    detail: Any | None = None

    def __str__(self) -> str:
        """Return the human-readable message."""
        return self.message


def form_error_detail(form) -> dict[str, Any]:
    """Serialize Django form errors for JSON APIs."""
    return translate_error_detail(form.errors.get_json_data())


def validate_form(form) -> bool:
    """Validate a Django form while forcing English validation messages."""
    with translation.override("en"):
        return form.is_valid()


ERROR_MESSAGE_MAP = {
    "该邮箱已被注册": "This email is already registered.",
    "开始日期必须早于结束日期": "The start date must be earlier than the end date.",
    "新邮箱不能与当前邮箱相同": (
        "The new email address must be different from the current one."
    ),
    "该邮箱已被其他用户使用": "This email address is already used by another account.",
    "密码不正确": "The password is incorrect.",
    "请输入目标账号的邮箱或用户名（至少一项）": (
        "Provide at least a target email address or username."
    ),
    "未找到匹配的目标账号，请检查用户名或邮箱是否正确": (
        "No matching target account was found. Check the username or email address."
    ),
    "匹配到多个账号，请同时提供用户名和邮箱以精确匹配": (
        "Multiple accounts matched. Provide both username and email to identify the "
        "target account."
    ),
    "管理员账号不支持发起合并": (
        "Administrator accounts cannot initiate an account merge."
    ),
    "当前账号已被停用，无法发起合并": (
        "This account is inactive and cannot initiate an account merge."
    ),
    "不能合并到自己的账号": "You cannot merge an account into itself.",
    "目标账号为管理员，无法合并": (
        "The target account is an administrator account and cannot be merged."
    ),
    "您已有待处理的合并申请，请等待处理后再尝试": (
        "You already have a pending merge request. Wait until it is resolved before "
        "creating another one."
    ),
    "该目标账号待处理申请过多，请稍后再试": (
        "The target account already has too many pending merge requests. Try again "
        "later."
    ),
    "提现金额必须大于 0": "The withdrawal amount must be greater than 0.",
    "请输入有效的手机号码（11位数字）": "Enter a valid 11-digit phone number.",
    "请输入有效的身份证号（15或18位）": (
        "Enter a valid ID card number with 15 or 18 characters."
    ),
    "请输入有效的银行卡号（16-19位数字）": (
        "Enter a valid bank account number with 16 to 19 digits."
    ),
    "提现金额超过 5000 积分时必须上传发票": (
        "An invoice file is required when the withdrawal amount exceeds 5000 points."
    ),
    "组织名称不能为空。": "The organization name is required.",
    "URL 别名不能为空。": "The organization slug is required.",
    "URL 别名已存在。": "The organization slug is already in use.",
    "URL 别名只能包含字母、数字、连字符和下划线。": (
        "The organization slug may only contain letters, numbers, hyphens, and "
        "underscores."
    ),
}

ERROR_MESSAGE_PATTERNS = [
    (
        re.compile(r"^现金积分不足，当前可用: (?P<balance>\d+)$"),
        lambda m: f"Not enough cash points. Available balance: {m['balance']}.",
    ),
]


def translate_error_text(message: str) -> str:
    """Translate API-facing validation strings to English when possible."""
    normalized = (message or "").strip()
    if not normalized:
        return normalized

    translated = ERROR_MESSAGE_MAP.get(normalized)
    if translated is not None:
        return translated

    for pattern, formatter in ERROR_MESSAGE_PATTERNS:
        match = pattern.match(normalized)
        if match:
            return formatter(match.groupdict())

    return normalized


def translate_error_detail(detail: Any) -> Any:
    """Recursively translate nested API error details to English when possible."""
    if isinstance(detail, str):
        return translate_error_text(detail)
    if isinstance(detail, list):
        return [translate_error_detail(item) for item in detail]
    if isinstance(detail, dict):
        return {
            key: (
                translate_error_text(value)
                if key == "message" and isinstance(value, str)
                else translate_error_detail(value)
            )
            for key, value in detail.items()
        }
    return detail


def paginate_queryset(
    queryset,
    page: int = 1,
    page_size: int = 20,
    *,
    max_page_size: int = 100,
):
    """Return a Django page object with bounded pagination settings."""
    safe_page = max(page or 1, 1)
    safe_page_size = min(max(page_size or 20, 1), max_page_size)
    paginator = Paginator(queryset, safe_page_size)
    return paginator.get_page(safe_page)


def build_paginated_response(page_obj, items: list[Any]) -> dict[str, Any]:
    """Return a consistent list response shape."""
    return {
        "items": items,
        "pagination": {
            "page": page_obj.number,
            "page_size": page_obj.paginator.per_page,
            "total_items": page_obj.paginator.count,
            "total_pages": page_obj.paginator.num_pages,
            "has_next": page_obj.has_next(),
            "has_previous": page_obj.has_previous(),
        },
    }
