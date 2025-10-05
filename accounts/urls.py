"""URL configuration for accounts app."""

from django.urls import path

from .views import (
    accounts_index,
    change_email_view,
    change_password_view,
    disconnect_social_account,
    logout_view,
    profile_edit_view,
    profile_view,
    sign_in_view,
    sign_up_view,
    social_connections_view,
)

app_name = "accounts"

urlpatterns = [
    path("", accounts_index, name="index"),
    path("sign-in/", sign_in_view, name="sign_in"),
    path("sign-up/", sign_up_view, name="sign_up"),
    path("profile/", profile_view, name="profile"),
    path("profile/edit/", profile_edit_view, name="profile_edit"),
    path("logout/", logout_view, name="logout"),
    path(
        "social-connections/",
        social_connections_view,
        name="social_connections",
    ),
    path(
        "social-connections/disconnect/<str:provider>/<int:association_id>/",
        disconnect_social_account,
        name="disconnect_social",
    ),
    path("change-password/", change_password_view, name="change_password"),
    path("change-email/", change_email_view, name="change_email"),
]
