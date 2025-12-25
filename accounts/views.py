"""Views for user authentication and profile management."""

import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import (
    authenticate,
    get_user_model,
    login,
    logout,
    update_session_auth_hash,
)
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.forms import inlineformset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_decode
from django.views.decorators.http import require_POST
from social_django.models import UserSocialAuth

from messages import services as inbox_services
from messages.models import Message as InboxMessage
from points.services import InsufficientPointsError
from shop.models import Redemption, ShopItem
from shop.services import RedemptionError, redeem_item

from .forms import (
    AccountMergeRequestForm,
    ChangeEmailForm,
    CustomPasswordChangeForm,
    EducationForm,
    PasswordResetConfirmForm,
    PasswordResetRequestForm,
    ProfileForm,
    ShippingAddressForm,
    SignUpForm,
    WorkExperienceForm,
)
from .models import (
    AccountMergeRequest,
    Education,
    Organization,
    OrganizationMembership,
    ShippingAddress,
    UserProfile,
    WorkExperience,
)
from .services import AccountMergeError, perform_merge
from .tasks import send_password_reset_email


def accounts_index(request):
    """Redirect to sign-in or profile based on authentication status."""
    if request.user.is_authenticated:
        return redirect("accounts:profile")
    return redirect("accounts:sign_in")


def sign_in_view(request):
    """Display sign-in page with email, username, and GitHub auth options."""
    error_message = None
    if request.user.is_authenticated:
        return redirect("accounts:profile")

    if request.method == "POST":
        login_id = request.POST.get("login-id") or ""
        password = request.POST.get("password") or ""

        UserModel = get_user_model()
        username_match = UserModel.objects.filter(username=login_id).first()
        email_user = None
        if "@" in login_id:
            email_qs = UserModel.objects.filter(email=login_id)
            email_user = email_qs.filter(is_active=True).first() or email_qs.first()

        user = authenticate(request, username=login_id, password=password)
        if not user and email_user:
            user = authenticate(
                request, username=email_user.username, password=password
            )

        candidate_user = username_match or email_user

        if not user:
            if (
                username_match
                and username_match.merged_into_id
                and login_id == username_match.username
            ):
                target = username_match.merged_into
                target_label = target.email or target.username
                error_message = f"该账号已合并到 {target_label}，请使用目标账号登录"
            elif candidate_user and not candidate_user.is_active:
                error_message = "账号已被停用，请联系管理员"
            else:
                error_message = "用户名或密码错误，请重试"
            messages.error(request, error_message)
        elif not user.is_active:
            error_message = "账号已被停用，请联系管理员"
            messages.error(request, error_message)
        else:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, "登录成功")
            raw_next = request.GET.get("next")
            next_url = (
                raw_next
                if raw_next
                and url_has_allowed_host_and_scheme(
                    url=raw_next,
                    allowed_hosts=settings.ALLOWED_HOSTS,
                    require_https=request.is_secure(),
                )
                else reverse("accounts:profile")
            )
            return redirect(next_url)

    return render(request, "sign_in.html", {"error_message": error_message})


def sign_up_view(request):
    """Display and handle sign-up form."""
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, "注册成功！欢迎加入 Open Share")
            return redirect("homepage:index")
    else:
        form = SignUpForm()

    return render(request, "sign_up.html", {"form": form})


@login_required
def profile_view(request):
    """Display user profile page."""
    from labels.models import Label, OwnerType

    profile, _created = UserProfile.objects.get_or_create(user=request.user)
    # 获取用户拥有的标签数量
    label_count = Label.objects.filter(
        owner_type=OwnerType.USER, owner_id=request.user.id
    ).count()
    return render(
        request, "profile.html", {"profile": profile, "label_count": label_count}
    )


def _get_profile_edit_forms(
    request,
    profile,
    work_formset_factory,
    education_formset_factory,
):
    """Return bound or unbound forms for the profile edit view."""
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=profile)
        work_formset = work_formset_factory(request.POST, instance=profile)
        education_formset = education_formset_factory(request.POST, instance=profile)
        return form, work_formset, education_formset, True

    form = ProfileForm(instance=profile)
    work_formset = work_formset_factory(instance=profile)
    education_formset = education_formset_factory(instance=profile)
    return form, work_formset, education_formset, False


def _save_profile_form(form):
    """Persist profile changes when the form has updates."""
    if not form.has_changed():
        return False
    form.save()
    return True


def _persist_inline_formset(formset):
    """Save inline formset changes, including deletions."""
    changed = False
    for instance in formset.save(commit=False):
        instance.save()
        changed = True

    for instance in formset.deleted_objects:
        instance.delete()
        changed = True

    if hasattr(formset, "save_m2m"):
        formset.save_m2m()

    return changed


@login_required
def profile_edit_view(request):
    """Handle profile editing with Bootstrap 5 form."""
    profile, _created = UserProfile.objects.get_or_create(user=request.user)

    WorkExperienceFormSet = inlineformset_factory(
        UserProfile,
        WorkExperience,
        form=WorkExperienceForm,
        extra=0,
        can_delete=True,
    )

    EducationFormSet = inlineformset_factory(
        UserProfile,
        Education,
        form=EducationForm,
        extra=0,
        can_delete=True,
    )

    # Create ShippingAddress formset using User model (not UserProfile)
    ShippingAddressFormSet = inlineformset_factory(
        get_user_model(),
        ShippingAddress,
        form=ShippingAddressForm,
        extra=0,
        can_delete=True,
    )

    if request.method == "POST":
        form = ProfileForm(request.POST, instance=profile)
        work_formset = WorkExperienceFormSet(request.POST, instance=profile)
        education_formset = EducationFormSet(request.POST, instance=profile)
        address_formset = ShippingAddressFormSet(request.POST, instance=request.user)
        is_post = True
    else:
        form = ProfileForm(instance=profile)
        work_formset = WorkExperienceFormSet(instance=profile)
        education_formset = EducationFormSet(instance=profile)
        address_formset = ShippingAddressFormSet(instance=request.user)
        is_post = False

    if is_post and all(
        form_like.is_valid()
        for form_like in (form, work_formset, education_formset, address_formset)
    ):
        form_changed = _save_profile_form(form)
        work_changed = _persist_inline_formset(work_formset)
        education_changed = _persist_inline_formset(education_formset)
        address_changed = _persist_inline_formset(address_formset)

        if form_changed or work_changed or education_changed or address_changed:
            messages.success(request, "个人资料已更新")
        else:
            messages.info(request, "未检测到任何更改")

        return redirect("accounts:profile")

    return render(
        request,
        "profile_edit.html",
        {
            "form": form,
            "work_formset": work_formset,
            "education_formset": education_formset,
            "address_formset": address_formset,
        },
    )


