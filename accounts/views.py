from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import SignUpForm


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
    return render(request, "profile.html")


@login_required
def logout_view(request):
    """Log out the current user and redirect to homepage."""
    logout(request)
    messages.success(request, "您已成功退出登录")
    return redirect("homepage:index")
