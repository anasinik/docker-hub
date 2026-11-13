from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from .validators import USERNAME_MAX_LENGTH, validate_username_format


class Role(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN", "Super admin"
    ADMIN = "ADMIN", "Admin"
    REGULAR_USER = "REGULAR_USER", "Regular user"

class Badge(models.TextChoices):
    NONE = "NONE", "", 
    VERIFIED_PUBLISHER = "VERIFIED_PUBLISHER", "Verified publisher" 
    SPONSORED_OSS = "SPONSORED_OSS", "Sponsored OSS"


ADMIN_ROLES = (Role.SUPER_ADMIN, Role.ADMIN)


class UserManager(DjangoUserManager):
    def create_admin(self, username, email=None, password=None, **extra_fields):
        extra_fields["role"] = Role.ADMIN
        return self.create_user(username, email, password, **extra_fields)

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields["role"] = Role.SUPER_ADMIN
        return super().create_superuser(username, email, password, **extra_fields)

    def admins(self):
        """Both administrator roles (super admin included)."""
        return self.filter(role__in=ADMIN_ROLES)

    def regular_users(self):
        return self.filter(role=Role.REGULAR_USER)


class User(AbstractUser):
    """Application user.

    Access control is driven by ``role``. Django's ``is_superuser`` and
    ``is_staff`` flags are derived from it on every save, so they never need to
    be set by hand:

    * SUPER_ADMIN  -> is_superuser=True,  is_staff=True (exactly one may exist)
    * ADMIN        -> is_superuser=False, is_staff=True
    * REGULAR_USER -> is_superuser=False, is_staff=False
    """

    username = models.CharField(
        "username",
        max_length=USERNAME_MAX_LENGTH,
        unique=True,
        validators=[validate_username_format],
        help_text="4-30 characters. Lowercase letters and digits only.",
        error_messages={"unique": "A user with that username already exists."},
    )
    email = models.EmailField("email address")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.REGULAR_USER)
    badge = models.CharField(max_length=20, choices=Badge.choices, default=Badge.NONE, blank=True)

    objects = UserManager()

    class Meta(AbstractUser.Meta):
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                condition=~Q(email=""),
                name="unique_user_email_ci",
                violation_error_message="A user with this email already exists.",
            ),
            models.UniqueConstraint(
                fields=["role"],
                condition=Q(role=Role.SUPER_ADMIN),
                name="unique_super_admin",
                violation_error_message="A super admin already exists.",
            ),
        ]

    def __str__(self):
        return self.username

    @property
    def is_super_admin(self):
        return self.role == Role.SUPER_ADMIN

    @property
    def is_admin(self):
        """True for both administrator roles; the super admin is also an admin."""
        return self.role in ADMIN_ROLES

    @property
    def is_regular_user(self):
        return self.role == Role.REGULAR_USER

    def sync_flags_with_role(self):
        self.is_superuser = self.is_super_admin
        self.is_staff = self.is_admin

    def save(self, *args, **kwargs):
        self.sync_flags_with_role()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "role" in update_fields:
            kwargs["update_fields"] = {*update_fields, "is_superuser", "is_staff"}
        super().save(*args, **kwargs)