@login_required
def logout_view(request):
    """Log out the current user and redirect to homepage."""
    logout(request)
    messages.success(request, "您已成功退出登录")
    return redirect("homepage:index")


@login_required
def social_connections_view(request):
    """Display user's connected social accounts."""
    from django.conf import settings

    # 定义支持的社交平台及其显示信息和配置键
    social_providers = {
        "github": {
            "name": "GitHub",
            "icon": "bi-github",
            "key": "SOCIAL_AUTH_GITHUB_KEY",
            "secret": "SOCIAL_AUTH_GITHUB_SECRET",
        },
        "google-oauth2": {
            "name": "Google",
            "icon": "bi-google",
            "key": "SOCIAL_AUTH_GOOGLE_OAUTH2_KEY",
            "secret": "SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET",
        },
        "bitbucket-oauth2": {
            "name": "Bitbucket",
            "icon": "bi-git",
            "key": "SOCIAL_AUTH_BITBUCKET_OAUTH2_KEY",
            "secret": "SOCIAL_AUTH_BITBUCKET_OAUTH2_SECRET",
        },
        "docker": {
            "name": "Docker",
            "icon": "bi-box-seam",
            "key": "SOCIAL_AUTH_DOCKER_KEY",
            "secret": "SOCIAL_AUTH_DOCKER_SECRET",
        },
        "facebook": {
            "name": "Facebook",
            "icon": "bi-facebook",
            "key": "SOCIAL_AUTH_FACEBOOK_KEY",
            "secret": "SOCIAL_AUTH_FACEBOOK_SECRET",
        },
        "gitlab": {
            "name": "GitLab",
            "icon": "bi-gitlab",
            "key": "SOCIAL_AUTH_GITLAB_KEY",
            "secret": "SOCIAL_AUTH_GITLAB_SECRET",
        },
        "gitea": {
            "name": "Gitea",
            "icon": "bi-git",
            "key": "SOCIAL_AUTH_GITEA_KEY",
            "secret": "SOCIAL_AUTH_GITEA_SECRET",
        },
        "gitee": {
            "name": "Gitee",
            "icon": "git-branch",
            "key": "SOCIAL_AUTH_GITEE_KEY",
            "secret": "SOCIAL_AUTH_GITEE_SECRET",
        },
        "linkedin-oauth2": {
            "name": "LinkedIn",
            "icon": "bi-linkedin",
            "key": "SOCIAL_AUTH_LINKEDIN_OAUTH2_KEY",
            "secret": "SOCIAL_AUTH_LINKEDIN_OAUTH2_SECRET",
        },
        "twitter-oauth2": {
            "name": "Twitter",
            "icon": "bi-twitter-x",
            "key": "SOCIAL_AUTH_TWITTER_OAUTH2_KEY",
            "secret": "SOCIAL_AUTH_TWITTER_OAUTH2_SECRET",
        },
        "huggingface": {
            "name": "HuggingFace",
            "icon": "brain",
            "key": "SOCIAL_AUTH_HUGGINGFACE_KEY",
            "secret": "SOCIAL_AUTH_HUGGINGFACE_SECRET",
        },
    }

    # 获取用户已连接的社交账号
    user_social_auths = UserSocialAuth.objects.filter(user=request.user)
    connected_providers = {auth.provider: auth for auth in user_social_auths}

    # 构建显示数据，只包含已配置的平台
    connections = []
    for provider_key, provider_info in social_providers.items():
        # 检查平台是否已配置（key 和 secret 都不为空）
        key = getattr(settings, provider_info["key"], "")
        secret = getattr(settings, provider_info["secret"], "")

        if not key or not secret:
            # 如果未配置，跳过此平台
            continue

        is_connected = provider_key in connected_providers
        connection_data = {
            "provider": provider_key,
            "name": provider_info["name"],
            "icon": provider_info["icon"],
            "is_connected": is_connected,
        }
        if is_connected:
            social_auth = connected_providers[provider_key]
            connection_data["uid"] = social_auth.uid
            connection_data["social_auth_id"] = social_auth.id
        connections.append(connection_data)

    # 计算用户的认证方式数量
    has_password = request.user.has_usable_password()
    connected_social_count = len(connected_providers)
    total_auth_methods = (1 if has_password else 0) + connected_social_count

    # 判断是否可以解绑（至少需要保留一个认证方式）
    can_disconnect = total_auth_methods > 1

    return render(
        request,
        "social_connections.html",
        {
            "connections": connections,
            "has_password": has_password,
            "can_disconnect": can_disconnect,
        },
    )


@login_required
def disconnect_social_account(request, provider, association_id):
    """Disconnect a social account from user profile."""
    try:
        social_auth = UserSocialAuth.objects.get(
            id=association_id,
            user=request.user,
            provider=provider,
        )

        # 检查用户是否至少有一个认证方式（密码或其他社交账号）
        has_password = request.user.has_usable_password()
        other_social_auths = UserSocialAuth.objects.filter(
            user=request.user,
        ).exclude(id=association_id)

        if not has_password and not other_social_auths.exists():
            messages.error(
                request,
                "无法解绑该账号：您必须至少保留一个登录方式（设置密码或保留其他社交账号）",
            )
        else:
            provider_name = social_auth.provider
            social_auth.delete()
            messages.success(request, f"已成功解绑 {provider_name} 账号")

    except UserSocialAuth.DoesNotExist:
        messages.error(request, "未找到该社交账号绑定")

    return redirect("accounts:social_connections")


@login_required
def change_password_view(request):
    """Change user password."""
    if request.method == "POST":
        form = CustomPasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            user = form.save()
            # 更新session，避免用户修改密码后被登出
            update_session_auth_hash(request, user)
            messages.success(request, "密码修改成功")
            return redirect("accounts:profile")
    else:
        form = CustomPasswordChangeForm(user=request.user)

    return render(request, "change_password.html", {"form": form})


@login_required
def change_email_view(request):
    """Change user email address."""
    if request.method == "POST":
        form = ChangeEmailForm(user=request.user, data=request.POST)
        if form.is_valid():
            new_email = form.cleaned_data["email"]
            request.user.email = new_email
            request.user.save()
            messages.success(request, "邮箱修改成功")
            return redirect("accounts:profile")
    else:
        form = ChangeEmailForm(user=request.user)

    return render(
        request,
        "change_email.html",
        {"form": form, "current_email": request.user.email},
    )


def _build_asset_snapshot(user):
    """Gather key asset counts for auditing and messaging."""
    providers = list(
        UserSocialAuth.objects.filter(user=user).values_list("provider", flat=True)
    )
    return {
        "total_points": user.total_points,
        "point_source_count": user.point_sources.count(),
        "redemption_count": Redemption.objects.filter(user_profile=user).count(),
        "organization_count": user.organizations.count(),
        "social_providers": providers,
        "withdrawal_count": user.withdrawal_requests.count(),
    }


