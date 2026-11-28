from dataclasses import dataclass
from typing import Protocol

# Manifest types the registry may store. All of them are sent in Accept:
# without a type the registry falls back to the old schema or answers 404, and
# the returned digest would not match the pushed one.
DOCKER_MANIFEST = "application/vnd.docker.distribution.manifest.v2+json"
DOCKER_MANIFEST_LIST = "application/vnd.docker.distribution.manifest.list.v2+json"
OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
MANIFEST_MEDIA_TYPES = (DOCKER_MANIFEST, DOCKER_MANIFEST_LIST, OCI_MANIFEST, OCI_INDEX)
INDEX_MEDIA_TYPES = (DOCKER_MANIFEST_LIST, OCI_INDEX)


class RegistryError(Exception):
    """Raised when communication with the container registry fails."""
    ...


@dataclass(frozen=True)
class ManifestInfo:
    digest: str
    media_type: str
    # Compressed size in bytes (config + layers, summed over platforms)
    size: int | None


class RegistryClient(Protocol):
    def is_available(self) -> bool:
        ...

    def list_tags(self, path: str) -> list[str]:
        """Tag names of a repository; [] if the registry does not know it."""
        ...

    def get_digest(self, path: str, tag: str) -> str | None:
        """Digest the tag points to, or None if the tag does not exist."""
        ...

    def get_manifest(self, path: str, reference: str) -> ManifestInfo:
        ...

    def delete_manifest(self, path: str, digest: str) -> bool:
        """Delete a manifest; False if it was already gone."""
        ...

    def delete_repository(self, path: str) -> int:
        """Delete all manifests of a repository; returns how many were deleted."""
        ...
