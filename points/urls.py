"""URL configuration for points application."""

from django.urls import path

from . import views

app_name = "points"

urlpatterns = [
    # 用户钱包
    path("wallet/", views.user_wallet_view, name="user_wallet"),
    path(
        "wallet/transactions/", views.user_transactions_view, name="user_transactions"
    ),
    # 提现
    path("withdraw/", views.create_withdrawal_view, name="create_withdrawal"),
    path("withdrawals/", views.withdrawal_list_view, name="withdrawal_list"),
    path(
        "withdrawals/<int:pk>/cancel/",
        views.cancel_withdrawal_view,
        name="cancel_withdrawal",
    ),
    # 组织钱包
    path("org/<slug:slug>/wallet/", views.org_wallet_view, name="org_wallet"),
    path(
        "org/<slug:slug>/transactions/",
        views.org_transactions_view,
        name="org_transactions",
    ),
    path(
        "org/<slug:slug>/withdraw/",
        views.org_create_withdrawal_view,
        name="org_create_withdrawal",
    ),
]
