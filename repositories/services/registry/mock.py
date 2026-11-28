class MockRegistryClient:
    """Registry without images, for runserver, tests and CI (no container needed).

    Tags come from ``docker push`` to the real registry, so the mock has none;
    deleting always succeeds.
    """

    def is_available(self):
        return True

    def list_tags(self, path):
        return []

    def get_digest(self, path, tag):
        return None

    def get_manifest(self, path, reference):
        raise LookupError(f"{path}@{reference} does not exist in the mock registry")

    def delete_manifest(self, path, digest):
        return False

    def delete_repository(self, path):
        return 0
