"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/

Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))

"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from accounts.views import public_profile_view

# Import admin customization to apply settings
from config import admin as _admin_config  # noqa: F401

urlpatterns = [
    path("admin/doc/", include("django.contrib.admindocs.urls")),
    path("admin/", admin.site.urls),
    path("", include("social_django.urls", namespace="social")),
    path("accounts/", include("accounts.urls")),
    path("messages/", include("messages.urls")),
    path("points/", include("points.urls")),
    path("", include("homepage.urls")),
    # Public profile route - must be last to avoid conflicts
    path("<str:username>/", public_profile_view, name="public_profile"),
]

if settings.DEBUG and not settings.TESTING:
    try:
        from debug_toolbar.toolbar import debug_toolbar_urls
    except ImportError:
        pass
    else:
        urlpatterns = [*urlpatterns, *debug_toolbar_urls()]
