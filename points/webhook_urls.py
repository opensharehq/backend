"""URL configuration for external webhooks."""

from django.urls import path

from points import webhooks

app_name = "points_webhooks"

urlpatterns = [
    path(
        "fdd/withdrawal-contract/",
        webhooks.fdd_withdrawal_contract_webhook,
        name="fdd_withdrawal_contract_webhook",
    ),
]
