"""URL configuration for accounts app."""

from django.urls import path

from .views import (
    accounts_index,
    change_email_view,
    change_password_view,
    disconnect_social_account,
    logout_view,
    password_reset_confirm_view,
    password_reset_done_view,
    password_reset_request_view,
    profile_edit_view,
    profile_view,
    redeem_confirm_view,
    redemption_list_view,
    shipping_address_create_guide_view,
    shipping_address_create_view,
    shipping_address_delete_view,
    shipping_address_edit_view,
    shipping_address_list_view,
    shipping_address_set_default_view,
    shop_list_view,
    sign_in_view,
    sign_up_view,
    social_connections_view,
)

app_name = "accounts"

urlpatterns = [
    path("", accounts_index, name="index"),
    path("login/", sign_in_view, name="sign_in"),
    path("signup/", sign_up_view, name="sign_up"),
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
    path(
        "password-reset/",
        password_reset_request_view,
        name="password_reset_request",
    ),
    path("password-reset/done/", password_reset_done_view, name="password_reset_done"),
    path(
        "password-reset-confirm/<uidb64>/<token>/",
        password_reset_confirm_view,
        name="password_reset_confirm",
    ),
    # Shop and redemption URLs
    path("shop/", shop_list_view, name="shop_list"),
    path("redemption/", redemption_list_view, name="redemption_list"),
    path("redeem/<int:item_id>/", redeem_confirm_view, name="redeem_confirm"),
    # Shipping address URLs
    path(
        "shipping-addresses/",
        shipping_address_list_view,
        name="shipping_address_list",
    ),
    path(
        "shipping-addresses/create/",
        shipping_address_create_view,
        name="shipping_address_create",
    ),
    path(
        "shipping-addresses/create-for-item/<int:item_id>/",
        shipping_address_create_guide_view,
        name="shipping_address_create_guide",
    ),
    path(
        "shipping-addresses/<int:address_id>/edit/",
        shipping_address_edit_view,
        name="shipping_address_edit",
    ),
    path(
        "shipping-addresses/<int:address_id>/delete/",
        shipping_address_delete_view,
        name="shipping_address_delete",
    ),
    path(
        "shipping-addresses/<int:address_id>/set-default/",
        shipping_address_set_default_view,
        name="shipping_address_set_default",
    ),
]
