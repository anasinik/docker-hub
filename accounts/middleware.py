from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse


class PasswordChangeRequiredMiddleware:
    """Keep users with ``password_change_required`` on the password change page.

    Until the password is changed, every other page (the Django admin included)
    redirects there; only signing out, static files and the health check stay
    available. Must come after ``AuthenticationMiddleware``.

    The registry token endpoint does not use the session, so it checks the
    flag itself (``RegistryTokenView``).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.password_change_required:
            change_url = reverse("accounts:password_change")
            if not self.is_allowed(request.path, change_url):
                return self.redirect(request, change_url)
        return self.get_response(request)

    def is_allowed(self, path, change_url):
        allowed = (change_url, reverse("accounts:logout"), reverse("core:health"))
        static_prefix = "/" + settings.STATIC_URL.lstrip("/")
        return path in allowed or path.startswith(static_prefix)

    def redirect(self, request, url):
        if request.headers.get("HX-Request") == "true":
            # htmx follows a 302 inside the XHR and would swap the whole page
            # into the target; HX-Redirect makes the browser navigate instead.
            response = HttpResponse(status=204)
            response["HX-Redirect"] = url
            return response
        return redirect(url)
