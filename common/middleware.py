"""Middleware for redirecting requests to the canonical host."""

from urllib.parse import urlsplit, urlunsplit

from django.http import HttpResponsePermanentRedirect


class CanonicalHostRedirectMiddleware:
    """Redirect requests to the canonical domain while preserving scheme, path, query, and ports."""

    source_host = "www.open-share.cn"
    target_host = "open-share.cn"

    def __init__(self, get_response):
        """Initialize the middleware with the given get_response callable."""
        self.get_response = get_response

    def __call__(self, request):
        """Process the request and redirect if the host matches the source host."""
        host_header = request.get_host()
        hostname, _, host_port = host_header.partition(":")
        hostname = hostname.lower()

        if hostname == self.source_host:
            return HttpResponsePermanentRedirect(
                self._build_redirect_url(request, host_port, True)
            )

        return self.get_response(request)

    def _build_redirect_url(self, request, host_port: str, is_secure: bool) -> str:
        scheme, _netloc, path, query, fragment = urlsplit(request.build_absolute_uri())
        scheme = "https" if is_secure else scheme
        netloc = self.target_host
        return urlunsplit((scheme, netloc, path, query, fragment))

    def _determine_port(self, host_port: str, request) -> str:
        """Pick the client-visible port when the Host header or trusted proxy supplies it."""
        if host_port:
            return host_port

        forwarded_port = (
            request.headers.get("X-Forwarded-Port", "").split(",")[0].strip()
        )
        if forwarded_port:
            return forwarded_port

        return ""
