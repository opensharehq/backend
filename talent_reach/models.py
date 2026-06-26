"""Talent outreach data models."""

from django.conf import settings
from django.db import models


class OutreachDraft(models.Model):
    """Draft message for talent outreach."""

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="outreach_drafts",
    )
    title = models.CharField(max_length=200)
    content = models.TextField()  # Markdown body (English)
    title_zh = models.CharField(max_length=200, blank=True, default="")
    content_zh = models.TextField(blank=True, default="")  # Markdown body (Chinese)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Meta options."""

        ordering = ["-updated_at"]

    def __str__(self):
        """Return string representation."""
        return f"Draft: {self.title}"


class OutreachCampaign(models.Model):
    """A completed talent outreach campaign."""

    class Status(models.TextChoices):
        """Campaign status choices."""

        SENDING = "sending", "Sending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="outreach_campaigns",
    )
    title = models.CharField(max_length=200)
    content = models.TextField()  # Markdown body snapshot (English)
    title_zh = models.CharField(max_length=200, blank=True, default="")
    content_zh = models.TextField(blank=True, default="")  # Chinese body snapshot

    # Filter criteria (JSON for history display)
    tag_ids = models.JSONField(default=list)
    tag_names = models.JSONField(default=list)
    languages = models.JSONField(default=list)
    countries = models.JSONField(default=list)
    regions = models.JSONField(default=list)
    top_n = models.PositiveIntegerField(null=True, blank=True)

    # Points info
    point_type = models.CharField(max_length=10)  # cash / gift
    cost_per_user = models.PositiveIntegerField()
    total_cost = models.PositiveIntegerField()
    reward_ratio = models.FloatField()  # Reward ratio from env var (0-1)
    reward_pool = models.PositiveIntegerField()  # total_cost * reward_ratio
    reward_expiry_days = models.PositiveIntegerField()

    # Statistics
    total_recipients = models.PositiveIntegerField()
    delivered_count = models.PositiveIntegerField(default=0)
    read_count = models.PositiveIntegerField(default=0)
    rewarded_count = models.PositiveIntegerField(default=0)

    # Relations
    message = models.ForeignKey(
        "site_messages.Message",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    reference_id = models.CharField(
        max_length=100, blank=True
    )  # Points transaction reference

    # Status
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Meta options."""

        ordering = ["-created_at"]

    def __str__(self):
        """Return string representation."""
        return f"Campaign: {self.title} ({self.status})"


class OutreachRecipient(models.Model):
    """Per-recipient record for outreach campaigns (includes reading reward)."""

    campaign = models.ForeignKey(
        OutreachCampaign, on_delete=models.CASCADE, related_name="recipient_records"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    user_message = models.ForeignKey(
        "site_messages.UserMessage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    # Reading reward
    reward_amount = (
        models.PositiveIntegerField()
    )  # Per-user reward (proportional to OpenRank)
    openrank_score = models.FloatField(
        default=0
    )  # Snapshot of OpenRank score at allocation time
    is_rewarded = models.BooleanField(default=False)
    rewarded_at = models.DateTimeField(null=True, blank=True)
    reward_expired = models.BooleanField(default=False)  # Expired/forfeited flag

    class Meta:
        """Meta options."""

        unique_together = ("campaign", "user")

    def __str__(self):
        """Return string representation."""
        return f"Recipient: {self.user} (campaign={self.campaign_id})"
