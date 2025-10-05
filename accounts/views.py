from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.forms import inlineformset_factory
from django.shortcuts import redirect, render

from .forms import EducationForm, ProfileForm, SignUpForm, WorkExperienceForm
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
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    return render(request, "profile.html", {"profile": profile})


@login_required
def profile_edit_view(request):
    """Handle profile editing with Bootstrap 5 form."""
    profile, created = UserProfile.objects.get_or_create(user=request.user)

    WorkExperienceFormSet = inlineformset_factory(
        UserProfile,
        WorkExperience,
        form=WorkExperienceForm,
        extra=1,
        can_delete=True,
    )

    EducationFormSet = inlineformset_factory(
        UserProfile,
        Education,
        form=EducationForm,
        extra=1,
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
