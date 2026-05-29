"""
Custom Django Admin site backed by GitHub OAuth login.

The default admin login form (username/password) is disabled. Any unauthenticated
visitor to the admin is redirected to the GitHub OAuth begin endpoint that
``social_django`` exposes; authenticated but non-staff users get a dedicated
no-permission page instead of an empty login form.
"""

from urllib.parse import urlencode

from django.contrib.admin.sites import AdminSite
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse


class GitHubAdminSite(AdminSite):
    """Admin site that delegates authentication to GitHub OAuth."""

    site_header = "OpenShare 管理后台"
    site_title = "OpenShare 管理后台"
    index_title = "欢迎使用 OpenShare 管理后台"

    def login(self, request, extra_context=None):
        """
        Replace the username/password form with a GitHub OAuth redirect.

        - Already-authenticated staff users are sent to the admin index.
        - Authenticated non-staff users see ``admin/no_permission.html``.
        - Anonymous users are redirected to ``social:begin`` for ``github``
          with the original ``next`` URL preserved.
        """
        if request.user.is_authenticated:
            if self.has_permission(request):
                index_path = reverse(f"{self.name}:index", current_app=self.name)
                return HttpResponseRedirect(index_path)
            context = {
                "site_header": self.site_header,
                "site_title": self.site_title,
                "user": request.user,
            }
            return render(request, "admin/no_permission.html", context, status=403)

        next_url = (
            request.GET.get("next")
            or request.POST.get("next")
            or reverse(f"{self.name}:index", current_app=self.name)
        )
        oauth_begin_url = reverse("social:begin", args=["github"])
        params = urlencode({"next": next_url})
        return HttpResponseRedirect(f"{oauth_begin_url}?{params}")
