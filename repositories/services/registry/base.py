from typing import Protocol

from repositories.models import Repository

class RegistryError(Exception):
    """Raised when communication with the container registry fails."""
    ...

class RegistryClient(Protocol):
    def is_available(self) -> bool:
        ...

    def list_tags(self, repository: Repository) -> list[dict]:
        ...