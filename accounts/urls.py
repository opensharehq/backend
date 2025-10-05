from django.urls import path

from .views import accounts_index, logout_view, profile_view, sign_in_view, sign_up_view

app_name = "accounts"

urlpatterns = [
    path("", accounts_index, name="index"),
    path("sign-in/", sign_in_view, name="sign_in"),
    path("sign-up/", sign_up_view, name="sign_up"),
    path("profile/", profile_view, name="profile"),
    path("logout/", logout_view, name="logout"),
]
