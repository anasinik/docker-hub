import logging

from django.core.management.base import BaseCommand, CommandError

from repositories.models import Repository
from repositories.services.registry.auth import find_repository
from repositories.services.registry.base import RegistryError
from repositories.services.registry.sync import SyncNotConfiguredError, get_sync_client, sync_repository

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Sync tags from the container registry into the database. Pushes are synced "
        "automatically (registry notifications); use this after downtime or to repair."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--repository",
            metavar="PATH",
            help="Only this repository, e.g. alice/web (official: nginx).",
        )

    def handle(self, *args, **options):
        try:
            client = get_sync_client()
        except SyncNotConfiguredError as error:
            logger.warning("Registry sync refused: %s", error)
            raise CommandError(str(error)) from error

        if options["repository"]:
            repository = find_repository(options["repository"])
            if repository is None:
                raise CommandError(f"Repository {options['repository']} does not exist.")
            repositories = [repository]
        else:
            repositories = Repository.objects.select_related("owner").order_by("pk")

        failed = 0
        for repository in repositories:
            path = repository.registry_path
            try:
                result = sync_repository(repository, client=client)
            except RegistryError as error:
                failed += 1
                self.stderr.write(f"{path}: {error}")
                continue
            self.stdout.write(
                f"{path}: added={result.added} updated={result.updated} removed={result.removed}"
            )

        if failed:
            raise CommandError(f"{failed} repositories could not be synced.")
        self.stdout.write(self.style.SUCCESS("Registry sync finished."))