def _generate_unique_token():
    """Generate a unique approval token for merge links."""
    while True:
        token = secrets.token_urlsafe(32)
        if not AccountMergeRequest.objects.filter(approve_token=token).exists():
            return token


def _send_merge_request_message(merge_request, request):
    """Send inbox notification to the target user with action links."""
    source = merge_request.source_user
    target = merge_request.target_user
    review_url = request.build_absolute_uri(
        reverse("accounts:merge_review", args=[merge_request.approve_token])
    )
    agree_url = request.build_absolute_uri(
        reverse("accounts:merge_agree", args=[merge_request.approve_token])
    )
    reject_url = request.build_absolute_uri(
        reverse("accounts:merge_reject", args=[merge_request.approve_token])
    )

    snapshot = merge_request.asset_snapshot or {}
    providers = snapshot.get("social_providers") or []
    content_lines = [
        f"来自 **{source.username}** ({source.email or '未留邮箱'}) 的账号合并申请。",
        "",
        "资产快照：",
        f"- 积分：{snapshot.get('total_points', 0)}",
        f"- 积分池：{snapshot.get('point_source_count', 0)}",
        f"- 兑换记录：{snapshot.get('redemption_count', 0)}",
        f"- 组织成员关系：{snapshot.get('organization_count', 0)}",
        f"- 提现记录：{snapshot.get('withdrawal_count', 0)}",
        f"- 社交绑定：{', '.join(providers) if providers else '无'}",
        "",
        f"有效期：{merge_request.expires_at:%Y-%m-%d %H:%M}",
        "",
        f"[同意合并]({agree_url})  |  [拒绝]({reject_url})",
        f"查看详情：{review_url}",
    ]

    message = inbox_services.send_message(
        title="账号合并申请",
        content="\n".join(content_lines),
        message_type=InboxMessage.MessageType.SECURITY,
        recipients=[target],
    )
    merge_request.message = message
    merge_request.save(update_fields=["message"])


def _notify_merge_result(merge_request, *, accepted, request, reason=None):
    """Send result notifications to both source and target users."""
    source = merge_request.source_user
    target = merge_request.target_user
    status_text = "合并已完成" if accepted else (reason or "合并已被拒绝")
    processed_at = merge_request.processed_at or timezone.now()
    content = "\n".join(
        [
            f"账号合并申请结果：{status_text}",
            "",
            f"源账号：{source.username} ({source.email or '未留邮箱'})",
            f"目标账号：{target.username} ({target.email or '未留邮箱'})",
            f"处理时间：{timezone.localtime(processed_at):%Y-%m-%d %H:%M}",
        ]
    )
    inbox_services.send_message(
        title="账号合并结果通知",
        content=content,
        message_type=InboxMessage.MessageType.SECURITY,
        recipients=[source, target],
    )


def _expire_request_if_needed(merge_request, actor, request):
    """Mark request expired and notify when token is stale."""
    if (
        merge_request.status != AccountMergeRequest.Status.PENDING
        or not merge_request.is_expired
    ):
        return False

    merge_request.status = AccountMergeRequest.Status.EXPIRED
    merge_request.processed_at = timezone.now()
    merge_request.processed_by = actor
    merge_request.save(update_fields=["status", "processed_at", "processed_by"])
    _notify_merge_result(
        merge_request,
        accepted=False,
        request=request,
        reason="申请已过期，未做任何变更",
    )
    return True


@login_required
def merge_request_view(request):
    """Create a merge request and list existing requests."""
    if request.method == "POST":
        form = AccountMergeRequestForm(user=request.user, data=request.POST)
        if form.is_valid():
            target_user = form.target_user
            token = _generate_unique_token()
            snapshot = _build_asset_snapshot(request.user)
            expires_at = timezone.now() + timedelta(days=7)

            try:
                merge_request = AccountMergeRequest.objects.create(
                    source_user=request.user,
                    target_user=target_user,
                    target_email_input=form.cleaned_data.get("target_email", ""),
                    target_username_input=form.cleaned_data.get("target_username", ""),
                    status=AccountMergeRequest.Status.PENDING,
                    approve_token=token,
                    expires_at=expires_at,
                    asset_snapshot=snapshot,
                )
            except IntegrityError:
                messages.error(request, "存在待处理的申请，请勿重复提交")
                return redirect("accounts:merge_request")

            _send_merge_request_message(merge_request, request)
            messages.success(request, "申请已提交，请等待目标账号确认")
            return redirect("accounts:merge_request")
    else:
        form = AccountMergeRequestForm(user=request.user)

    sent_requests = AccountMergeRequest.objects.filter(
        source_user=request.user
    ).order_by("-created_at")
    incoming_requests = AccountMergeRequest.objects.filter(
        target_user=request.user
    ).order_by("-created_at")

    return render(
        request,
        "merge_request.html",
        {
            "form": form,
            "sent_requests": sent_requests,
            "incoming_requests": incoming_requests,
        },
    )


@login_required
def merge_review_view(request, token):
    """Display merge details for the target user to review."""
    merge_request = get_object_or_404(AccountMergeRequest, approve_token=token)
    if merge_request.target_user != request.user:
        msg = "您无权查看此合并请求"
        raise PermissionDenied(msg)

    _expire_request_if_needed(merge_request, request.user, request)

    return render(
        request,
        "merge_review.html",
        {
            "merge_request": merge_request,
            "agree_url": reverse("accounts:merge_agree", args=[token]),
            "reject_url": reverse("accounts:merge_reject", args=[token]),
        },
    )


@login_required
def merge_agree_view(request, token):
    """Handle acceptance of a merge request by the target user."""
    merge_request = get_object_or_404(AccountMergeRequest, approve_token=token)
    if merge_request.target_user != request.user:
        msg = "您无权处理此合并请求"
        raise PermissionDenied(msg)

    if merge_request.status == AccountMergeRequest.Status.ACCEPTED:
        messages.info(request, "该申请已处理完成")
        return redirect("accounts:merge_review", token=token)

    if _expire_request_if_needed(merge_request, request.user, request):
        messages.error(request, "申请已过期，无法合并")
        return redirect("accounts:merge_review", token=token)

    if request.method != "POST":
        return redirect("accounts:merge_review", token=token)

    try:
        perform_merge(merge_request)
    except AccountMergeError as exc:  # pragma: no cover - defensive
        messages.error(request, str(exc))
        return redirect("accounts:merge_review", token=token)

    _notify_merge_result(merge_request, accepted=True, request=request)
    messages.success(request, "合并完成，源账号已停用")
    return redirect("accounts:merge_review", token=token)


