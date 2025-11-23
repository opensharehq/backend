"""消息服务层."""

from django.contrib.auth import get_user_model
from django.db import transaction

from .models import Message, UserMessage

User = get_user_model()


class MessageError(Exception):
    """消息操作异常基类."""


@transaction.atomic
def send_message(  # noqa: PLR0913
    title,
    content,
    message_type=Message.MessageType.SYSTEM,
    sender=None,
    recipients=None,
    is_broadcast=False,
):
    """
    发送站内信.

    Args:
        title: 消息标题
        content: 消息内容 (支持 Markdown)
        message_type: 消息类型
        sender: 发送者 (User 对象, 可为 None)
        recipients: 接收者列表 (User 对象列表或 queryset)
        is_broadcast: 是否广播消息 (发送给全站用户)

    Returns:
        Message: 创建的消息对象

    Raises:
        MessageError: 当参数无效时

    """
    if not title:
        msg = "消息标题不能为空"
        raise MessageError(msg)

    if not content:
        msg = "消息内容不能为空"
        raise MessageError(msg)

    if is_broadcast and recipients:
        msg = "广播消息不能同时指定接收者"
        raise MessageError(msg)

    if not is_broadcast and not recipients:
        msg = "非广播消息必须指定接收者"
        raise MessageError(msg)

    # 创建消息
    message = Message.objects.create(
        title=title,
        content=content,
        message_type=message_type,
        sender=sender,
        is_broadcast=is_broadcast,
    )

    # 创建用户消息关联
    if is_broadcast:
        # 广播消息发送给所有用户（分批处理避免内存耗尽）
        batch_size = 1000
        user_messages = []
        users = User.objects.filter(is_active=True).iterator(chunk_size=batch_size)

        for user in users:
            user_messages.append(UserMessage(user=user, message=message))
            if len(user_messages) >= batch_size:
                UserMessage.objects.bulk_create(user_messages, ignore_conflicts=True)
                user_messages = []

        # 插入剩余的消息
        if user_messages:
            UserMessage.objects.bulk_create(user_messages, ignore_conflicts=True)
    else:
        # 发送给指定用户
        user_messages = [UserMessage(user=user, message=message) for user in recipients]
        UserMessage.objects.bulk_create(user_messages, ignore_conflicts=True)

    return message


def get_user_messages(
    user, include_deleted=False, only_unread=False, message_type=None
):
    """
    获取用户的消息列表.

    Args:
        user: 用户对象
        include_deleted: 是否包含已删除的消息
        only_unread: 是否仅返回未读消息
        message_type: 消息类型过滤

    Returns:
        QuerySet: UserMessage 查询集

    """
    queryset = UserMessage.objects.filter(user=user).select_related(
        "message", "message__sender"
    )

    if not include_deleted:
        queryset = queryset.filter(is_deleted=False)

    if only_unread:
        queryset = queryset.filter(is_read=False)

    if message_type:
        queryset = queryset.filter(message__message_type=message_type)

    return queryset


def get_unread_count(user, message_type=None):
    """
    获取用户未读消息数量.

    Args:
        user: 用户对象
        message_type: 消息类型过滤

    Returns:
        int: 未读消息数量

    """
    queryset = UserMessage.objects.filter(user=user, is_read=False, is_deleted=False)

    if message_type:
        queryset = queryset.filter(message__message_type=message_type)

    return queryset.count()


@transaction.atomic
def mark_as_read(user, message_ids=None):
    """
    标记消息为已读.

    Args:
        user: 用户对象
        message_ids: 消息 ID 列表 (None 表示标记所有未读消息)

    Returns:
        int: 标记的消息数量

    """
    queryset = UserMessage.objects.filter(user=user, is_read=False, is_deleted=False)

    if message_ids:
        queryset = queryset.filter(message_id__in=message_ids)

    from django.utils import timezone

    updated = queryset.update(is_read=True, read_at=timezone.now())

    return updated


@transaction.atomic
def mark_as_unread(user, message_ids):
    """
    标记消息为未读.

    Args:
        user: 用户对象
        message_ids: 消息 ID 列表

    Returns:
        int: 标记的消息数量

    """
    queryset = UserMessage.objects.filter(
        user=user, is_read=True, is_deleted=False, message_id__in=message_ids
    )

    updated = queryset.update(is_read=False, read_at=None)

    return updated


@transaction.atomic
def delete_messages(user, message_ids):
    """
    删除消息 (软删除).

    Args:
        user: 用户对象
        message_ids: 消息 ID 列表

    Returns:
        int: 删除的消息数量

    """
    queryset = UserMessage.objects.filter(
        user=user, is_deleted=False, message_id__in=message_ids
    )

    updated = queryset.update(is_deleted=True)

    return updated


def get_message_stats(user):
    """
    获取用户消息统计.

    Args:
        user: 用户对象

    Returns:
        dict: 统计信息

    """
    total = UserMessage.objects.filter(user=user, is_deleted=False).count()
    unread = UserMessage.objects.filter(
        user=user, is_deleted=False, is_read=False
    ).count()

    # 按类型统计未读消息
    from django.db.models import Count

    type_stats = (
        UserMessage.objects.filter(user=user, is_deleted=False, is_read=False)
        .values("message__message_type")
        .annotate(count=Count("id"))
    )

    type_counts = {stat["message__message_type"]: stat["count"] for stat in type_stats}

    return {
        "total": total,
        "unread": unread,
        "read": total - unread,
        "type_counts": type_counts,
    }
