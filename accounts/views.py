"""Views for user authentication and profile management."""

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.forms import inlineformset_factory
from django.shortcuts import redirect, render
from social_django.models import UserSocialAuth

from .forms import (
    ChangeEmailForm,
    CustomPasswordChangeForm,
    EducationForm,
    ProfileForm,
    SignUpForm,
    WorkExperienceForm,
)
from .models import Education, UserProfile, WorkExperience


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

    if request.method == "POST":
        form = ProfileForm(request.POST, instance=profile)
        work_formset = WorkExperienceFormSet(request.POST, instance=profile)
        education_formset = EducationFormSet(request.POST, instance=profile)

        if form.is_valid() and work_formset.is_valid() and education_formset.is_valid():
            has_changes = False

            if form.has_changed():
                form.save()
                has_changes = True

            work_instances = work_formset.save(commit=False)
            if work_instances or work_formset.deleted_objects:
                for instance in work_instances:
                    instance.save()
                for instance in work_formset.deleted_objects:
                    instance.delete()
                has_changes = True

            education_instances = education_formset.save(commit=False)
            if education_instances or education_formset.deleted_objects:
                for instance in education_instances:
                    instance.save()
                for instance in education_formset.deleted_objects:
                    instance.delete()
                has_changes = True

            if has_changes:
                messages.success(request, "个人资料已更新")
            else:
                messages.info(request, "未检测到任何更改")

            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=profile)
        work_formset = WorkExperienceFormSet(instance=profile)
        education_formset = EducationFormSet(instance=profile)

    return render(
        request,
        "profile_edit.html",
        {
            "form": form,
            "work_formset": work_formset,
            "education_formset": education_formset,
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