@login_required
def merge_reject_view(request, token):
    """Reject a merge request as the target user."""
    merge_request = get_object_or_404(AccountMergeRequest, approve_token=token)
    if merge_request.target_user != request.user:
        msg = "您无权处理此合并请求"
        raise PermissionDenied(msg)

    if merge_request.status == AccountMergeRequest.Status.ACCEPTED:
        messages.info(request, "该申请已完成合并，无法拒绝")
        return redirect("accounts:merge_review", token=token)

    if _expire_request_if_needed(merge_request, request.user, request):
        messages.error(request, "申请已过期")
        return redirect("accounts:merge_review", token=token)

    if request.method != "POST":
        return redirect("accounts:merge_review", token=token)

    if merge_request.status == AccountMergeRequest.Status.PENDING:
        merge_request.status = AccountMergeRequest.Status.REJECTED
        merge_request.processed_by = request.user
        merge_request.processed_at = timezone.now()
        merge_request.save(update_fields=["status", "processed_by", "processed_at"])
        _notify_merge_result(
            merge_request,
            accepted=False,
            request=request,
            reason="目标账号已拒绝合并请求",
        )
        messages.info(request, "已拒绝该合并申请")

    return redirect("accounts:merge_review", token=token)


def password_reset_request_view(request):
    """Handle password reset request."""
    if request.method == "POST":
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            User = get_user_model()

            try:
                user = User.objects.get(email=email)

                # 检查用户是否有可用密码（即是否通过邮箱/用户名注册的）
                if not user.has_usable_password():
                    # 用户没有设置密码，检查是否有社交账号绑定
                    social_auths = UserSocialAuth.objects.filter(user=user)
                    if social_auths.exists():
                        providers = ", ".join(
                            auth.provider for auth in social_auths[:3]
                        )
                        messages.warning(
                            request,
                            f"该账号未设置密码，请使用社交账号登录（{providers}）",
                        )
                    else:
                        messages.error(
                            request,
                            "该账号未设置密码且没有绑定社交账号，请联系管理员",
                        )
                    return redirect("accounts:password_reset_request")

                # 发送密码重置邮件（异步任务）
                domain = request.get_host()
                use_https = request.is_secure()
                send_password_reset_email.enqueue(user.id, domain, use_https)

                messages.success(
                    request,
                    "密码重置链接已发送到您的邮箱，请检查收件箱（包括垃圾邮件文件夹）",
                )
                return redirect("accounts:password_reset_done")

            except User.DoesNotExist:
                # 为了安全，不透露邮箱是否存在
                messages.success(
                    request,
                    "如果该邮箱已注册，密码重置链接将发送到您的邮箱",
                )
                return redirect("accounts:password_reset_done")
    else:
        form = PasswordResetRequestForm()

    return render(request, "password_reset_request.html", {"form": form})


def password_reset_done_view(request):
    """Display password reset email sent confirmation."""
    return render(request, "password_reset_done.html")


def password_reset_confirm_view(request, uidb64, token):
    """Handle password reset confirmation with token."""
    User = get_user_model()

    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        if request.method == "POST":
            form = PasswordResetConfirmForm(user, request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "密码重置成功，请使用新密码登录")
                return redirect("accounts:sign_in")
        else:
            form = PasswordResetConfirmForm(user)

        return render(
            request,
            "password_reset_confirm.html",
            {"form": form, "validlink": True},
        )
    else:
        return render(
            request,
            "password_reset_confirm.html",
            {"validlink": False},
        )


@login_required
def shop_list_view(request):
    """Display list of available shop items for redemption."""
    # Get all active items
    items = ShopItem.objects.filter(is_active=True).prefetch_related("allowed_tags")

    # Get user's total available points (uses cached value)
    user_points = request.user.total_points

    return render(
        request,
        "shop_list.html",
        {
            "items": items,
            "user_points": user_points,
        },
    )


@login_required
def redemption_list_view(request):
    """Display user's redemption history."""
    redemptions = Redemption.objects.filter(user_profile=request.user).select_related(
        "item", "transaction"
    )

    return render(
        request,
        "redemption_list.html",
        {
            "redemptions": redemptions,
        },
    )


@login_required
def redeem_confirm_view(request, item_id):
    """Handle item redemption confirmation and processing."""
    item = get_object_or_404(ShopItem, id=item_id)

    # Check if item requires shipping
    if item.requires_shipping:
        user_addresses = ShippingAddress.objects.filter(user=request.user)
        if not user_addresses.exists():
            # No addresses - redirect to create address page
            messages.warning(request, "此商品需要收货地址，请先添加收货地址")
            return redirect("accounts:shipping_address_create_guide", item_id=item_id)

        default_address = user_addresses.filter(is_default=True).first()
    else:
        user_addresses = None
        default_address = None

    # Only process POST requests for redemption
    if request.method == "POST":
        shipping_address_id = None
        if item.requires_shipping:
            shipping_address_id = request.POST.get("shipping_address")
            if not shipping_address_id:
                messages.error(request, "请选择收货地址")
                return redirect("accounts:redeem_confirm", item_id=item_id)

        try:
            redemption = redeem_item(
                user=request.user,
                item_id=item_id,
                shipping_address_id=shipping_address_id,
            )
            messages.success(
                request,
                f"成功兑换 {item.name}！消耗积分：{redemption.points_cost_at_redemption}",
            )
            return redirect("accounts:redemption_list")
        except RedemptionError as e:
            messages.error(request, f"兑换失败：{e}")
            return redirect("accounts:shop_list")
        except InsufficientPointsError as e:
            messages.error(request, f"积分不足：{e}")
            return redirect("accounts:shop_list")

    # GET request - show confirmation page
    # Use cached total_points for better performance
    user_points = request.user.total_points

    can_afford = user_points >= item.cost
    remaining_after_redeem = user_points - item.cost if can_afford else 0
    points_needed = item.cost - user_points if not can_afford else 0

    return render(
        request,
        "redeem_confirm.html",
        {
            "item": item,
            "user_points": user_points,
            "can_afford": can_afford,
            "remaining_after_redeem": remaining_after_redeem,
            "points_needed": points_needed,
            "requires_shipping": item.requires_shipping,
            "addresses": user_addresses,
            "default_address": default_address,
        },
    )


def public_profile_view(request, username):
    """Display public profile page for any user."""
    User = get_user_model()
    user = get_object_or_404(User, username=username)
    profile, _created = UserProfile.objects.get_or_create(user=user)

    # Get work experiences and educations
    work_experiences = profile.work_experiences.all()
    educations = profile.educations.all()

    # Get user's total points (public information)
    total_points = user.total_points

    return render(
        request,
        "public_profile.html",
        {
            "profile_user": user,
            "profile": profile,
            "work_experiences": work_experiences,
            "educations": educations,
            "total_points": total_points,
        },
    )


