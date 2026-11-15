"""Log authentication events, so they can be searched in the Analytics section."""

import logging

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def client_ip(request):
    return request.META.get("REMOTE_ADDR") if request is not None else None


@receiver(user_logged_in)
def log_login(sender, request, user, **kwargs):
    logger.info("User logged in: username=%s id=%s ip=%s", user.username, user.pk, client_ip(request))


@receiver(user_logged_out)
def log_logout(sender, request, user, **kwargs):
    if user is not None:
        logger.info("User logged out: username=%s id=%s ip=%s", user.username, user.pk, client_ip(request))


@receiver(user_login_failed)
def log_login_failed(sender, credentials, request=None, **kwargs):
    # Django has already masked the password in ``credentials``. The username
    # is user input, so %r keeps newlines from forging extra log lines.
    logger.warning("Login failed: username=%r ip=%s", credentials.get("username"), client_ip(request))
