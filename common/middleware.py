from urllib.parse import urlsplit, urlunsplit

from django.http import HttpResponsePermanentRedirect


class CanonicalHostRedirectMiddleware:
    """
    Redirects requests from open-share.cn to www.open-share.cn to enforce
    a single canonical host, keeping scheme, path, query, and non-standard ports.
    """

    source_host = "open-share.cn"
    target_host = "www.open-share.cn"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host_header = request.get_host()
        hostname, _, host_port = host_header.partition(":")
        hostname = hostname.lower()

        # 强制 HTTPS 重定向
        if not request.is_secure():
            return HttpResponsePermanentRedirect(
                self._build_redirect_url(request, host_port, is_secure=True)
            )

        if hostname == self.source_host:
            return HttpResponsePermanentRedirect(
                self._build_redirect_url(request, host_port, request.is_secure())
            )

        return self.get_response(request)

    def _build_redirect_url(self, request, host_port: str, is_secure: bool) -> str:
        scheme, _netloc, path, query, fragment = urlsplit(request.build_absolute_uri())
        scheme = "https" if is_secure else scheme
        port = host_port or request.get_port()

        # Preserve non-default ports (useful in staging), but drop default HTTP/S ports.
        if port not in {"80", "443"}:
            netloc = f"{self.target_host}:{port}"
        else:
            netloc = self.target_host

        return urlunsplit((scheme, netloc, path, query, fragment))