@login_required
def shipping_address_list_view(request):
    """Display user's shipping addresses."""
    addresses = ShippingAddress.objects.filter(user=request.user)
    return render(
        request,
        "shipping_address_list.html",
        {"addresses": addresses},
    )


@login_required
def shipping_address_create_view(request):
    """Create a new shipping address."""
    if request.method == "POST":
        form = ShippingAddressForm(request.POST)
        if form.is_valid():
            address = form.save(commit=False)
            address.user = request.user
            address.save()
            messages.success(request, "收货地址已添加")
            return redirect("accounts:shipping_address_list")
    else:
        form = ShippingAddressForm()

    return render(
        request,
        "shipping_address_form.html",
        {"form": form, "action": "create"},
    )


@login_required
def shipping_address_create_guide_view(request, item_id):
    """Guide user to create shipping address for redemption."""
    item = get_object_or_404(ShopItem, id=item_id)

    if request.method == "POST":
        form = ShippingAddressForm(request.POST)
        if form.is_valid():
            address = form.save(commit=False)
            address.user = request.user
            address.save()
            messages.success(request, "收货地址已添加，现在可以继续兑换")
            return redirect("accounts:redeem_confirm", item_id=item_id)
    else:
        # Set is_default to True for the first address
        initial_data = {"is_default": True}
        form = ShippingAddressForm(initial=initial_data)

    return render(
        request,
        "shipping_address_guide.html",
        {"form": form, "item": item},
    )


@login_required
def shipping_address_edit_view(request, address_id):
    """Edit an existing shipping address."""
    address = get_object_or_404(ShippingAddress, id=address_id, user=request.user)

    if request.method == "POST":
        form = ShippingAddressForm(request.POST, instance=address)
        if form.is_valid():
            form.save()
            messages.success(request, "收货地址已更新")
            return redirect("accounts:shipping_address_list")
    else:
        form = ShippingAddressForm(instance=address)

    return render(
        request,
        "shipping_address_form.html",
        {"form": form, "action": "edit", "address": address},
    )


@login_required
def shipping_address_delete_view(request, address_id):
    """Delete a shipping address."""
    address = get_object_or_404(ShippingAddress, id=address_id, user=request.user)

    if request.method == "POST":
        address.delete()
        messages.success(request, "收货地址已删除")
        return redirect("accounts:shipping_address_list")

    return render(
        request,
        "shipping_address_confirm_delete.html",
        {"address": address},
    )


@login_required
def shipping_address_set_default_view(request, address_id):
    """Set an address as default."""
    address = get_object_or_404(ShippingAddress, id=address_id, user=request.user)

    if request.method == "POST":
        address.is_default = True
        address.save()
        messages.success(request, "已设置为默认地址")

    return redirect("accounts:shipping_address_list")


# Organization views


@login_required
def organization_list(request):
    """
    Display list of organizations the user is a member of.

    Args:
        request: HTTP request

    """
    # Get user's organizations with their memberships
    memberships = (
        OrganizationMembership.objects.filter(user=request.user)
        .select_related("organization")
        .order_by("-joined_at")
    )

    # Build organizations list with membership info
    organizations = []
    for membership in memberships:
        org = membership.organization
        # Attach membership info for easy template access
        org.user_membership = membership
        organizations.append(org)

    context = {
        "organizations": organizations,
    }

    return render(request, "accounts/organization_list.html", context)


@login_required
def organization_create(request):
    """
    Create a new organization.

    Args:
        request: HTTP request

    """
    form_data = None
    if request.method == "POST":
        # Create a dict with form data for validation
        form_data = {
            "name": request.POST.get("name", "").strip(),
            "slug": request.POST.get("slug", "").strip(),
            "description": request.POST.get("description", "").strip(),
            "website": request.POST.get("website", "").strip(),
            "location": request.POST.get("location", "").strip(),
            "avatar": request.FILES.get("avatar"),
        }

        # Validate required fields
        errors = {}
        if not form_data["name"]:
            errors["name"] = "组织名称不能为空。"
        if not form_data["slug"]:
            errors["slug"] = "URL 别名不能为空。"

        # Check slug uniqueness
        if form_data["slug"]:
            existing = Organization.objects.filter(slug=form_data["slug"]).first()
            if existing:
                errors["slug"] = "URL 别名已存在。"

        # Validate slug format (alphanumeric, hyphens, underscores only)
        if form_data["slug"]:
            import re

            if not re.match(r"^[a-zA-Z0-9_-]+$", form_data["slug"]):
                errors["slug"] = "URL 别名只能包含字母、数字、连字符和下划线。"

        if not errors:
            # Create organization
            organization = Organization.objects.create(
                name=form_data["name"],
                slug=form_data["slug"],
                description=form_data["description"],
                website=form_data["website"],
                location=form_data["location"],
            )

            # Handle avatar upload
            if form_data["avatar"]:
                organization.avatar = form_data["avatar"]
                organization.save()

            # Add creator as owner
            OrganizationMembership.objects.create(
                user=request.user,
                organization=organization,
                role=OrganizationMembership.Role.OWNER,
            )

            messages.success(request, f"组织 {organization.name} 创建成功！")
            return redirect("accounts:organization_detail", slug=organization.slug)
        else:
            # Pass errors to template
            form_data["errors"] = errors

    # Prepare form data for GET request or failed POST
    if not form_data:
        form_data = {
            "name": "",
            "slug": "",
            "description": "",
            "website": "",
            "location": "",
        }

    context = {
        "form": type(
            "obj", (object,), form_data
        ),  # Create a simple object with form data
    }

    return render(request, "accounts/organization_create.html", context)


@login_required
def organization_detail(request, slug):
    """
    Display organization details.

    Args:
        request: HTTP request
        slug: Organization slug

    """
    organization = get_object_or_404(Organization, slug=slug)

    # Check if user is a member
    try:
        membership = OrganizationMembership.objects.get(
            user=request.user, organization=organization
        )
    except OrganizationMembership.DoesNotExist:
        msg = "您不是该组织的成员。"
        raise PermissionDenied(msg) from None

    # Get all memberships
    memberships = list(
        OrganizationMembership.objects.filter(organization=organization)
        .select_related("user")
        .order_by("-role", "joined_at")
    )
    memberships_count = len(memberships)

    context = {
        "organization": organization,
        "membership": membership,
        "memberships": memberships,
        "memberships_count": memberships_count,
        "is_admin": membership.is_admin_or_owner(),
    }

    return render(request, "accounts/organization_detail.html", context)


