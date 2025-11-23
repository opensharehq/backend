"""Views for the points app."""

import json
from collections import defaultdict
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import F, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from points.forms import WithdrawalRequestForm
from points.models import PointSource, Tag, WithdrawalRequest
from points.services import (
    PointSourceNotWithdrawableError,
    WithdrawalAmountError,
    WithdrawalData,
    WithdrawalError,
    cancel_withdrawal,
    create_withdrawal_request,
)

TREND_DAYS = 30


def _trend_date_range():
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=TREND_DAYS - 1)
    return start_date, end_date


def _build_trend_labels(start_date):
    return [
        (start_date + timedelta(days=offset)).strftime("%m/%d")
        for offset in range(TREND_DAYS)
    ]


def _user_tags(user):
    return Tag.objects.filter(point_sources__user=user).distinct().order_by("name")


def _build_tag_trends(user, tags, start_date):
    """
    Build per-tag trend datasets via two aggregates and one balance lookup.

    Keeps query count O(1) regardless of标签数量。
    """
    tag_ids = list(tags.values_list("id", flat=True))

    earn_rows = (
        user.point_sources.filter(created_at__date__gte=start_date, tags__in=tag_ids)
        .annotate(
            date=TruncDate("created_at"), tag_id=F("tags__id"), tag_name=F("tags__name")
        )
        .values("tag_id", "tag_name", "date")
        .annotate(total=Sum("initial_points"))
    )

    spend_rows = (
        user.point_transactions.filter(
            created_at__date__gte=start_date,
            transaction_type="SPEND",
            consumed_sources__tags__in=tag_ids,
        )
        .annotate(
            date=TruncDate("created_at"),
            tag_id=F("consumed_sources__tags__id"),
            tag_name=F("consumed_sources__tags__name"),
        )
        .values("tag_id", "tag_name", "date")
        .annotate(total=Sum("points"))
    )

    balances = {
        row["tags__id"]: row["total"]
        for row in user.point_sources.filter(remaining_points__gt=0, tags__in=tag_ids)
        .values("tags__id")
        .annotate(total=Sum("remaining_points"))
    }

    daily = defaultdict(lambda: defaultdict(int))
    tag_names = {}

    for row in earn_rows:
        daily[row["tag_id"]][row["date"]] += row["total"]
        tag_names[row["tag_id"]] = row["tag_name"]

    for row in spend_rows:
        daily[row["tag_id"]][row["date"]] += row["total"]
        tag_names[row["tag_id"]] = row["tag_name"]

    datasets = []
    for tag in tags:
        tag_id = tag.id
        tag_daily = daily.get(tag_id, {})
        current_points = balances.get(tag_id, 0)
        total_change = sum(tag_daily.values())
        starting_points = current_points - total_change

        cumulative = starting_points
        trend_data = []
        for offset in range(TREND_DAYS):
            current_date = start_date + timedelta(days=offset)
            cumulative += tag_daily.get(current_date, 0)
            trend_data.append(cumulative)

        if current_points > 0 or total_change != 0:
            datasets.append({"label": tag.name, "data": trend_data})

    return datasets


@login_required
def my_points(request):
    """
    Display user's points information.

    Shows:
    - Total points
    - Points by tag
    - Point sources
    - Transaction history

    """
    user = request.user

    # Get points by tag
    points_by_tag = user.get_points_by_tag()

    # Get active point sources (with remaining points)
    active_sources = user.point_sources.filter(remaining_points__gt=0).order_by(
        "-created_at"
    )

    # Get transaction history with pagination
    transactions = user.point_transactions.select_related().order_by("-created_at")
    paginator = Paginator(transactions, 20)  # 20 transactions per page
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    start_date, _ = _trend_date_range()
    trend_labels = _build_trend_labels(start_date)
    user_tags = _user_tags(user)
    trend_datasets = _build_tag_trends(user, user_tags, start_date)

    context = {
        "total_points": user.total_points,
        "points_by_tag": points_by_tag,
        "active_sources": active_sources,
        "page_obj": page_obj,
        "trend_labels_json": json.dumps(trend_labels),
        "trend_datasets_json": json.dumps(trend_datasets),
    }

    return render(request, "points/my_points.html", context)


@login_required
def withdrawal_create(request, point_source_id):
    """
    Create a withdrawal request for a specific point source.

    Args:
        request: HTTP request
        point_source_id: ID of the point source to withdraw from

    """
    # Get the point source and verify it belongs to the user
    point_source = get_object_or_404(PointSource, id=point_source_id, user=request.user)

    # Check if the point source is withdrawable
    if not point_source.is_withdrawable:
        messages.error(request, "该积分来源不支持提现。")
        return redirect("points:my_points")

    # Check if there are remaining points
    if point_source.remaining_points <= 0:
        messages.error(request, "该积分来源没有可提现的积分。")
        return redirect("points:my_points")

    if request.method == "POST":
        form = WithdrawalRequestForm(request.POST, point_source=point_source)
        if form.is_valid():
            try:
                withdrawal_data = WithdrawalData(
                    real_name=form.cleaned_data["real_name"],
                    id_number=form.cleaned_data["id_number"],
                    phone_number=form.cleaned_data["phone_number"],
                    bank_name=form.cleaned_data["bank_name"],
                    bank_account=form.cleaned_data["bank_account"],
                )
                withdrawal_request = create_withdrawal_request(
                    user=request.user,
                    point_source_id=point_source.id,
                    points=form.cleaned_data["points"],
                    withdrawal_data=withdrawal_data,
                )
                messages.success(
                    request,
                    f"提现申请已提交！申请编号: #{withdrawal_request.id}，请等待审核。",
                )
                return redirect("points:withdrawal_list")
            except (
                PointSource.DoesNotExist,
                PointSourceNotWithdrawableError,
                WithdrawalAmountError,
            ) as e:
                messages.error(request, str(e))
    else:
        form = WithdrawalRequestForm(point_source=point_source)

    context = {
        "form": form,
        "point_source": point_source,
    }

    return render(request, "points/withdrawal_create.html", context)


