"""Service layer for points application business logic."""

import logging
from collections import defaultdict

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.models import Organization, User

from .models import (
    PointSource,
    PointTransaction,
    PointType,
    PointWallet,
    Tag,
    TransactionType,
    WithdrawalRequest,
    WithdrawalStatus,
)

logger = logging.getLogger(__name__)


class InsufficientPointsError(Exception):
    """积分不足异常."""


class InvalidPointOperationError(Exception):
    """无效的积分操作异常."""


class WithdrawalError(Exception):
    """提现错误异常."""


def get_or_create_wallet(owner: User | Organization) -> PointWallet:
    """
    获取或创建积分钱包.

    Args:
        owner: User 或 Organization 实例

    Returns:
        PointWallet: 积分钱包实例

    """
    content_type = ContentType.objects.get_for_model(owner)
    wallet, created = PointWallet.objects.get_or_create(
        content_type=content_type,
        object_id=owner.pk,
    )
    if created:
        logger.info(
            "创建积分钱包: owner_type=%s, owner_id=%s, wallet_id=%s",
            content_type.model,
            owner.pk,
            wallet.id,
        )
    return wallet


def get_balance(
    owner: User | Organization,
    point_type: str | None = None,
    tag_slug: str | None = None,
) -> int:
    """
    获取积分余额.

    Args:
        owner: User 或 Organization 实例
        point_type: 积分类型 (cash/gift), 为 None 时返回总余额
        tag_slug: 标签别名, 仅对 gift 类型有效

    Returns:
        int: 积分余额

    """
    wallet = get_or_create_wallet(owner)

    if point_type is None:
        return wallet.get_total_balance()
    elif point_type == PointType.CASH:
        return wallet.get_cash_balance()
    elif point_type == PointType.GIFT:
        return wallet.get_gift_balance(tag_slug=tag_slug)
    else:
        msg = f"无效的积分类型: {point_type}"
        raise InvalidPointOperationError(msg)


def get_detailed_balance(owner: User | Organization) -> dict:
    """
    获取详细的积分余额信息.

    Args:
        owner: User 或 Organization 实例

    Returns:
        dict: 包含 cash, gift, by_tag 的详细余额信息

    """
    wallet = get_or_create_wallet(owner)

    # 获取现金积分
    cash_balance = wallet.get_cash_balance()

    # 获取礼物积分（按标签分组）
    gift_sources = wallet.sources.filter(
        point_type=PointType.GIFT,
        remaining_amount__gt=0,
    ).select_related("tag")

    gift_total = 0
    by_tag = defaultdict(int)
    no_tag_total = 0

    for source in gift_sources:
        gift_total += source.remaining_amount
        if source.tag:
            by_tag[source.tag.slug] += source.remaining_amount
        else:
            no_tag_total += source.remaining_amount

    return {
        "total": cash_balance + gift_total,
        "cash": cash_balance,
        "gift": gift_total,
        "gift_no_tag": no_tag_total,
        "by_tag": dict(by_tag),
    }


@transaction.atomic
def grant_points(  # noqa: PLR0913
    owner: User | Organization,
    amount: int,
    point_type: str,
    reason: str,
    *,
    tag_slug: str | None = None,
    expires_at=None,
    reference_id: str = "",
    created_by: User | None = None,
) -> PointSource:
    """
    发放积分.

    Args:
        owner: User 或 Organization 实例
        amount: 发放数量
        point_type: 积分类型 (cash/gift)
        reason: 发放原因
        tag_slug: 标签别名(仅 gift 类型可用)
        expires_at: 过期时间
        reference_id: 关联ID
        created_by: 创建者

    Returns:
        PointSource: 积分来源记录

    Raises:
        InvalidPointOperationError: 如果参数无效

    """
    if amount <= 0:
        msg = "发放数量必须大于 0"
        raise InvalidPointOperationError(msg)

    if point_type not in [PointType.CASH, PointType.GIFT]:
        msg = f"无效的积分类型: {point_type}"
        raise InvalidPointOperationError(msg)

    if tag_slug and point_type != PointType.GIFT:
        msg = "只有礼物积分可以设置标签"
        raise InvalidPointOperationError(msg)

    wallet = get_or_create_wallet(owner)

    # 获取标签
    tag = None
    if tag_slug:
        try:
            tag = Tag.objects.get(slug=tag_slug)
        except Tag.DoesNotExist as err:
            msg = f"标签不存在: {tag_slug}"
            raise InvalidPointOperationError(msg) from err

    # 创建积分来源
    source = PointSource.objects.create(
        wallet=wallet,
        point_type=point_type,
        tag=tag,
        original_amount=amount,
        remaining_amount=amount,
        reason=reason,
        reference_id=reference_id,
        expires_at=expires_at,
        created_by=created_by,
    )

    # 获取新余额
    if point_type == PointType.CASH:
        balance_after = wallet.get_cash_balance()
    else:
        balance_after = wallet.get_gift_balance()

    # 创建交易记录
    PointTransaction.objects.create(
        wallet=wallet,
        transaction_type=TransactionType.EARN,
        point_type=point_type,
        amount=amount,
        balance_after=balance_after,
        description=reason,
        reference_id=reference_id,
        source=source,
        tag=tag,
        created_by=created_by,
    )

    logger.info(
        "发放积分成功: wallet_id=%s, type=%s, amount=%s, tag=%s, reason=%s",
        wallet.id,
        point_type,
        amount,
        tag_slug or "无",
        reason,
    )

    return source


