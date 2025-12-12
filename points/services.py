"""积分系统的业务逻辑服务层, 提供积分发放和消费功能."""

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F, Q
from django.utils.text import slugify

from .models import (
    PointSource,
    PointTransaction,
    Tag,
    WithdrawalContract,
    WithdrawalRequest,
)

User = get_user_model()
logger = logging.getLogger(__name__)


def _normalize_user(user: User | None = None, user_profile: User | None = None) -> User:
    """Return a concrete user instance from legacy arguments."""
    if user is None and user_profile is None:
        msg = "必须提供 user 或 user_profile 参数。"
        raise ValueError(msg)

    if user is not None and user_profile is not None and user != user_profile:
        msg = "user 与 user_profile 参数指向不同的用户。"
        raise ValueError(msg)

    return user or user_profile


# 定义一个自定义异常，便于上层逻辑捕获
class InsufficientPointsError(Exception):
    """当用户积分不足时抛出此异常."""

    pass


@transaction.atomic
def grant_points(
    user: User | None = None,
    *,
    points: int,
    description: str,
    tag_names: Iterable[str] | None = None,
    source_object=None,
    **legacy_kwargs,
) -> PointSource:
    """
    为用户发放积分.

    这是一个原子操作.

    Args:
        user (User | None): 获得积分的用户 (兼容旧版参数名)。
        points (int): 发放的积分数量, 必须为正数.
        description (str): 积分来源描述, 将记录在流水中.
        tag_names (Iterable[str] | None): 一个包含标签名称的集合. 如果标签不存在, 会自动创建.
        source_object (models.Model, optional): 关联的源对象, 用于追溯.
        **legacy_kwargs: 接受 legacy user_profile 参数.

    Returns:
        PointSource: 新创建的积分来源对象.

    Raises:
        ValueError: 如果 points 不是正数.

    """
    legacy_user_profile = legacy_kwargs.pop("user_profile", None)
    if legacy_kwargs:
        unexpected = ", ".join(sorted(legacy_kwargs))
        msg = f"Unsupported legacy kwargs: {unexpected}"
        raise TypeError(msg)

    resolved_user = _normalize_user(user=user, user_profile=legacy_user_profile)

    if not isinstance(points, int) or points <= 0:
        msg = "发放的积分必须是正整数。"
        raise ValueError(msg)

    tag_names = list(tag_names or [])

    # 1. 处理标签：获取或创建（Get or Create）
    # 支持使用 name 或 slug 来查找标签
    tags_to_add = []
    for name_or_slug in tag_names:
        # 先尝试通过 slug 或 name 查找
        tag = Tag.objects.filter(Q(slug=name_or_slug) | Q(name=name_or_slug)).first()

        if tag is None:
            # 如果不存在，创建新标签（使用输入作为 name，生成 slug）
            tag_slug = slugify(name_or_slug)
            # 如果 slug 为空（如纯中文），使用原值
            if not tag_slug:
                tag_slug = name_or_slug
            tag, _ = Tag.objects.get_or_create(
                name=name_or_slug, defaults={"slug": tag_slug}
            )

        tags_to_add.append(tag)

    # 2. 创建积分来源（积分桶）
    new_source = PointSource.objects.create(
        user=resolved_user,
        initial_points=points,
        remaining_points=points,
    )
    # 关联标签
    new_source.tags.set(tags_to_add)

    # 3. 记录积分流水（账本）
    PointTransaction.objects.create(
        user=resolved_user,
        points=points,  # 正数表示增加
        transaction_type=PointTransaction.TransactionType.EARN,
        description=description,
    )

    logger.info(
        "积分发放成功: 用户=%s (ID=%s), 积分=%s, 标签=%s, 描述=%s",
        resolved_user.username,
        resolved_user.id,
        points,
        tag_names,
        description,
    )

    if hasattr(resolved_user, "clear_points_cache"):
        resolved_user.clear_points_cache()

    return new_source


