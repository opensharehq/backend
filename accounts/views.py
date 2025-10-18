"""Views for user authentication and profile management."""

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.db.models import Sum
from django.forms import inlineformset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from social_django.models import UserSocialAuth

from points.services import InsufficientPointsError
from shop.models import Redemption, ShopItem
from shop.services import RedemptionError, redeem_item

from .forms import (
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
from .models import Education, ShippingAddress, UserProfile, WorkExperience
from .tasks import send_password_reset_email


def accounts_index(request):
    """Redirect to sign-in or profile based on authentication status."""
    if request.user.is_authenticated:
        return redirect("accounts:profile")
    return redirect("accounts:sign_in")


def sign_in_view(request):
    """Display sign-in page with email, username, and GitHub auth options."""
    return render(request, "sign_in.html")


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
    profile, _created = UserProfile.objects.get_or_create(user=request.user)
    return render(request, "profile.html", {"profile": profile})


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

    # Get user's total available points
    user_points = (
        request.user.point_sources.aggregate(total=Sum("remaining_points"))["total"]
        or 0
    )

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
                user_profile=request.user,
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
    user_points = (
        request.user.point_sources.aggregate(total=Sum("remaining_points"))["total"]
        or 0
    )

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
