import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from analytics.documents import LogEntry
from analytics.elasticsearch import get_client

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Create the Elasticsearch index for application logs. Safe to run more than once."

    def add_arguments(self, parser):
        parser.add_argument(
            "--recreate",
            action="store_true",
            help="Delete the index first. All logs stored in it are lost.",
        )

    def handle(self, *args, recreate=False, **options):
        if not get_client().ping():
            raise CommandError(
                f"Elasticsearch is not reachable at {settings.ELASTICSEARCH_URL} "
                "(is the container running and is ELASTIC_PASSWORD correct?)."
            )

        index = LogEntry._index
        if recreate and index.exists():
            index.delete()
            logger.warning("Elasticsearch index deleted: index=%s", index._name)

        LogEntry.init()
        logger.info("Elasticsearch index ready: index=%s", index._name)
        self.stdout.write(self.style.SUCCESS(f"Index '{index._name}' is ready."))