@transaction.atomic
def spend_points(
    user: User | None = None,
    *,
    amount: int,
    description: str,
    priority_tag_name: str | None = None,
    **legacy_kwargs,
) -> PointTransaction:
    """
    消费用户的积分.

    这是一个原子操作, 并实现了优先扣除逻辑.

    Args:
        user (User | None): 消费积分的用户 (兼容旧版参数名)。
        amount (int): 消费的积分数量, 必须为正数.
        description (str): 消费描述, 将记录在流水中.
        priority_tag_name (str | None, optional): 优先扣除的标签名称.
        **legacy_kwargs: 接受 legacy user_profile 参数.

    Returns:
        PointTransaction: 新创建的消费流水对象.

    Raises:
        ValueError: 如果 amount 不是正数.
        InsufficientPointsError: 如果用户总积分不足以消费.

    """
    legacy_user_profile = legacy_kwargs.pop("user_profile", None)
    if legacy_kwargs:
        unexpected = ", ".join(sorted(legacy_kwargs))
        msg = f"Unsupported legacy kwargs: {unexpected}"
        raise TypeError(msg)

    resolved_user = _normalize_user(user=user, user_profile=legacy_user_profile)

    if not isinstance(amount, int) or amount <= 0:
        msg = "消费的积分必须是正整数。"
        raise ValueError(msg)

    active_sources = PointSource.objects.filter(
        user=resolved_user, remaining_points__gt=0
    ).select_for_update()
    current_balance = sum(source.remaining_points for source in active_sources)
    _ensure_sufficient_balance(resolved_user, amount, current_balance, description)

    amount_to_deduct = amount
    consumed_sources_list: list[PointSource] = []
    consumed_ids: set[int] = set()

    for filters in _deduction_conditions(priority_tag_name):
        if amount_to_deduct <= 0:
            break

        queryset = (
            PointSource.objects.filter(
                user=resolved_user,
                remaining_points__gt=0,
                **filters,
            )
            .exclude(id__in=list(consumed_ids))
            .order_by("created_at")
        )

        amount_to_deduct, consumed = _deduct_from_queryset(queryset, amount_to_deduct)
        consumed_sources_list.extend(consumed)
        consumed_ids.update(source.id for source in consumed)

    if amount_to_deduct > 0:  # pragma: no cover
        msg = "积分扣除逻辑异常：最终应扣除额度大于0。"
        raise Exception(msg)

    # 5. 创建消费流水记录
    spend_transaction = PointTransaction.objects.create(
        user=resolved_user,
        points=-amount,  # 负数表示减少
        transaction_type=PointTransaction.TransactionType.SPEND,
        description=description,
    )
    # 关联此次消费涉及到的所有积分来源
    spend_transaction.consumed_sources.set(consumed_sources_list)

    logger.info(
        "积分消费成功: 用户=%s (ID=%s), 消费=%s, 剩余=%s, 消费源数量=%s, 优先标签=%s, 描述=%s",
        resolved_user.username,
        resolved_user.id,
        amount,
        current_balance - amount,
        len(consumed_sources_list),
        priority_tag_name or "无",
        description,
    )

    if hasattr(resolved_user, "clear_points_cache"):
        resolved_user.clear_points_cache()

    return spend_transaction


def _deduct_from_queryset(queryset, needed):
    """Deduct points from the provided queryset in FIFO order."""
    consumed = []
    for source in queryset.select_for_update():
        if needed <= 0:
            break

        deduct_amount = min(source.remaining_points, needed)
        source.remaining_points = F("remaining_points") - deduct_amount
        source.save(update_fields=["remaining_points"])
        consumed.append(source)
        needed -= deduct_amount

    return needed, consumed


def _deduction_conditions(priority_tag_name: str | None):
    """Yield successive deduction filters based on priority rules."""
    if priority_tag_name:
        yield {"tags__name": priority_tag_name}
    yield {"tags__is_default": True}
    yield {}