def _validate_organization_settings(form_data, organization):
    """
    Validate organization settings form data.

    Args:
        form_data: Dictionary with form data
        organization: Organization instance for slug uniqueness check

    Returns:
        Dictionary of errors (empty if valid)

    """
    errors = {}
    if not form_data["name"]:
        errors["name"] = "组织名称不能为空。"
    if not form_data["slug"]:
        errors["slug"] = "URL 别名不能为空。"

    # Check slug uniqueness
    if form_data["slug"]:
        existing = (
            Organization.objects.filter(slug=form_data["slug"])
            .exclude(id=organization.id)
            .first()
        )
        if existing:
            errors["slug"] = "URL 别名已存在。"

    return errors


def _handle_organization_avatar(organization, form_data):
    """
    Handle organization avatar upload or removal.

    Args:
        organization: Organization instance
        form_data: Dictionary with form data including avatar/remove_avatar

    """
    if form_data["remove_avatar"]:
        organization.avatar.delete(save=False)
        organization.avatar = None
    elif form_data["avatar"]:
        # Delete old avatar if exists
        if organization.avatar:
            organization.avatar.delete(save=False)
        organization.avatar = form_data["avatar"]


@login_required
def organization_settings(request, slug):
    """
    Display and handle organization settings (admin only).

    Args:
        request: HTTP request
        slug: Organization slug

    """
    organization = get_object_or_404(Organization, slug=slug)

    # Check if user is admin/owner
    try:
        membership = OrganizationMembership.objects.get(
            user=request.user, organization=organization
        )
    except OrganizationMembership.DoesNotExist:
        msg = "您不是该组织的成员。"
        raise PermissionDenied(msg) from None

    if not membership.is_admin_or_owner():
        msg = "您没有权限访问该页面。"
        raise PermissionDenied(msg)

    form_data = None
    if request.method == "POST":
        # Create a dict with form data for validation
        form_data = {
            "name": request.POST.get("name", "").strip(),
            "slug": request.POST.get("slug", "").strip(),
            "description": request.POST.get("description", "").strip(),
            "website": request.POST.get("website", "").strip(),
            "location": request.POST.get("location", "").strip(),
            "avatar": request.FILES.get("avatar"),
            "remove_avatar": request.POST.get("remove_avatar") == "1",
        }

        # Validate form data
        errors = _validate_organization_settings(form_data, organization)

        if not errors:
            # Update organization settings
            organization.name = form_data["name"]
            organization.slug = form_data["slug"]
            organization.description = form_data["description"]
            organization.website = form_data["website"]
            organization.location = form_data["location"]

            # Handle avatar upload or removal
            _handle_organization_avatar(organization, form_data)

            organization.save()

            messages.success(request, "组织设置已更新。")
            return redirect("accounts:organization_settings", slug=organization.slug)

        # Pass errors to template
        form_data["errors"] = errors

    # Prepare form data for GET request or failed POST
    if not form_data:
        form_data = {
            "name": organization.name,
            "slug": organization.slug,
            "description": organization.description or "",
            "website": organization.website or "",
            "location": organization.location or "",
        }

    context = {
        "organization": organization,
        "membership": membership,
        "form": type(
            "obj", (object,), form_data
        ),  # Create a simple object with form data
    }

    return render(request, "accounts/organization_settings.html", context)


@login_required
def organization_members(request, slug):
    """
    Display and manage organization members (admin only).

    Args:
        request: HTTP request
        slug: Organization slug

    """
    organization = get_object_or_404(Organization, slug=slug)

    # Check if user is admin/owner
    try:
        membership = OrganizationMembership.objects.get(
            user=request.user, organization=organization
        )
    except OrganizationMembership.DoesNotExist:
        msg = "您不是该组织的成员。"
        raise PermissionDenied(msg) from None

    if not membership.is_admin_or_owner():
        msg = "您没有权限访问该页面。"
        raise PermissionDenied(msg)

    # Get all memberships
    memberships = (
        OrganizationMembership.objects.filter(organization=organization)
        .select_related("user")
        .order_by("-role", "joined_at")
    )

    # Count owners
    owner_count = memberships.filter(role=OrganizationMembership.Role.OWNER).count()

    context = {
        "organization": organization,
        "membership": membership,
        "memberships": memberships,
        "owner_count": owner_count,
    }

    return render(request, "accounts/organization_members.html", context)


@login_required
def organization_member_add(request, slug):
    """
    Add a new member to organization (admin only).

    Args:
        request: HTTP request
        slug: Organization slug

    """
    User = get_user_model()
    organization = get_object_or_404(Organization, slug=slug)

    # Check if user is admin/owner
    try:
        membership = OrganizationMembership.objects.get(
            user=request.user, organization=organization
        )
    except OrganizationMembership.DoesNotExist:
        msg = "您不是该组织的成员。"
        raise PermissionDenied(msg) from None

    if not membership.is_admin_or_owner():
        msg = "您没有权限执行该操作。"
        raise PermissionDenied(msg)

    if request.method != "POST":
        return redirect("accounts:organization_members", slug=slug)

    # Get username and role from form
    username = request.POST.get("username", "").strip()
    role = request.POST.get("role", OrganizationMembership.Role.MEMBER)

    # Validate role
    valid_roles = [choice[0] for choice in OrganizationMembership.Role.choices]
    if role not in valid_roles:
        messages.error(request, "无效的角色。")
        return redirect("accounts:organization_members", slug=slug)

    # Find user by username
    try:
        user_to_add = User.objects.get(username=username)
    except User.DoesNotExist:
        messages.error(request, f"用户 {username} 不存在。")
        return redirect("accounts:organization_members", slug=slug)

    # Check if user is already a member
    if OrganizationMembership.objects.filter(
        user=user_to_add, organization=organization
    ).exists():
        messages.error(request, f"用户 {username} 已经是组织成员。")
        return redirect("accounts:organization_members", slug=slug)

    # Add user to organization
    OrganizationMembership.objects.create(
        user=user_to_add, organization=organization, role=role
    )

    messages.success(request, f"成功将 {username} 添加为组织成员。")
    return redirect("accounts:organization_members", slug=slug)


