"""Middleware for redirecting requests to the canonical host."""

from urllib.parse import urlsplit, urlunsplit

from django.http import HttpResponsePermanentRedirect


class CanonicalHostRedirectMiddleware:
    """Redirect requests to the canonical domain while preserving path and query."""

    source_host = "www.open-share.cn"
    target_host = "open-share.cn"

    def __init__(self, get_response):
        """Initialize the middleware with the given get_response callable."""
        self.get_response = get_response

    def __call__(self, request):
        """Process the request and redirect if the host matches the source host."""
        hostname = request.get_host().partition(":")[0].lower()

        if hostname == self.source_host:
            return HttpResponsePermanentRedirect(self._build_redirect_url(request))

        return self.get_response(request)

    def _build_redirect_url(self, request) -> str:
        _scheme, _netloc, path, query, fragment = urlsplit(request.build_absolute_uri())
        netloc = self.target_host
        return urlunsplit(("https", netloc, path, query, fragment))
