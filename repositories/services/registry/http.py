import logging
from urllib.parse import urljoin

import requests
from django.conf import settings

from repositories.services.registry.auth import issue_internal_token
from repositories.services.registry.base import (
    INDEX_MEDIA_TYPES,
    MANIFEST_MEDIA_TYPES,
    ManifestInfo,
    RegistryError,
)

logger = logging.getLogger(__name__)

API_VERSION_HEADER = "Docker-Distribution-API-Version"
API_VERSION = "registry/2.0"


class HttpRegistryClient:
    """Client for a Distribution (registry:2) container, talks to its HTTP API v2."""

    def __init__(self, base_url=None, timeout=None):
        self.base_url = (base_url or settings.REGISTRY_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.REGISTRY_TIMEOUT

    def is_available(self) -> bool:
        """Return True if the registry answers the API v2 version check.

        401 also counts as available: the registry is running, it only
        requires authentication.
        """
        url = f"{self.base_url}/v2/"
        try:
            response = requests.get(url, timeout=self.timeout)
        except requests.RequestException as error:
            logger.warning("Registry not reachable: url=%s error=%s", url, error)
            return False

        if response.status_code not in (200, 401):
            logger.warning(
                "Registry returned an unexpected status: url=%s status=%s",
                url,
                response.status_code,
            )
            return False

        if response.headers.get(API_VERSION_HEADER) != API_VERSION:
            logger.warning(
                "Server is not a Docker registry (missing %s header): url=%s",
                API_VERSION_HEADER,
                url,
            )
            return False

        return True

    # Registry API v2. Every call carries a token signed by the application
    # (issue_internal_token), limited to the repository and the action.

    def _request(self, method, url, actions, path, **kwargs):
        access = [{"type": "repository", "name": path, "actions": actions}]
        headers = {"Authorization": f"Bearer {issue_internal_token(access)}", **kwargs.pop("headers", {})}
        if not url.startswith("http"):
            url = urljoin(self.base_url, url)
        try:
            response = requests.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
        except requests.RequestException as error:
            raise RegistryError(f"{method} {url} failed: {error}") from error
        if response.status_code in (401, 403):
            raise RegistryError(f"{method} {url} was not authorized ({response.status_code})")
        return response

    def _manifest_request(self, method, path, reference, actions=("pull",)):
        return self._request(
            method,
            f"/v2/{path}/manifests/{reference}",
            list(actions),
            path,
            headers={"Accept": ", ".join(MANIFEST_MEDIA_TYPES)},
        )

    @staticmethod
    def _check(response, expected=(200,)):
        if response.status_code not in expected:
            raise RegistryError(
                f"{response.request.method} {response.url} returned {response.status_code}"
            )

    def list_tags(self, path):
        tags = []
        url = f"/v2/{path}/tags/list?n=100"
        while url:
            response = self._request("GET", url, ["pull"], path)
            if response.status_code == 404:
                # NAME_UNKNOWN: nothing was pushed yet
                return []
            self._check(response)
            # An emptied repository answers {"tags": null}
            tags.extend(response.json().get("tags") or [])
            url = response.links.get("next", {}).get("url")
        return tags

    def get_digest(self, path, tag):
        response = self._manifest_request("HEAD", path, tag)
        if response.status_code == 404:
            return None
        self._check(response)
        digest = response.headers.get("Docker-Content-Digest")
        if not digest:
            raise RegistryError(f"No digest for {path}:{tag}")
        return digest

    def get_manifest(self, path, reference):
        response = self._manifest_request("GET", path, reference)
        self._check(response)
        manifest = response.json()
        media_type = manifest.get("mediaType") or response.headers.get("Content-Type", "")
        digest = response.headers.get("Docker-Content-Digest") or reference

        if media_type in INDEX_MEDIA_TYPES:
            size = 0
            for child in manifest.get("manifests", []):
                if self._is_attestation(child) or child.get("mediaType") in INDEX_MEDIA_TYPES:
                    continue
                size += self._image_size(self._get_json(path, child["digest"]))
        else:
            size = self._image_size(manifest)

        return ManifestInfo(digest=digest, media_type=media_type, size=size)

    def _get_json(self, path, digest):
        response = self._manifest_request("GET", path, digest)
        self._check(response)
        return response.json()

    @staticmethod
    def _is_attestation(descriptor):
        # buildx stores provenance/SBOM as extra manifests with platform unknown/unknown
        annotations = descriptor.get("annotations") or {}
        platform = descriptor.get("platform") or {}
        return (
            annotations.get("vnd.docker.reference.type") == "attestation-manifest"
            or platform.get("os") == "unknown"
        )

    @staticmethod
    def _image_size(manifest):
        config = manifest.get("config") or {}
        return config.get("size", 0) + sum(layer.get("size", 0) for layer in manifest.get("layers", []))

    def delete_manifest(self, path, digest):
        response = self._manifest_request("DELETE", path, digest, actions=("delete",))
        if response.status_code == 404:
            # Already deleted, e.g. two tags pointed to the same digest
            return False
        self._check(response, expected=(202,))
        return True

    def delete_repository(self, path):
        digests = []
        for tag in self.list_tags(path):
            digest = self.get_digest(path, tag)
            if digest and digest not in digests:
                digests.append(digest)
        return sum(self.delete_manifest(path, digest) for digest in digests)
