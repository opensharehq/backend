"""URL configuration for points app."""

from django.urls import path

from . import views

app_name = "points"

urlpatterns = [
    path("points/", views.my_points, name="my_points"),
    # Withdrawal URLs
    path(
        "withdrawal/create/<int:point_source_id>/",
        views.withdrawal_create,
        name="withdrawal_create",
    ),
    path("withdrawal/batch/", views.batch_withdrawal, name="batch_withdrawal"),
    path("withdrawal/", views.withdrawal_list, name="withdrawal_list"),
    path(
        "withdrawal/<int:withdrawal_id>/",
        views.withdrawal_detail,
        name="withdrawal_detail",
    ),
    path(
        "withdrawal/<int:withdrawal_id>/cancel/",
        views.withdrawal_cancel,
        name="withdrawal_cancel",
    ),
    # Recharge URL
    path(
        "recharge/<int:point_source_id>/",
        views.recharge,
        name="recharge",
    ),
]
