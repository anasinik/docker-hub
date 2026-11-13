from django.conf import settings
from django.db import models

from .validators import (
    REPOSITORY_DESCRIPTION_MAX_LENGTH,
    REPOSITORY_NAME_MAX_LENGTH,
    validate_repository_name,
)


class Visibility(models.TextChoices):
    PUBLIC = "PUBLIC", "Public"
    PRIVATE = "PRIVATE", "Private"


class Repository(models.Model):
    """A container image repository owned by a user.

    Images are addressed as ``<owner username>/<name>``, see ``registry_path``.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="repositories",
    )
    name = models.CharField(
        max_length=REPOSITORY_NAME_MAX_LENGTH,
        validators=[validate_repository_name],
        help_text=(
            "2-100 characters. Lowercase letters and digits, "
            "optionally separated by ., _ or -."
        ),
    )
    description = models.CharField(
        max_length=REPOSITORY_DESCRIPTION_MAX_LENGTH,
        blank=True,
        help_text=f"Optional short description, up to {REPOSITORY_DESCRIPTION_MAX_LENGTH} characters.",
    )
    visibility = models.CharField(
        max_length=10,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
    )
    is_official = models.BooleanField(default=False)
    starred_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="RepositoryStar",
        related_name="starred_repositories",
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "repositories"
        ordering = ["owner__username", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "name"],
                name="unique_repository_per_owner",
                violation_error_message="You already have a repository with this name.",
            ),
        ]

    def __str__(self):
        return self.registry_path

    @property
    def registry_path(self):
        """Path used to push and pull images, e.g. ``alice/my-app``."""
        return f"{self.owner.username}/{self.name}"

    @property
    def is_public(self):
        return self.visibility == Visibility.PUBLIC


class RepositoryStar(models.Model):
    repository = models.ForeignKey(
        Repository,
        on_delete=models.CASCADE,
        related_name="star_records",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="repository_star_records",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["repository", "user"],
                name="unique_repository_star",
            ),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} starred {self.repository}"