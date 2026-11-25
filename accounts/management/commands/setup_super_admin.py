"""Create the single super admin when the system is started for the first time."""

import logging
import os
import secrets

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction

from accounts.models import Role, User
from accounts.validators import validate_username_format

logger = logging.getLogger(__name__)

PASSWORD_ATTEMPTS = 5


def generate_password(user):
    """Random password that passes AUTH_PASSWORD_VALIDATORS."""
    for _ in range(PASSWORD_ATTEMPTS):
        password = secrets.token_urlsafe(18)
        try:
            validate_password(password, user)
        except ValidationError:
            continue
        return password
    raise CommandError("Could not generate a password that passes the password validators.")


def write_password_file(path, password):
    """Write the password to ``path``, readable only by the owner (on POSIX)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # The mode is applied when the file is created, so the password is never
    # readable by others, not even briefly. chmod covers an existing file.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(password + "\n")
    os.chmod(path, 0o600)


class Command(BaseCommand):
    help = (
        "Create the super admin with a generated password, written to SUPER_ADMIN_PASSWORD_FILE. "
        "The password must be changed at the first sign-in. Does nothing if a super admin exists."
    )

    def handle(self, *args, **options):
        existing = User.objects.filter(role=Role.SUPER_ADMIN).first()
        if existing is not None:
            self.stdout.write(f"Super admin already exists: {existing.username}. Nothing to do.")
            return

        username = settings.SUPER_ADMIN_USERNAME
        email = settings.SUPER_ADMIN_EMAIL
        self.validate(username, email)

        path = settings.SUPER_ADMIN_PASSWORD_FILE
        try:
            with transaction.atomic():
                user = User(username=username, email=email, role=Role.SUPER_ADMIN, password_change_required=True)
                password = generate_password(user)
                user.set_password(password)
                user.save()
                # Inside the transaction: if the file cannot be written, the
                # account is not created, so nobody is locked out.
                write_password_file(path, password)
        except IntegrityError as error:
            # Another process created the super admin in the meantime.
            raise CommandError(f"Super admin could not be created: {error}") from error
        except OSError as error:
            raise CommandError(f"Cannot write the password file {path}: {error}") from error

        logger.info("Super admin created: username=%s id=%s password_file=%s", user.username, user.pk, path)
        self.stdout.write(self.style.SUCCESS(f"Super admin created: {user.username}"))
        self.stdout.write(self.style.SUCCESS(f"Initial password written to: {path}"))
        self.stdout.write("Sign in with it; the password must be changed before the account can be used.")

    def validate(self, username, email):
        try:
            validate_username_format(username)
        except ValidationError as error:
            raise CommandError(f"SUPER_ADMIN_USERNAME {username!r}: {' '.join(error.messages)}") from error
        try:
            validate_email(email)
        except ValidationError as error:
            raise CommandError(f"SUPER_ADMIN_EMAIL {email!r}: {' '.join(error.messages)}") from error

        if User.objects.filter(username=username).exists():
            raise CommandError(
                f"User {username!r} already exists and is not the super admin. Set SUPER_ADMIN_USERNAME to another name."
            )
        if User.objects.filter(email__iexact=email).exists():
            raise CommandError(f"Email {email!r} is already used. Set SUPER_ADMIN_EMAIL to another address.")