@login_required
def organization_member_update_role(request, slug, member_id):
    """
    Update a member's role (admin only).

    Args:
        request: HTTP request
        slug: Organization slug
        member_id: OrganizationMembership ID

    """
    organization = get_object_or_404(Organization, slug=slug)

    # Check if user is admin/owner
    try:
        user_membership = OrganizationMembership.objects.get(
            user=request.user, organization=organization
        )
    except OrganizationMembership.DoesNotExist:
        msg = "您不是该组织的成员。"
        raise PermissionDenied(msg) from None

    if not user_membership.is_admin_or_owner():
        msg = "您没有权限执行该操作。"
        raise PermissionDenied(msg)

    if request.method != "POST":
        return redirect("accounts:organization_members", slug=slug)

    # Get the member to update
    member = get_object_or_404(
        OrganizationMembership, id=member_id, organization=organization
    )

    # Get new role
    new_role = request.POST.get("role")
    if new_role not in dict(OrganizationMembership.Role.choices):
        messages.error(request, "无效的角色。")
        return redirect("accounts:organization_members", slug=slug)

    # Check if demoting the last owner
    if (
        member.role == OrganizationMembership.Role.OWNER
        and new_role != OrganizationMembership.Role.OWNER
    ):
        owner_count = OrganizationMembership.objects.filter(
            organization=organization, role=OrganizationMembership.Role.OWNER
        ).count()
        if owner_count <= 1:
            messages.error(request, "无法降级该所有者，组织必须至少有一个所有者。")
            return redirect("accounts:organization_members", slug=slug)

    # Update role
    member.role = new_role
    member.save()
    messages.success(
        request,
        f"已将 {member.user.username} 的角色更新为{member.get_role_display()}。",
    )

    return redirect("accounts:organization_members", slug=slug)


@login_required
def organization_member_remove(request, slug, member_id):
    """
    Remove a member from organization (admin only).

    Args:
        request: HTTP request
        slug: Organization slug
        member_id: OrganizationMembership ID

    """
    organization = get_object_or_404(Organization, slug=slug)

    # Check if user is admin/owner
    try:
        user_membership = OrganizationMembership.objects.get(
            user=request.user, organization=organization
        )
    except OrganizationMembership.DoesNotExist:
        msg = "您不是该组织的成员。"
        raise PermissionDenied(msg) from None

    if not user_membership.is_admin_or_owner():
        msg = "您没有权限执行该操作。"
        raise PermissionDenied(msg)

    if request.method != "POST":
        return redirect("accounts:organization_members", slug=slug)

    # Get the member to remove
    member = get_object_or_404(
        OrganizationMembership, id=member_id, organization=organization
    )

    # Prevent removing the last owner
    if member.role == OrganizationMembership.Role.OWNER:
        owner_count = OrganizationMembership.objects.filter(
            organization=organization, role=OrganizationMembership.Role.OWNER
        ).count()
        if owner_count <= 1:
            messages.error(request, "无法移除该所有者，组织必须至少有一个所有者。")
            return redirect("accounts:organization_members", slug=slug)

    username = member.user.username
    is_self_removal = member.user == request.user
    member.delete()
    messages.success(request, f"已将 {username} 从组织中移除。")

    # If user removed themselves, redirect to organization list
    if is_self_removal:
        return redirect("accounts:organization_list")

    return redirect("accounts:organization_members", slug=slug)


@login_required
@require_POST
def organization_delete(request, slug):
    """
    Delete an organization (admin/owner only).

    Args:
        request: HTTP request
        slug: Organization slug

    """
    organization = get_object_or_404(Organization, slug=slug)

    try:
        membership = OrganizationMembership.objects.get(
            user=request.user, organization=organization
        )
    except OrganizationMembership.DoesNotExist:
        msg = "您不是该组织的成员。"
        raise PermissionDenied(msg) from None

    if not membership.is_admin_or_owner():
        msg = "您没有权限执行该操作。"
        raise PermissionDenied(msg)

    confirmation = request.POST.get("confirm_slug", "").strip()
    if confirmation != organization.slug:
        messages.error(request, "请输入正确的组织标识以确认删除。")
        return redirect("accounts:organization_settings", slug=slug)

    org_name = organization.name
    avatar_file = organization.avatar if organization.avatar else None

    with transaction.atomic():
        organization.delete()
        if avatar_file:
            transaction.on_commit(lambda f=avatar_file: f.delete(save=False))
    messages.success(request, f"组织 {org_name} 已删除。")
    return redirect("accounts:organization_list")


# Label management views


@login_required
def label_list_view(request):
    """Display user's labels."""
    from labels.models import Label, OwnerType

    # Get user's labels
    user_labels = Label.objects.filter(
        owner_type=OwnerType.USER, owner_id=request.user.id
    ).order_by("-created_at")

    # Get labels shared with user
    shared_labels = []
    from labels.models import GranteeType, LabelPermission

    label_permissions = LabelPermission.objects.filter(
        grantee_type=GranteeType.USER, grantee_id=request.user.id, is_active=True
    ).select_related("label")

    for perm in label_permissions:
        if not perm.is_expired():
            label = perm.label
            label.permission_level = perm.permission_level
            shared_labels.append(label)

    return render(
        request,
        "accounts/label_list.html",
        {"user_labels": user_labels, "shared_labels": shared_labels},
    )


@login_required
def label_create_view(request):
    """Create a new label."""
    import json

    from labels.models import Label, LabelType, OwnerType

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        name_zh = request.POST.get("name_zh", "").strip()
        label_type = request.POST.get("type", "")
        is_public = request.POST.get("is_public") == "1"
        data_str = request.POST.get("data", "{}").strip()

        errors = {}
        if not name:
            errors["name"] = "英文名称不能为空"
        if not name_zh:
            errors["name_zh"] = "中文名称不能为空"
        if label_type not in dict(LabelType.choices):
            errors["type"] = "请选择有效的标签类型"

        # Parse JSON data
        data = {}
        if data_str:
            try:
                data = json.loads(data_str)
                if not isinstance(data, dict):
                    errors["data"] = "标签数据必须是 JSON 对象格式"
            except json.JSONDecodeError:
                errors["data"] = "标签数据格式无效，请输入有效的 JSON"

        # Check uniqueness
        if name and Label.objects.filter(
            name=name, owner_type=OwnerType.USER, owner_id=request.user.id
        ).exists():
            errors["name"] = "该标签名称已存在"

        if not errors:
            label = Label.objects.create(
                name=name,
                name_zh=name_zh,
                type=label_type,
                owner_type=OwnerType.USER,
                owner_id=request.user.id,
                is_public=is_public,
                data=data,
            )
            messages.success(request, f"标签 {label.name_zh} 创建成功")
            return redirect("accounts:label_list")

        context = {
            "errors": errors,
            "name": name,
            "name_zh": name_zh,
            "type": label_type,
            "is_public": is_public,
            "data": data_str,
            "label_types": LabelType.choices,
        }
        return render(request, "accounts/label_form.html", context)

    return render(
        request, "accounts/label_form.html", {"label_types": LabelType.choices}
    )