def _get_available_balance(
    wallet: PointWallet,
    point_type: str,
    tag_slug: str | None,
    tag_is_null: bool,
) -> int:
    if tag_slug:
        return wallet.get_gift_balance(tag_slug=tag_slug)
    if point_type == PointType.GIFT and tag_is_null:
        return (
            wallet.sources.filter(
                point_type=PointType.GIFT,
                remaining_amount__gt=0,
                tag__isnull=True,
            ).aggregate(total=Sum("remaining_amount"))["total"]
            or 0
        )
    if point_type == PointType.CASH:
        return wallet.get_cash_balance()
    return wallet.get_gift_balance()


def _get_spend_sources_queryset(
    wallet: PointWallet,
    point_type: str,
    tag_slug: str | None,
    tag_is_null: bool,
):
    sources_queryset = wallet.sources.filter(
        point_type=point_type,
        remaining_amount__gt=0,
    ).order_by("created_at")

    if tag_slug:
        return sources_queryset.filter(tag__slug=tag_slug)
    if tag_is_null:
        return sources_queryset.filter(tag__isnull=True)
    return sources_queryset


@transaction.atomic
def spend_points(  # noqa: PLR0913
    owner: User | Organization,
    amount: int,
    point_type: str,
    description: str,
    *,
    tag_slug: str | None = None,
    tag_is_null: bool = False,
    reference_id: str = "",
    created_by: User | None = None,
) -> list[PointTransaction]:
    """
    消费积分(FIFO 方式).

    Args:
        owner: User 或 Organization 实例
        amount: 消费数量
        point_type: 积分类型 (cash/gift)
        description: 消费描述
        tag_slug: 标签别名(仅限使用特定标签的积分)
        tag_is_null: 仅消费无标签礼物积分
        reference_id: 关联ID
        created_by: 创建者

    Returns:
        list[PointTransaction]: 交易记录列表

    Raises:
        InvalidPointOperationError: 如果参数无效
        InsufficientPointsError: 如果积分不足

    """
    if amount <= 0:
        msg = "消费数量必须大于 0"
        raise InvalidPointOperationError(msg)

    if point_type not in [PointType.CASH, PointType.GIFT]:
        msg = f"无效的积分类型: {point_type}"
        raise InvalidPointOperationError(msg)

    wallet = get_or_create_wallet(owner)

    # 获取可用余额
    if tag_slug and tag_is_null:
        msg = "tag_slug 与 tag_is_null 不能同时使用"
        raise InvalidPointOperationError(msg)

    if tag_slug and point_type != PointType.GIFT:
        msg = "只有礼物积分可以按标签筛选"
        raise InvalidPointOperationError(msg)

    available = _get_available_balance(wallet, point_type, tag_slug, tag_is_null)

    if available < amount:
        msg = f"积分不足：需要 {amount}，可用 {available}"
        raise InsufficientPointsError(msg)

    # 获取可消费的积分来源（FIFO）
    sources = list(
        _get_spend_sources_queryset(
            wallet, point_type, tag_slug, tag_is_null
        ).select_for_update()
    )

    # 消费积分
    remaining_to_spend = amount
    transactions = []

    for source in sources:
        if remaining_to_spend <= 0:
            break

        spend_from_source = min(source.remaining_amount, remaining_to_spend)
        source.remaining_amount -= spend_from_source
        source.save(update_fields=["remaining_amount"])

        remaining_to_spend -= spend_from_source

        # 获取当前余额
        if point_type == PointType.CASH:
            balance_after = wallet.get_cash_balance()
        else:
            balance_after = wallet.get_gift_balance()

        # 创建交易记录
        txn = PointTransaction.objects.create(
            wallet=wallet,
            transaction_type=TransactionType.SPEND,
            point_type=point_type,
            amount=-spend_from_source,
            balance_after=balance_after,
            description=description,
            reference_id=reference_id,
            source=source,
            tag=source.tag,
            created_by=created_by,
        )
        transactions.append(txn)

    logger.info(
        "消费积分成功: wallet_id=%s, type=%s, amount=%s, tag=%s, description=%s",
        wallet.id,
        point_type,
        amount,
        tag_slug or "无",
        description,
    )

    return transactions


