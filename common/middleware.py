"""Middleware for redirecting requests to the canonical host and API CORS."""

from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.http import HttpResponse, HttpResponsePermanentRedirect
from django.utils.cache import patch_vary_headers


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


class ApiCorsMiddleware:
    """Apply a minimal CORS policy for versioned API endpoints."""

    exposed_prefixes = ("/api/",)
    allowed_methods = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    allowed_headers = "Authorization, Content-Type"

    def __init__(self, get_response):
        """Initialize middleware state once per process."""
        self.get_response = get_response
        self.allowed_origins = {
            origin.rstrip("/")
            for origin in getattr(settings, "CORS_ALLOWED_ORIGINS", [])
            if origin
        }

    def __call__(self, request):
        """Short-circuit valid preflight requests and decorate API responses."""
        if not self._is_cors_request(request):
            return self.get_response(request)

        if request.method == "OPTIONS":
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)

        self._apply_headers(response, request.headers["Origin"])
        return response

    def _is_cors_request(self, request) -> bool:
        origin = request.headers.get("Origin")
        if not origin:
            return False

        normalized_origin = origin.rstrip("/")
        if normalized_origin not in self.allowed_origins:
            return False

        return any(request.path.startswith(prefix) for prefix in self.exposed_prefixes)

    def _apply_headers(self, response, origin: str) -> None:
        response["Access-Control-Allow-Origin"] = origin
        response["Access-Control-Allow-Methods"] = self.allowed_methods
        response["Access-Control-Allow-Headers"] = self.allowed_headers
        response["Access-Control-Max-Age"] = "86400"
        patch_vary_headers(response, ["Origin"])
