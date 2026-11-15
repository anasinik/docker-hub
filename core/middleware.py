import logging
import time

from django.conf import settings

logger = logging.getLogger("dockerhub.requests")


class RequestLoggingMiddleware:
    """Log one line per HTTP request."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.skip_prefixes = tuple(getattr(settings, "LOG_REQUESTS_SKIP_PREFIXES", ()))

    def __call__(self, request):
        if request.path.startswith(self.skip_prefixes):
            return self.get_response(request)

        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - start) * 1000, 1)

        status = response.status_code
        if status >= 500:
            level = logging.ERROR
        elif status >= 400:
            level = logging.WARNING
        else:
            level = logging.INFO

        # request.user is missing when an earlier middleware answered before
        user = getattr(request, "user", None)
        username = user.get_username() if user is not None and user.is_authenticated else None
        ip = request.META.get("REMOTE_ADDR")
        path = repr(request.path)[1:-1]  # escape newlines so nobody can fake log lines

        logger.log(
            level,
            "%s %s %s %.1fms user=%s ip=%s",
            request.method, path, status, duration_ms, username or "-", ip,
            extra={
                "http_method": request.method,
                "http_path": request.path,
                "http_status": status,
                "duration_ms": duration_ms,
                "username": username,
                "client_ip": ip,
            },
        )
        return response