@transaction.atomic
def create_withdrawal_request(  # noqa: PLR0913
    owner: User | Organization,
    amount: int,
    real_name: str,
    phone: str,
    id_card: str,
    bank_name: str,
    bank_account: str,
    invoice_file=None,
) -> WithdrawalRequest:
    """
    创建提现申请.

    Args:
        owner: User 或 Organization 实例
        amount: 提现金额
        real_name: 真实姓名
        phone: 联系电话
        id_card: 身份证号
        bank_name: 银行名称
        bank_account: 银行账号
        invoice_file: 发票文件

    Returns:
        WithdrawalRequest: 提现申请记录

    Raises:
        InsufficientPointsError: 如果现金积分不足
        WithdrawalError: 如果有待处理的提现申请

    """
    if amount <= 0:
        msg = "提现金额必须大于 0"
        raise WithdrawalError(msg)

    wallet = get_or_create_wallet(owner)

    # 检查现金积分余额
    available = wallet.get_cash_balance()
    if available < amount:
        msg = f"现金积分不足：需要 {amount}，可用 {available}"
        raise InsufficientPointsError(msg)

    # 检查是否有待处理的提现申请
    pending_withdrawals = wallet.withdrawals.filter(
        status=WithdrawalStatus.PENDING
    ).count()
    if pending_withdrawals > 0:
        msg = "您有待处理的提现申请，请等待处理完成后再申请"
        raise WithdrawalError(msg)

    # 创建提现申请
    withdrawal = WithdrawalRequest.objects.create(
        wallet=wallet,
        amount=amount,
        status=WithdrawalStatus.PENDING,
        real_name=real_name,
        phone=phone,
        id_card=id_card,
        bank_name=bank_name,
        bank_account=bank_account,
        invoice_file=invoice_file,
    )

    logger.info(
        "创建提现申请: wallet_id=%s, amount=%s, withdrawal_id=%s",
        wallet.id,
        amount,
        withdrawal.id,
    )

    return withdrawal


@transaction.atomic
def approve_withdrawal(
    withdrawal_id: int,
    admin_user: User,
    note: str = "",
) -> WithdrawalRequest:
    """
    批准提现申请并扣除积分.

    Args:
        withdrawal_id: 提现申请 ID
        admin_user: 管理员用户
        note: 管理员备注

    Returns:
        WithdrawalRequest: 更新后的提现申请

    Raises:
        WithdrawalError: 如果提现申请状态无效
        InsufficientPointsError: 如果现金积分不足

    """
    try:
        withdrawal = WithdrawalRequest.objects.select_for_update().get(id=withdrawal_id)
    except WithdrawalRequest.DoesNotExist as err:
        msg = f"提现申请不存在: {withdrawal_id}"
        raise WithdrawalError(msg) from err

    if withdrawal.status != WithdrawalStatus.PENDING:
        msg = f"提现申请状态无效: {withdrawal.get_status_display()}"
        raise WithdrawalError(msg)

    wallet = withdrawal.wallet

    # 检查余额
    available = wallet.get_cash_balance()
    if available < withdrawal.amount:
        msg = f"现金积分不足：需要 {withdrawal.amount}，可用 {available}"
        raise InsufficientPointsError(msg)

    # 扣除积分
    transactions = spend_points(
        owner=wallet.owner,
        amount=withdrawal.amount,
        point_type=PointType.CASH,
        description=f"提现申请 #{withdrawal.id}",
        reference_id=f"withdrawal:{withdrawal.id}",
        created_by=admin_user,
    )

    # 更新提现申请状态
    withdrawal.status = WithdrawalStatus.APPROVED
    withdrawal.admin_note = note
    withdrawal.processed_by = admin_user
    withdrawal.processed_at = timezone.now()
    withdrawal.transaction = transactions[0] if transactions else None
    withdrawal.save()

    logger.info(
        "批准提现申请: withdrawal_id=%s, admin=%s",
        withdrawal.id,
        admin_user.username,
    )

    return withdrawal


