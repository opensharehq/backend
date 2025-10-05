"""Django admin configuration for accounts app."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Education, User, UserProfile, WorkExperience


class WorkExperienceInline(admin.TabularInline):
    """Inline admin for work experience."""

    model = WorkExperience
    extra = 0
    fields = ("company_name", "title", "start_date", "end_date", "description")


class EducationInline(admin.TabularInline):
    """Inline admin for education."""

    model = Education
    extra = 0
    fields = ("institution_name", "degree", "field_of_study", "start_date", "end_date")


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Custom admin for User model."""

    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_staff",
        "is_active",
        "date_joined",
        "display_total_points",
    )
    list_filter = ("is_staff", "is_superuser", "is_active", "date_joined")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("-date_joined",)
    date_hierarchy = "date_joined"

    @admin.display(description="总积分", ordering="username")
    def display_total_points(self, obj):
        """Display total points for the user."""
        return obj.total_points


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """Admin for UserProfile model."""

    list_display = (
        "user",
        "company",
        "location",
        "birth_date",
        "has_bio",
    )
    list_filter = ("company", "location")
    search_fields = (
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
        "company",
        "location",
        "bio",
    )
    readonly_fields = ("user",)
    inlines = [WorkExperienceInline, EducationInline]

    fieldsets = (
        (
            "基本信息",
            {
                "fields": ("user", "bio", "birth_date"),
            },
        ),
        (
            "工作信息",
            {
                "fields": ("company", "location"),
            },
        ),
        (
            "社交链接",
            {
                "fields": (
                    "github_url",
                    "homepage_url",
                    "blog_url",
                    "twitter_url",
                    "linkedin_url",
                ),
            },
        ),
    )

    @admin.display(boolean=True, description="是否有简介")
    def has_bio(self, obj):
        """Check if user has a bio."""
        return bool(obj.bio)


@admin.register(WorkExperience)
class WorkExperienceAdmin(admin.ModelAdmin):
    """Admin for WorkExperience model."""

    list_display = (
        "profile",
        "company_name",
        "title",
        "start_date",
        "end_date",
        "is_current",
    )
    list_filter = ("company_name", "start_date", "end_date")
    search_fields = (
        "profile__user__username",
        "company_name",
        "title",
        "description",
    )
    ordering = ("-start_date",)
    date_hierarchy = "start_date"

    @admin.display(boolean=True, description="在职中")
    def is_current(self, obj):
        """Check if this is current employment."""
        return obj.end_date is None


@admin.register(Education)
class EducationAdmin(admin.ModelAdmin):
    """Admin for Education model."""

    list_display = (
        "profile",
        "institution_name",
        "degree",
        "field_of_study",
        "start_date",
        "end_date",
    )
    list_filter = ("degree", "institution_name", "start_date")
    search_fields = (
        "profile__user__username",
        "institution_name",
        "degree",
        "field_of_study",
    )
    ordering = ("-start_date",)
    date_hierarchy = "start_date"
