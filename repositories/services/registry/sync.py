"""Mirror the tags of a repository from the registry into the ``Tag`` table.

The registry is the source of truth. A sync reads the tag list, asks for each
tag's digest (HEAD, cheap) and downloads a manifest only when the digest is new
or changed, so syncing a repository that did not change costs one request per
tag.
"""

import logging
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from repositories.models import Tag
from repositories.services.registry.base import RegistryError
from repositories.services.registry.factory import get_registry_client
from repositories.services.registry.mock import MockRegistryClient

logger = logging.getLogger(__name__)


class SyncNotConfiguredError(RegistryError):
    """The configured client cannot sync (MockRegistryClient has no images)."""


def get_sync_client():
    """Return the configured registry client, or raise if it is the mock.

    The mock has no images, so a sync with it would delete every tag in the
    database. A missing REGISTRY_CLIENT_CLASS must not cost the tag history.
    """
    return check_sync_client(get_registry_client())


def check_sync_client(client):
    if isinstance(client, MockRegistryClient):
        raise SyncNotConfiguredError(
            "REGISTRY_CLIENT_CLASS is MockRegistryClient, which has no images; set it to "
            "repositories.services.registry.http.HttpRegistryClient to sync tags."
        )
    return client


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    removed: int = 0

    @property
    def changed(self):
        return bool(self.added or self.updated or self.removed)


def sync_repository(repository, pushed_at=None, client=None):
    """Bring ``repository.tags`` in line with the registry.

    ``pushed_at`` maps tag names to their push event time. New and changed tags
    get that time, or the current time if their push is not in it; tags whose
    digest did not change keep their time. Raises ``RegistryError`` before
    changing anything if the registry cannot be read, and
    ``SyncNotConfiguredError`` if the client is the mock.
    """
    client = check_sync_client(client) if client is not None else get_sync_client()
    path = repository.registry_path
    pushed_at = pushed_at or {}
    now = timezone.now()

    # Read everything from the registry first, then write in one transaction.
    known = dict(repository.tags.values_list("name", "digest"))
    current = {}
    for name in client.list_tags(path):
        digest = client.get_digest(path, name)
        if digest is None:
            # Removed between listing and HEAD
            continue
        current[name] = None if known.get(name) == digest else client.get_manifest(path, digest)

    try:
        result = _write_tags(repository, current, pushed_at, now)
    except IntegrityError:
        # Another sync of the same repository (the registry retries slow
        # notifications) created a tag in the meantime; the rows exist now.
        result = _write_tags(repository, current, pushed_at, now)

    if result.changed:
        logger.info(
            "Tags synced: path=%s added=%s updated=%s removed=%s",
            path,
            result.added,
            result.updated,
            result.removed,
            extra={"repo_id": repository.pk},
        )
    return result


def _write_tags(repository, current, pushed_at, now):
    result = SyncResult()
    with transaction.atomic():
        for name, manifest in current.items():
            if manifest is None:
                continue
            _, created = Tag.objects.update_or_create(
                repository=repository,
                name=name,
                defaults={
                    "digest": manifest.digest,
                    "media_type": manifest.media_type,
                    "size": manifest.size,
                    "pushed_at": pushed_at.get(name) or now,
                },
            )
            if created:
                result.added += 1
            else:
                result.updated += 1

        result.removed = repository.tags.exclude(name__in=list(current)).delete()[0]
    return result
