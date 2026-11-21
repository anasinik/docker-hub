from django.core.management.base import BaseCommand, CommandError

from repositories.services.registry.http import HttpRegistryClient


class Command(BaseCommand):
    help = "Check that the container registry at REGISTRY_URL is reachable."

    def handle(self, *args, **options):
        client = HttpRegistryClient()
        if not client.is_available():
            raise CommandError(
                f"Registry is not reachable at {client.base_url} "
                "(is the registry container running?)."
            )
        self.stdout.write(self.style.SUCCESS(f"Registry at {client.base_url} is available."))
