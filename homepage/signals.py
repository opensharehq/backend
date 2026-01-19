"""Signal handlers to keep homepage caches consistent."""

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .cache import bump_search_cache_version

User = get_user_model()
UserProfile = apps.get_model("accounts", "UserProfile")


def _invalidate_search_cache(*_, **__):
    bump_search_cache_version()


@receiver(post_save, sender=User)
@receiver(post_delete, sender=User)
@receiver(post_save, sender=UserProfile)
@receiver(post_delete, sender=UserProfile)
def invalidate_cache_on_user_updates(sender, **kwargs):
    """Reset cached search results when user identity data changes."""
    _invalidate_search_cache(sender, **kwargs)
