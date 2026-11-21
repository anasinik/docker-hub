import logging

import requests
from django.conf import settings

from repositories.services.registry.base import RegistryError

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

    def list_tags(self, repository):
        # Implemented in #26 (sync pushed images and tags). RegistryError lets
        # the repository detail page show "registry unavailable" instead of failing.
        raise RegistryError("Listing tags from the registry is not implemented yet.")