def _ensure_sufficient_balance(user, amount, current_balance, description):
    """Raise InsufficientPointsError when the balance is too low."""
    if current_balance >= amount:
        return

    msg = f"积分不足。当前余额: {current_balance}, 需要: {amount}"
    logger.warning(
        "积分消费失败（余额不足）: 用户=%s (ID=%s), 需要=%s, 当前余额=%s, 描述=%s",
        user.username,
        user.id,
        amount,
        current_balance,
        description,
    )
    raise InsufficientPointsError(msg)


class WithdrawalError(Exception):
    """提现相关错误的基类."""

    pass


class WithdrawalContractNotSigned(WithdrawalError):
    """当用户未完成提现合同签署时抛出此异常."""

    pass


class PointSourceNotWithdrawableError(WithdrawalError):
    """当积分来源不支持提现时抛出此异常."""

    pass


class WithdrawalAmountError(WithdrawalError):
    """当提现金额不合法时抛出此异常."""

    pass


@dataclass
class WithdrawalData:
    """提现申请数据."""

    real_name: str
    id_number: str
    phone_number: str
    bank_name: str
    bank_account: str


def get_or_create_withdrawal_contract(user: User) -> tuple[WithdrawalContract, bool]:
    """
    获取或创建提现合同.

    会为用户生成一个占位的法大大流程ID和签署链接。
    """
    contract, created = WithdrawalContract.objects.get_or_create(
        user=user,
        defaults={
            "fadada_flow_id": uuid.uuid4().hex,
            "sign_url": "",  # 占位，后续可替换成真实法大大链接
        },
    )

    # 如果 sign_url 为空，为其生成占位符链接（幂等）
    if not contract.sign_url:
        contract.sign_url = f"https://example.com/fadada/sign/{contract.fadada_flow_id}"
        contract.save(update_fields=["sign_url", "updated_at"])

    return contract, created


def ensure_contract_signed(user: User) -> None:
    """
    确认用户已完成提现合同签署, 否则抛出异常.

    Raises:
        WithdrawalContractNotSigned: 当用户未完成签署时。

    """
    contract, _ = get_or_create_withdrawal_contract(user)
    if not contract.is_signed:
        msg = "提现前需要先完成合同签署。"
        raise WithdrawalContractNotSigned(msg)


@transaction.atomic
def create_withdrawal_request(
    user: User,
    point_source_id: int,
    points: int,
    withdrawal_data: WithdrawalData,
) -> WithdrawalRequest:
    """
    创建提现申请.

    这是一个原子操作.

    Args:
        user (User): 申请提现的用户。
        point_source_id (int): 积分来源ID。
        points (int): 提现积分数量。
        withdrawal_data (WithdrawalData): 提现申请数据(姓名、身份证、银行信息等)。

    Returns:
        WithdrawalRequest: 新创建的提现申请对象。

    Raises:
        PointSource.DoesNotExist: 如果积分来源不存在。
        PointSourceNotWithdrawableError: 如果积分来源不支持提现。
        WithdrawalAmountError: 如果提现金额不合法。

    """
    # 0. 确认用户已签署提现合同
    ensure_contract_signed(user)

    # 1. 验证积分来源
    try:
        point_source = PointSource.objects.select_for_update().get(
            id=point_source_id, user=user
        )
    except PointSource.DoesNotExist as e:
        logger.warning(
            "提现申请失败（积分来源不存在）: 用户=%s (ID=%s), 积分来源ID=%s",
            user.username,
            user.id,
            point_source_id,
        )
        msg = "积分来源不存在或不属于您。"
        raise PointSource.DoesNotExist(msg) from e

    # 2. 验证是否可提现
    if not point_source.is_withdrawable:
        logger.warning(
            "提现申请失败（积分来源不可提现）: 用户=%s (ID=%s), 积分来源ID=%s",
            user.username,
            user.id,
            point_source_id,
        )
        msg = "该积分来源不支持提现。"
        raise PointSourceNotWithdrawableError(msg)

    # 3. 验证提现金额
    if not isinstance(points, int) or points <= 0:
        msg = "提现积分必须是正整数。"
        raise WithdrawalAmountError(msg)

    if points > point_source.remaining_points:
        msg = f"提现积分不能超过剩余积分。剩余积分: {point_source.remaining_points}, 申请提现: {points}"
        logger.warning(
            "提现申请失败（积分不足）: 用户=%s (ID=%s), 剩余=%s, 申请=%s",
            user.username,
            user.id,
            point_source.remaining_points,
            points,
        )
        raise WithdrawalAmountError(msg)

    # 4. 创建提现申请
    withdrawal_request = WithdrawalRequest.objects.create(
        user=user,
        point_source=point_source,
        points=points,
        real_name=withdrawal_data.real_name,
        id_number=withdrawal_data.id_number,
        phone_number=withdrawal_data.phone_number,
        bank_name=withdrawal_data.bank_name,
        bank_account=withdrawal_data.bank_account,
    )

    logger.info(
        "提现申请创建成功: 用户=%s (ID=%s), 积分=%s, 申请ID=%s",
        user.username,
        user.id,
        points,
        withdrawal_request.id,
    )

    return withdrawal_request