@login_required
def withdrawal_list(request):
    """
    Display user's withdrawal requests.

    Shows all withdrawal requests with their status.

    """
    # Get user's withdrawal requests with pagination
    withdrawals = request.user.withdrawal_requests.select_related(
        "point_source", "processed_by"
    ).order_by("-created_at")

    paginator = Paginator(withdrawals, 20)  # 20 requests per page
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
    }

    return render(request, "points/withdrawal_list.html", context)


@login_required
def withdrawal_detail(request, withdrawal_id):
    """
    Display details of a specific withdrawal request.

    Args:
        request: HTTP request
        withdrawal_id: ID of the withdrawal request

    """
    withdrawal = get_object_or_404(
        WithdrawalRequest.objects.select_related("point_source", "processed_by"),
        id=withdrawal_id,
        user=request.user,
    )

    context = {
        "withdrawal": withdrawal,
    }

    return render(request, "points/withdrawal_detail.html", context)


@login_required
def withdrawal_cancel(request, withdrawal_id):
    """
    Cancel a pending withdrawal request.

    Args:
        request: HTTP request
        withdrawal_id: ID of the withdrawal request

    """
    withdrawal = get_object_or_404(
        WithdrawalRequest, id=withdrawal_id, user=request.user
    )

    if request.method == "POST":
        try:
            cancel_withdrawal(withdrawal)
            messages.success(request, "提现申请已取消。")
            return redirect("points:withdrawal_list")
        except WithdrawalError as e:
            messages.error(request, str(e))
            return redirect("points:withdrawal_detail", withdrawal_id=withdrawal_id)

    # If not POST, redirect to detail page
    return redirect("points:withdrawal_detail", withdrawal_id=withdrawal_id)


@login_required
def recharge(request, point_source_id):
    """
    Display recharge page for a specific point source.

    Args:
        request: HTTP request
        point_source_id: ID of the point source to recharge

    """
    # Get the point source and verify it belongs to the user
    point_source = get_object_or_404(PointSource, id=point_source_id, user=request.user)

    # Check if the point source allows recharge (based on settings or tags)
    if not point_source.is_rechargeable:
        messages.error(request, "该积分池不支持充值。")
        return redirect("points:my_points")

    context = {
        "point_source": point_source,
    }

    return render(request, "points/recharge.html", context)


@login_required
def batch_withdrawal(request):
    """
    Batch withdrawal page for multiple point sources.

    Shows all withdrawable point sources and allows user to create
    multiple withdrawal requests at once.

    """
    from points.forms import BatchWithdrawalInfoForm
    from points.services import create_batch_withdrawal_requests

    # Get all withdrawable point sources for the user
    withdrawable_sources = [
        source
        for source in request.user.point_sources.filter(
            remaining_points__gt=0
        ).prefetch_related("tags")
        if source.is_withdrawable
    ]

    # Check if user has any withdrawable sources
    if not withdrawable_sources:
        messages.warning(request, "您没有可提现的积分池。")
        return redirect("points:my_points")

    if request.method == "POST":
        form = BatchWithdrawalInfoForm(request.POST)

        # Collect withdrawal amounts from POST data
        withdrawal_amounts = {}
        has_any_amount = False

        for source in withdrawable_sources:
            field_name = f"points_{source.id}"
            points_str = request.POST.get(field_name, "").strip()

            if points_str:
                try:
                    points = int(points_str)
                    if points > 0:
                        # Validate amount doesn't exceed remaining points
                        if points > source.remaining_points:
                            messages.error(
                                request,
                                f"积分池 #{source.id} 的提现数量不能超过剩余积分 {source.remaining_points}。",
                            )
                            form.add_error(
                                None,
                                f"积分池 #{source.id} 的提现数量不能超过剩余积分。",
                            )
                        else:
                            withdrawal_amounts[source.id] = points
                            has_any_amount = True
                except ValueError:
                    messages.error(
                        request, f"积分池 #{source.id} 的提现数量格式不正确。"
                    )
                    form.add_error(None, f"积分池 #{source.id} 的提现数量必须是整数。")

        # Validate that at least one amount is provided
        if not has_any_amount:
            form.add_error(None, "至少需要为一个积分池设置提现数量。")

        if form.is_valid() and has_any_amount:
            try:
                withdrawal_data = WithdrawalData(
                    real_name=form.cleaned_data["real_name"],
                    id_number=form.cleaned_data["id_number"],
                    phone_number=form.cleaned_data["phone_number"],
                    bank_name=form.cleaned_data["bank_name"],
                    bank_account=form.cleaned_data["bank_account"],
                )

                withdrawal_requests = create_batch_withdrawal_requests(
                    user=request.user,
                    withdrawal_amounts=withdrawal_amounts,
                    withdrawal_data=withdrawal_data,
                )

                messages.success(
                    request,
                    f"批量提现申请已提交！共创建了 {len(withdrawal_requests)} 个提现申请，总计 {sum(wr.points for wr in withdrawal_requests)} 积分。请等待审核。",
                )
                return redirect("points:withdrawal_list")
            except (
                PointSource.DoesNotExist,
                PointSourceNotWithdrawableError,
                WithdrawalAmountError,
                WithdrawalError,
            ) as e:
                messages.error(request, str(e))
    else:
        form = BatchWithdrawalInfoForm()

    context = {
        "form": form,
        "withdrawable_sources": withdrawable_sources,
    }

    return render(request, "points/batch_withdrawal.html", context)
