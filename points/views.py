"""Views for points application."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import Organization, OrganizationMembership

from . import services
from .forms import WithdrawalRequestForm
from .models import PointType, WithdrawalStatus


@login_required
def user_wallet_view(request):
    """用户钱包页面."""
    user = request.user
    balance = services.get_detailed_balance(user)

    # 获取最近的交易记录
    wallet = services.get_or_create_wallet(user)
    recent_transactions = wallet.transactions.select_related("tag").order_by(
        "-created_at"
    )[:10]

    context = {
        "balance": balance,
        "recent_transactions": recent_transactions,
        "wallet": wallet,
    }
    return render(request, "points/user_wallet.html", context)


@login_required
def user_transactions_view(request):
    """用户交易记录页面."""
    user = request.user
    wallet = services.get_or_create_wallet(user)

    # 获取筛选参数
    point_type = request.GET.get("point_type", "")
    transaction_type = request.GET.get("transaction_type", "")

    # 构建查询
    transactions = wallet.transactions.select_related("tag").order_by("-created_at")

    if point_type:
        transactions = transactions.filter(point_type=point_type)

    if transaction_type:
        transactions = transactions.filter(transaction_type=transaction_type)

    # 分页
    paginator = Paginator(transactions, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "point_type": point_type,
        "transaction_type": transaction_type,
        "point_types": PointType.choices,
        "transaction_types": [
            ("earn", "获取"),
            ("spend", "消费"),
            ("withdraw", "提现"),
        ],
    }
    return render(request, "points/user_transactions.html", context)


@login_required
def create_withdrawal_view(request):
    """创建提现申请页面."""
    user = request.user
    balance = services.get_detailed_balance(user)

    # 检查是否有待处理的提现申请
    wallet = services.get_or_create_wallet(user)
    has_pending = wallet.withdrawals.filter(status=WithdrawalStatus.PENDING).exists()

    if request.method == "POST":
        form = WithdrawalRequestForm(user, request.POST)
        if form.is_valid():
            try:
                withdrawal = services.create_withdrawal_request(
                    owner=user,
                    amount=form.cleaned_data["amount"],
                    real_name=form.cleaned_data["real_name"],
                    phone=form.cleaned_data["phone"],
                    bank_name=form.cleaned_data["bank_name"],
                    bank_account=form.cleaned_data["bank_account"],
                )
                messages.success(
                    request,
                    f"提现申请已提交，申请金额: {withdrawal.amount}，请等待审核。",
                )
                return redirect("points:withdrawal_list")
            except (
                services.InsufficientPointsError,
                services.WithdrawalError,
            ) as e:
                messages.error(request, str(e))
    else:
        form = WithdrawalRequestForm(user)

    context = {
        "form": form,
        "balance": balance,
        "has_pending": has_pending,
    }
    return render(request, "points/withdrawal_form.html", context)


@login_required
def withdrawal_list_view(request):
    """提现记录列表页面."""
    user = request.user
    wallet = services.get_or_create_wallet(user)

    withdrawals = wallet.withdrawals.order_by("-created_at")

    # 分页
    paginator = Paginator(withdrawals, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
    }
    return render(request, "points/withdrawal_list.html", context)


@login_required
def cancel_withdrawal_view(request, pk):
    """取消提现申请."""
    if request.method == "POST":
        try:
            services.cancel_withdrawal(pk, request.user)
            messages.success(request, "提现申请已取消")
        except services.WithdrawalError as e:
            messages.error(request, str(e))

    return redirect("points:withdrawal_list")


@login_required
def org_wallet_view(request, slug):
    """组织钱包页面."""
    org = get_object_or_404(Organization, slug=slug)

    # 检查用户是否是组织成员
    membership = OrganizationMembership.objects.filter(
        user=request.user,
        organization=org,
    ).first()

    if not membership:
        messages.error(request, "您不是该组织的成员")
        return redirect("homepage:index")

    balance = services.get_detailed_balance(org)

    # 获取最近的交易记录
    wallet = services.get_or_create_wallet(org)
    recent_transactions = wallet.transactions.select_related("tag").order_by(
        "-created_at"
    )[:10]

    context = {
        "org": org,
        "membership": membership,
        "balance": balance,
        "recent_transactions": recent_transactions,
        "wallet": wallet,
        "can_withdraw": membership.is_admin_or_owner(),
    }
    return render(request, "points/organization_wallet.html", context)


@login_required
def org_transactions_view(request, slug):
    """组织交易记录页面."""
    org = get_object_or_404(Organization, slug=slug)

    # 检查用户是否是组织成员
    membership = OrganizationMembership.objects.filter(
        user=request.user,
        organization=org,
    ).first()

    if not membership:
        messages.error(request, "您不是该组织的成员")
        return redirect("homepage:index")

    wallet = services.get_or_create_wallet(org)

    # 获取筛选参数
    point_type = request.GET.get("point_type", "")
    transaction_type = request.GET.get("transaction_type", "")

    # 构建查询
    transactions = wallet.transactions.select_related("tag").order_by("-created_at")

    if point_type:
        transactions = transactions.filter(point_type=point_type)

    if transaction_type:
        transactions = transactions.filter(transaction_type=transaction_type)

    # 分页
    paginator = Paginator(transactions, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "org": org,
        "membership": membership,
        "page_obj": page_obj,
        "point_type": point_type,
        "transaction_type": transaction_type,
        "point_types": PointType.choices,
        "transaction_types": [
            ("earn", "获取"),
            ("spend", "消费"),
            ("withdraw", "提现"),
        ],
    }
    return render(request, "points/organization_transactions.html", context)


@login_required
def org_create_withdrawal_view(request, slug):
    """组织创建提现申请页面."""
    org = get_object_or_404(Organization, slug=slug)

    # 检查用户是否是组织管理员或所有者
    membership = OrganizationMembership.objects.filter(
        user=request.user,
        organization=org,
        role__in=[OrganizationMembership.Role.OWNER, OrganizationMembership.Role.ADMIN],
    ).first()

    if not membership:
        messages.error(request, "只有组织管理员可以申请提现")
        return redirect("points:org_wallet", slug=slug)

    balance = services.get_detailed_balance(org)

    # 检查是否有待处理的提现申请
    wallet = services.get_or_create_wallet(org)
    has_pending = wallet.withdrawals.filter(status=WithdrawalStatus.PENDING).exists()

    if request.method == "POST":
        form = WithdrawalRequestForm(org, request.POST)
        if form.is_valid():
            try:
                withdrawal = services.create_withdrawal_request(
                    owner=org,
                    amount=form.cleaned_data["amount"],
                    real_name=form.cleaned_data["real_name"],
                    phone=form.cleaned_data["phone"],
                    bank_name=form.cleaned_data["bank_name"],
                    bank_account=form.cleaned_data["bank_account"],
                )
                messages.success(
                    request,
                    f"提现申请已提交，申请金额: {withdrawal.amount}，请等待审核。",
                )
                return redirect("points:org_wallet", slug=slug)
            except (
                services.InsufficientPointsError,
                services.WithdrawalError,
            ) as e:
                messages.error(request, str(e))
    else:
        form = WithdrawalRequestForm(org)

    context = {
        "org": org,
        "form": form,
        "balance": balance,
        "has_pending": has_pending,
    }
    return render(request, "points/organization_withdrawal_form.html", context)