@transaction.atomic
def approve_withdrawal(
    withdrawal_request: WithdrawalRequest, admin_user: User, admin_note: str = ""
) -> PointTransaction:
    """
    批准提现申请并扣除相应积分.

    将申请状态直接变为"已完成", 扣除积分并创建提现交易记录.

    这是一个原子操作.

    Args:
        withdrawal_request (WithdrawalRequest): 提现申请对象。
        admin_user (User): 处理该申请的管理员。
        admin_note (str, optional): 管理员备注。

    Returns:
        PointTransaction: 提现交易记录。

    Raises:
        WithdrawalError: 如果申请状态不是待处理。
        InsufficientPointsError: 如果积分不足。

    """
    from django.utils import timezone

    # 验证申请状态
    if withdrawal_request.status != WithdrawalRequest.Status.PENDING:
        msg = f"只能批准待处理状态的申请。当前状态: {withdrawal_request.get_status_display()}"
        raise WithdrawalError(msg)

    # 扣除积分（使用现有的 spend_points 服务）
    transaction = spend_points(
        user=withdrawal_request.user,
        amount=withdrawal_request.points,
        description=f"提现申请 #{withdrawal_request.id}",
    )

    # 更新交易类型为提现
    transaction.transaction_type = PointTransaction.TransactionType.WITHDRAW
    transaction.save(update_fields=["transaction_type"])

    # 更新提现申请状态为已完成
    withdrawal_request.status = WithdrawalRequest.Status.COMPLETED
    withdrawal_request.processed_by = admin_user
    withdrawal_request.processed_at = timezone.now()
    withdrawal_request.admin_note = admin_note
    withdrawal_request.save()

    logger.info(
        "提现申请已完成: 申请ID=%s, 用户=%s (ID=%s), 积分=%s, 处理人=%s",
        withdrawal_request.id,
        withdrawal_request.user.username,
        withdrawal_request.user.id,
        withdrawal_request.points,
        admin_user.username,
    )

    return transaction


