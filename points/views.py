"""Views for points application."""

import json
from datetime import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView

from accounts.models import Organization, OrganizationMembership

from . import services
from .allocation_services import AllocationService
from .forms import WithdrawalRequestForm
from .models import PointAllocation, PointSource, PointType, Tag, WithdrawalStatus


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
        form = WithdrawalRequestForm(user, request.POST, request.FILES)
        if form.is_valid():
            try:
                withdrawal = services.create_withdrawal_request(
                    owner=user,
                    amount=form.cleaned_data["amount"],
                    real_name=form.cleaned_data["real_name"],
                    phone=form.cleaned_data["phone"],
                    id_card=form.cleaned_data["id_card"],
                    bank_name=form.cleaned_data["bank_name"],
                    bank_account=form.cleaned_data["bank_account"],
                    invoice_file=form.cleaned_data["invoice_file"],
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
        form = WithdrawalRequestForm(org, request.POST, request.FILES)
        if form.is_valid():
            try:
                withdrawal = services.create_withdrawal_request(
                    owner=org,
                    amount=form.cleaned_data["amount"],
                    real_name=form.cleaned_data["real_name"],
                    phone=form.cleaned_data["phone"],
                    id_card=form.cleaned_data["id_card"],
                    bank_name=form.cleaned_data["bank_name"],
                    bank_account=form.cleaned_data["bank_account"],
                    invoice_file=form.cleaned_data["invoice_file"],
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


# ============================================================================
# 积分分配相关视图
# ============================================================================


class PointAllocationConfigView(LoginRequiredMixin, TemplateView):
    """积分分配配置页面."""

    template_name = "points/allocation_config.html"

    def get_context_data(self, **kwargs):
        """Get context data."""
        context = super().get_context_data(**kwargs)

        user = self.request.user

        # 获取用户可用的积分池（按类型和标签分组汇总）
        user_pools = self._get_aggregated_pools(
            wallet_content_type=ContentType.objects.get_for_model(user),
            wallet_object_id=user.id,
            wallet_owner=user,
        )

        # 获取用户所在组织的积分池（如果是 OWNER/ADMIN）
        org_pools = []
        memberships = user.organization_memberships.filter(role__in=["owner", "admin"])
        for membership in memberships:
            org_content_type = ContentType.objects.get_for_model(
                membership.organization
            )
            pools = self._get_aggregated_pools(
                wallet_content_type=org_content_type,
                wallet_object_id=membership.organization.id,
                wallet_owner=membership.organization,
            )
            org_pools.extend(pools)

        context["user_pools"] = user_pools
        context["org_pools"] = org_pools

        return context

    def _get_aggregated_pools(
        self, wallet_content_type, wallet_object_id, wallet_owner=None
    ):
        """
        获取按类型和标签分组汇总的积分池.

        Args:
            wallet_content_type: 钱包的 ContentType
            wallet_object_id: 钱包所有者的 ID
            wallet_owner: 钱包所有者对象 (用于组织池显示名称)

        Returns:
            list: 包含分组汇总后积分池信息的字典列表

        """
        from django.db.models import Min, Sum

        from .models import Tag

        # 查询所有有余额的 PointSource
        sources = PointSource.objects.filter(
            wallet__content_type=wallet_content_type,
            wallet__object_id=wallet_object_id,
            remaining_amount__gt=0,
        )

        # 按 point_type 和 tag 分组汇总
        aggregated = (
            sources.values("point_type", "tag")
            .annotate(
                total_remaining=Sum("remaining_amount"),
                min_id=Min("id"),
            )
            .order_by("point_type", "tag")
        )

        # 构建结果列表
        pools = []
        for item in aggregated:
            point_type = item["point_type"]
            tag_id = item["tag"]
            total_remaining = item["total_remaining"]

            # 获取 tag 对象（如果有）
            tag = Tag.objects.get(id=tag_id) if tag_id else None

            # 构建虚拟的积分池对象（字典）
            pool = {
                "id": item["min_id"],
                "point_type": point_type,
                "get_point_type_display": dict(PointType.choices)[point_type],
                "remaining_amount": total_remaining,
                "tag": tag,
                "wallet": {"owner": wallet_owner} if wallet_owner else None,
            }
            pools.append(pool)

        return pools


class PoolListAPIView(LoginRequiredMixin, View):
    """API: 获取可用积分池列表."""

    def get(self, request):
        """Get available point pools."""
        user = request.user

        # 获取用户积分池
        user_content_type = ContentType.objects.get_for_model(user)
        user_pools = PointSource.objects.filter(
            wallet__content_type=user_content_type,
            wallet__object_id=user.id,
            remaining_amount__gt=0,
        ).select_related("tag")

        # 获取组织积分池
        org_pools = []
        memberships = user.organization_memberships.filter(role__in=["owner", "admin"])
        for membership in memberships:
            org_content_type = ContentType.objects.get_for_model(
                membership.organization
            )
            pools = PointSource.objects.filter(
                wallet__content_type=org_content_type,
                wallet__object_id=membership.organization.id,
                remaining_amount__gt=0,
            ).select_related("tag")
            org_pools.extend(pools)

        # 序列化数据
        user_pools_data = [
            {
                "id": pool.id,
                "type": pool.point_type,
                "type_display": pool.get_point_type_display(),
                "balance": pool.remaining_amount,
                "tag": pool.tag.slug if pool.tag else None,
                "tag_name": pool.tag.name if pool.tag else None,
                "owner": "个人",
            }
            for pool in user_pools
        ]

        org_pools_data = [
            {
                "id": pool.id,
                "type": pool.point_type,
                "type_display": pool.get_point_type_display(),
                "balance": pool.remaining_amount,
                "tag": pool.tag.slug if pool.tag else None,
                "tag_name": pool.tag.name if pool.tag else None,
                "owner": str(pool.wallet.owner),
            }
            for pool in org_pools
        ]

        return JsonResponse(
            {"user_pools": user_pools_data, "org_pools": org_pools_data}
        )


class TagListAPIView(LoginRequiredMixin, View):
    """API: 获取标签列表."""

    def get(self, request):
        """Get tag list."""
        tag_type = request.GET.get("type")  # org/repo/user
        is_official = request.GET.get("official")  # true/false

        tags = Tag.objects.all()

        if tag_type:
            tags = tags.filter(tag_type=tag_type)

        if is_official is not None:
            tags = tags.filter(is_official=is_official == "true")

        # Future enhancement: include user/org private tags.

        tags_data = [
            {
                "slug": tag.slug,
                "name": tag.name,
                "type": tag.tag_type,
                "is_official": tag.is_official,
                "entity_identifier": tag.entity_identifier,
            }
            for tag in tags
        ]

        return JsonResponse({"tags": tags_data})


class ContributionPreviewAPIView(LoginRequiredMixin, View):
    """API: 预览贡献度列表."""

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        """Dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request):
        """Preview contributions."""
        try:
            from chdb import services as chdb_services

            data = json.loads(request.body)

            # 创建临时的 PointAllocation 对象
            allocation = PointAllocation(
                project_scope=data["project_scope"],
                user_scope=data.get("user_scope"),
                start_month=datetime.strptime(data["start_month"], "%Y-%m-%d").date(),
                end_month=datetime.strptime(data["end_month"], "%Y-%m-%d").date(),
                total_amount=data["total_amount"],
                adjustment_ratio=data.get("adjustment_ratio", 1.0),
                individual_adjustments=data.get("individual_adjustments", {}),
            )

            # 预览
            preview = AllocationService.preview_allocation(allocation)

            # 转换 Decimal 为 float 以便 JSON 序列化
            for item in preview:
                if "contribution_score" in item:
                    item["contribution_score"] = float(item["contribution_score"])

            # 查询标签平台信息（如果有项目标签）
            label_platforms_info = {}
            project_tags = data.get("project_scope", {}).get("tags", [])
            if project_tags:
                label_platforms_info = chdb_services.get_label_users(project_tags)

            return JsonResponse(
                {
                    "contributions": preview,
                    "label_platforms_info": label_platforms_info,
                    "total_points": sum(c["adjusted_points"] for c in preview),
                    "total_recipients": len(preview),
                }
            )
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)


class AllocationExecuteAPIView(LoginRequiredMixin, View):
    """API: 执行积分分配."""

    @method_decorator(csrf_exempt)
    def dispatch(self, *args, **kwargs):
        """Dispatch."""
        return super().dispatch(*args, **kwargs)

    def post(self, request):
        """Execute allocation."""
        try:
            data = json.loads(request.body)

            # 创建 PointAllocation 记录
            user_content_type = ContentType.objects.get_for_model(request.user)
            allocation = PointAllocation.objects.create(
                initiator_type=user_content_type,
                initiator_id=request.user.id,
                source_pool_id=data["pool_id"],
                total_amount=data["total_amount"],
                project_scope=data["project_scope"],
                user_scope=data.get("user_scope"),
                start_month=datetime.strptime(data["start_month"], "%Y-%m-%d").date(),
                end_month=datetime.strptime(data["end_month"], "%Y-%m-%d").date(),
                adjustment_ratio=data.get("adjustment_ratio", 1.0),
                individual_adjustments=data.get("individual_adjustments", {}),
            )

            # 执行
            result = AllocationService.execute_allocation(allocation)

            return JsonResponse({"allocation_id": allocation.id, **result})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)


class TagSearchAPIView(LoginRequiredMixin, View):
    """API: 搜索标签 (ClickHouse opensource.labels 表)."""

    def get(self, request):
        """Search tags by keyword."""
        from chdb import services as chdb_services

        keyword = request.GET.get("q", "").strip()

        if not keyword:
            return JsonResponse({"tags": []})

        try:
            tags = chdb_services.search_tags(keyword)
            return JsonResponse({"tags": tags})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