@login_required
def label_edit_view(request, label_id):
    """Edit an existing label."""
    import json

    from labels.models import Label, LabelType

    label = get_object_or_404(Label, id=label_id)

    if not label.can_edit(request.user):
        messages.error(request, "您没有权限编辑此标签")
        return redirect("accounts:label_list")

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        name_zh = request.POST.get("name_zh", "").strip()
        label_type = request.POST.get("type", "")
        is_public = request.POST.get("is_public") == "1"
        data_str = request.POST.get("data", "{}").strip()

        errors = {}
        if not name:
            errors["name"] = "英文名称不能为空"
        if not name_zh:
            errors["name_zh"] = "中文名称不能为空"
        if label_type not in dict(LabelType.choices):
            errors["type"] = "请选择有效的标签类型"

        # Parse JSON data
        data = {}
        if data_str:
            try:
                data = json.loads(data_str)
                if not isinstance(data, dict):
                    errors["data"] = "标签数据必须是 JSON 对象格式"
            except json.JSONDecodeError:
                errors["data"] = "标签数据格式无效，请输入有效的 JSON"

        # Check uniqueness (exclude current label)
        if name and Label.objects.filter(
            name=name, owner_type=label.owner_type, owner_id=label.owner_id
        ).exclude(id=label.id).exists():
            errors["name"] = "该标签名称已存在"

        if not errors:
            label.name = name
            label.name_zh = name_zh
            label.type = label_type
            label.is_public = is_public
            label.data = data
            label.save()
            messages.success(request, f"标签 {label.name_zh} 更新成功")
            return redirect("accounts:label_list")

        context = {
            "label": label,
            "errors": errors,
            "name": name,
            "name_zh": name_zh,
            "type": label_type,
            "is_public": is_public,
            "data": data_str,
            "label_types": LabelType.choices,
        }
        return render(request, "accounts/label_form.html", context)

    return render(
        request,
        "accounts/label_form.html",
        {"label": label, "label_types": LabelType.choices},
    )


@login_required
@require_POST
def label_delete_view(request, label_id):
    """Delete a label."""
    from labels.models import Label

    label = get_object_or_404(Label, id=label_id)

    if not label.can_manage(request.user):
        messages.error(request, "您没有权限删除此标签")
        return redirect("accounts:label_list")

    label_name = label.name_zh
    label.delete()
    messages.success(request, f"标签 {label_name} 已删除")
    return redirect("accounts:label_list")


@login_required
def label_permissions_view(request, label_id):
    """Manage label permissions."""
    from labels.models import Label, LabelPermission

    label = get_object_or_404(Label, id=label_id)

    if not label.can_manage(request.user):
        messages.error(request, "您没有权限管理此标签的权限")
        return redirect("accounts:label_list")

    permissions = LabelPermission.objects.filter(label=label, is_active=True).order_by(
        "-granted_at"
    )

    return render(
        request,
        "accounts/label_permissions.html",
        {"label": label, "permissions": permissions},
    )


@login_required
def label_permission_grant_view(request, label_id):
    """Grant permission to a user."""
    from labels.models import (
        GranteeType,
        Label,
        LabelPermission,
        LabelPermissionLog,
        PermissionLevel,
    )

    label = get_object_or_404(Label, id=label_id)

    if not label.can_manage(request.user):
        messages.error(request, "您没有权限管理此标签的权限")
        return redirect("accounts:label_list")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        permission_level = request.POST.get("permission_level", "")
        expires_days = request.POST.get("expires_days", "").strip()
        notes = request.POST.get("notes", "").strip()

        errors = {}
        if not username:
            errors["username"] = "请输入用户名"
        if permission_level not in dict(PermissionLevel.choices):
            errors["permission_level"] = "请选择有效的权限级别"

        # Find user
        User = get_user_model()
        try:
            target_user = User.objects.get(username=username)
        except User.DoesNotExist:
            errors["username"] = f"用户 {username} 不存在"
            target_user = None

        # Check if user is trying to grant permission to themselves
        if target_user and target_user.id == request.user.id:
            errors["username"] = "不能授权给自己"
            target_user = None

        # Calculate expiration date
        expires_at = None
        if expires_days:
            try:
                days = int(expires_days)
                if days > 0:
                    expires_at = timezone.now() + timedelta(days=days)
            except ValueError:
                errors["expires_days"] = "请输入有效的天数"

        if not errors and target_user:
            # Check if permission already exists
            existing_perm = LabelPermission.objects.filter(
                label=label,
                grantee_type=GranteeType.USER,
                grantee_id=target_user.id,
                is_active=True,
            ).first()

            if existing_perm:
                # Update existing permission
                existing_perm.permission_level = permission_level
                existing_perm.expires_at = expires_at
                existing_perm.notes = notes
                existing_perm.save()

                # Log the update
                LabelPermissionLog.objects.create(
                    permission=existing_perm,
                    action="updated",
                    actor=request.user,
                    details={
                        "permission_level": permission_level,
                        "expires_at": expires_at.isoformat() if expires_at else None,
                    },
                )
                messages.success(request, f"已更新授予 {username} 的权限")
            else:
                # Create new permission
                perm = LabelPermission.objects.create(
                    label=label,
                    grantee_type=GranteeType.USER,
                    grantee_id=target_user.id,
                    permission_level=permission_level,
                    granted_by=request.user,
                    expires_at=expires_at,
                    notes=notes,
                )

                # Log the grant
                LabelPermissionLog.objects.create(
                    permission=perm,
                    action="granted",
                    actor=request.user,
                    details={
                        "permission_level": permission_level,
                        "expires_at": expires_at.isoformat() if expires_at else None,
                    },
                )
                messages.success(request, f"已授予 {username} 权限")

            return redirect("accounts:label_permissions", label_id=label.id)

        context = {
            "label": label,
            "errors": errors,
            "username": username,
            "permission_level": permission_level,
            "expires_days": expires_days,
            "notes": notes,
            "permission_levels": PermissionLevel.choices,
        }
        return render(request, "accounts/label_permission_grant.html", context)

    return render(
        request,
        "accounts/label_permission_grant.html",
        {"label": label, "permission_levels": PermissionLevel.choices},
    )


@login_required
@require_POST
def label_permission_revoke_view(request, permission_id):
    """Revoke a permission."""
    from labels.models import LabelPermission, LabelPermissionLog

    permission = get_object_or_404(LabelPermission, id=permission_id)

    if not permission.label.can_manage(request.user):
        messages.error(request, "您没有权限撤销此权限")
        return redirect("accounts:label_list")

    label_id = permission.label.id
    permission.is_active = False
    permission.save()

    # Log the revocation
    LabelPermissionLog.objects.create(
        permission=permission, action="revoked", actor=request.user, details={}
    )

    messages.success(request, "权限已撤销")
    return redirect("accounts:label_permissions", label_id=label_id)