@transaction.atomic
def complete_withdrawal(
    withdrawal_id: int,
    admin_user: User,
    note: str = "",
) -> WithdrawalRequest:
    """
    完成提现(打款后).

    Args:
        withdrawal_id: 提现申请 ID
        admin_user: 管理员用户
        note: 管理员备注

    Returns:
        WithdrawalRequest: 更新后的提现申请

    Raises:
        WithdrawalError: 如果提现申请状态无效

    """
    try:
        withdrawal = WithdrawalRequest.objects.select_for_update().get(id=withdrawal_id)
    except WithdrawalRequest.DoesNotExist as err:
        msg = f"提现申请不存在: {withdrawal_id}"
        raise WithdrawalError(msg) from err

    if withdrawal.status != WithdrawalStatus.APPROVED:
        msg = f"提现申请状态无效: {withdrawal.get_status_display()}"
        raise WithdrawalError(msg)

    withdrawal.status = WithdrawalStatus.COMPLETED
    if note:
        withdrawal.admin_note = f"{withdrawal.admin_note}\n{note}".strip()
    withdrawal.processed_by = admin_user
    withdrawal.processed_at = timezone.now()
    withdrawal.save()

    logger.info(
        "完成提现: withdrawal_id=%s, admin=%s",
        withdrawal.id,
        admin_user.username,
    )

    return withdrawal


@transaction.atomic
def reject_withdrawal(
    withdrawal_id: int,
    admin_user: User,
    reason: str,
) -> WithdrawalRequest:
    """
    拒绝提现申请.

    Args:
        withdrawal_id: 提现申请 ID
        admin_user: 管理员用户
        reason: 拒绝原因

    Returns:
        WithdrawalRequest: 更新后的提现申请

    Raises:
        WithdrawalError: 如果提现申请状态无效

    """
    try:
        withdrawal = WithdrawalRequest.objects.select_for_update().get(id=withdrawal_id)
    except WithdrawalRequest.DoesNotExist as err:
        msg = f"提现申请不存在: {withdrawal_id}"
        raise WithdrawalError(msg) from err

    if withdrawal.status != WithdrawalStatus.PENDING:
        msg = f"提现申请状态无效: {withdrawal.get_status_display()}"
        raise WithdrawalError(msg)

    withdrawal.status = WithdrawalStatus.REJECTED
    withdrawal.admin_note = reason
    withdrawal.processed_by = admin_user
    withdrawal.processed_at = timezone.now()
    withdrawal.save()

    logger.info(
        "拒绝提现申请: withdrawal_id=%s, admin=%s, reason=%s",
        withdrawal.id,
        admin_user.username,
        reason,
    )

    return withdrawal


@transaction.atomic
def cancel_withdrawal(
    withdrawal_id: int,
    user: User,
) -> WithdrawalRequest:
    """
    取消提现申请(用户自行取消).

    Args:
        withdrawal_id: 提现申请 ID
        user: 取消的用户

    Returns:
        WithdrawalRequest: 更新后的提现申请

    Raises:
        WithdrawalError: 如果提现申请状态无效或无权限

    """
    try:
        withdrawal = WithdrawalRequest.objects.select_for_update().get(id=withdrawal_id)
    except WithdrawalRequest.DoesNotExist as err:
        msg = f"提现申请不存在: {withdrawal_id}"
        raise WithdrawalError(msg) from err

    # 验证权限
    wallet = withdrawal.wallet
    owner = wallet.owner

    has_permission = False
    if isinstance(owner, User) and owner.pk == user.pk:
        has_permission = True
    elif isinstance(owner, Organization):
        # 检查用户是否是组织的管理员或所有者
        from accounts.models import OrganizationMembership

        membership = OrganizationMembership.objects.filter(
            user=user,
            organization=owner,
            role__in=[
                OrganizationMembership.Role.OWNER,
                OrganizationMembership.Role.ADMIN,
            ],
        ).first()
        if membership:
            has_permission = True

    if not has_permission:
        msg = "您没有权限取消此提现申请"
        raise WithdrawalError(msg)

    if withdrawal.status != WithdrawalStatus.PENDING:
        msg = f"只能取消待审核的提现申请，当前状态: {withdrawal.get_status_display()}"
        raise WithdrawalError(msg)

    withdrawal.status = WithdrawalStatus.CANCELLED
    withdrawal.save()

    logger.info(
        "取消提现申请: withdrawal_id=%s, user=%s",
        withdrawal.id,
        user.username,
    )

    return withdrawal