@transaction.atomic
def reject_withdrawal(
    withdrawal_request: WithdrawalRequest, admin_user: User, admin_note: str = ""
):
    """
    拒绝提现申请.

    Args:
        withdrawal_request (WithdrawalRequest): 提现申请对象。
        admin_user (User): 处理该申请的管理员。
        admin_note (str, optional): 拒绝原因。

    Raises:
        WithdrawalError: 如果申请状态不是待处理。

    """
    from django.utils import timezone

    # 验证申请状态
    if withdrawal_request.status != WithdrawalRequest.Status.PENDING:
        msg = f"只能拒绝待处理状态的申请。当前状态: {withdrawal_request.get_status_display()}"
        raise WithdrawalError(msg)

    # 更新申请状态
    withdrawal_request.status = WithdrawalRequest.Status.REJECTED
    withdrawal_request.processed_by = admin_user
    withdrawal_request.processed_at = timezone.now()
    withdrawal_request.admin_note = admin_note
    withdrawal_request.save()

    logger.info(
        "提现申请已拒绝: 申请ID=%s, 用户=%s (ID=%s), 处理人=%s, 原因=%s",
        withdrawal_request.id,
        withdrawal_request.user.username,
        withdrawal_request.user.id,
        admin_user.username,
        admin_note,
    )


@transaction.atomic
def cancel_withdrawal(withdrawal_request: WithdrawalRequest):
    """
    用户取消提现申请.

    Args:
        withdrawal_request (WithdrawalRequest): 提现申请对象。

    Raises:
        WithdrawalError: 如果申请状态不是待处理。

    """
    from django.utils import timezone

    # 验证申请状态
    if withdrawal_request.status != WithdrawalRequest.Status.PENDING:
        msg = f"只能取消待处理状态的申请。当前状态: {withdrawal_request.get_status_display()}"
        raise WithdrawalError(msg)

    # 更新申请状态
    withdrawal_request.status = WithdrawalRequest.Status.CANCELLED
    withdrawal_request.processed_at = timezone.now()
    withdrawal_request.save()

    logger.info(
        "提现申请已取消: 申请ID=%s, 用户=%s (ID=%s)",
        withdrawal_request.id,
        withdrawal_request.user.username,
        withdrawal_request.user.id,
    )


@transaction.atomic
def create_batch_withdrawal_requests(
    user: User,
    withdrawal_amounts: dict[int, int],
    withdrawal_data: WithdrawalData,
) -> list[WithdrawalRequest]:
    """
    批量创建提现申请.

    这是一个原子操作, 如果任何一个申请创建失败, 所有申请都会回滚。

    Args:
        user (User): 申请提现的用户。
        withdrawal_amounts (dict[int, int]): 积分来源ID到提现数量的映射。
        withdrawal_data (WithdrawalData): 提现申请数据(姓名、身份证、银行信息等)。

    Returns:
        list[WithdrawalRequest]: 创建的提现申请列表。

    Raises:
        PointSource.DoesNotExist: 如果任何积分来源不存在。
        PointSourceNotWithdrawableError: 如果任何积分来源不支持提现。
        WithdrawalAmountError: 如果任何提现金额不合法。

    """
    # 0. 确认用户已签署提现合同
    ensure_contract_signed(user)

    # 验证至少有一个提现请求
    if not withdrawal_amounts:
        msg = "至少需要选择一个积分池进行提现。"
        raise WithdrawalError(msg)

    withdrawal_requests = []

    # 为每个积分池创建提现申请
    for point_source_id, points in withdrawal_amounts.items():
        # 跳过提现数量为0或None的项
        if not points or points <= 0:
            continue

        # 创建单个提现申请
        withdrawal_request = create_withdrawal_request(
            user=user,
            point_source_id=point_source_id,
            points=points,
            withdrawal_data=withdrawal_data,
        )
        withdrawal_requests.append(withdrawal_request)

    # 验证至少创建了一个提现申请
    if not withdrawal_requests:
        msg = "至少需要为一个积分池设置提现数量。"
        raise WithdrawalError(msg)

    logger.info(
        "批量提现申请创建成功: 用户=%s (ID=%s), 申请数量=%s, 总积分=%s",
        user.username,
        user.id,
        len(withdrawal_requests),
        sum(wr.points for wr in withdrawal_requests),
    )

    return withdrawal_requests
