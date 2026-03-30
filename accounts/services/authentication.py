"""Password-based authentication helpers shared by views and APIs."""

from dataclasses import dataclass
from typing import Any

from django.contrib.auth import authenticate, get_user_model
from django.http import HttpRequest


@dataclass(slots=True)
class PasswordLoginError(Exception):
    """Base exception for account/password sign-in failures."""

    code: str
    status_code: int
    message: str

    def __str__(self) -> str:
        """Return the human-readable message."""
        return self.message


class InvalidCredentialsError(PasswordLoginError):
    """Raised when account credentials are invalid."""

    def __init__(self) -> None:
        """Initialize the invalid-credentials error payload."""
        super().__init__(
            code="invalid_credentials",
            status_code=401,
            message="用户名或密码错误，请重试",
        )


class AccountDisabledError(PasswordLoginError):
    """Raised when the matching account is inactive."""

    def __init__(self) -> None:
        """Initialize the disabled-account error payload."""
        super().__init__(
            code="account_disabled",
            status_code=403,
            message="账号已被停用，请联系管理员",
        )


class AccountMergedError(PasswordLoginError):
    """Raised when the source account has been merged into another account."""

    def __init__(self, target_label: str) -> None:
        """Initialize the merged-account error payload."""
        super().__init__(
            code="account_merged",
            status_code=409,
            message=f"该账号已合并到 {target_label}，请使用目标账号登录",
        )


def authenticate_by_login_id(
    login_id: str,
    password: str,
    *,
    request: HttpRequest | None = None,
) -> Any:
    """Authenticate a user with username or email and password."""
    UserModel = get_user_model()
    username_match = UserModel.objects.filter(username=login_id).first()
    email_user = None

    if "@" in login_id:
        email_qs = UserModel.objects.filter(email=login_id)
        email_user = email_qs.filter(is_active=True).first() or email_qs.first()

    user = authenticate(request, username=login_id, password=password)
    if not user and email_user:
        user = authenticate(request, username=email_user.username, password=password)

    candidate_user = username_match or email_user

    if not user:
        if (
            username_match
            and username_match.merged_into_id
            and login_id == username_match.username
        ):
            target = username_match.merged_into
            target_label = target.email or target.username
            raise AccountMergedError(target_label)
        if candidate_user and not candidate_user.is_active:
            raise AccountDisabledError()
        raise InvalidCredentialsError()

    if not user.is_active:
        raise AccountDisabledError()

    return user
