"""Admin configuration for talent_reach models."""

from django.contrib import admin

from .models import OutreachCampaign, OutreachDraft, OutreachRecipient


@admin.register(OutreachDraft)
class OutreachDraftAdmin(admin.ModelAdmin):
    """Admin for OutreachDraft."""

    list_display = ("title", "author", "created_at", "updated_at")
    list_filter = ("author", "created_at")
    search_fields = ("title", "content")
    readonly_fields = ("created_at", "updated_at")


@admin.register(OutreachCampaign)
class OutreachCampaignAdmin(admin.ModelAdmin):
    """Admin for OutreachCampaign."""

    list_display = (
        "title",
        "author",
        "status",
        "total_recipients",
        "delivered_count",
        "read_count",
        "rewarded_count",
        "point_type",
        "total_cost",
        "created_at",
    )
    list_filter = ("status", "point_type", "created_at", "author")
    search_fields = ("title", "reference_id")
    readonly_fields = ("created_at", "completed_at")


@admin.register(OutreachRecipient)
class OutreachRecipientAdmin(admin.ModelAdmin):
    """Admin for OutreachRecipient."""

    list_display = (
        "campaign",
        "user",
        "reward_amount",
        "openrank_score",
        "is_rewarded",
        "reward_expired",
        "rewarded_at",
    )
    list_filter = ("is_rewarded", "reward_expired", "campaign")
    search_fields = ("user__username",)
    readonly_fields = ("rewarded_at",)
