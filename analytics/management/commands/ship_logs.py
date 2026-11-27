import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from analytics import shipping

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Send new entries of the JSON log file to Elasticsearch. "
        "Runs once, or every --interval seconds until stopped."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=float,
            help="Run again every INTERVAL seconds until stopped (Ctrl+C).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            help=f"Log entries per bulk request (default: {settings.LOG_SHIP_BATCH_SIZE}).",
        )

    def handle(self, *args, interval=None, batch_size=None, **options):
        if batch_size is not None and batch_size <= 0:
            raise CommandError("--batch-size must be greater than 0.")

        if interval is None:
            try:
                shipping.ensure_index()
                result = shipping.ship_logs(batch_size=batch_size)
            except shipping.ShippingError as error:
                raise CommandError(str(error)) from error
            self.report(result)
            return

        if interval <= 0:
            raise CommandError("--interval must be greater than 0.")
        self.run_forever(interval, batch_size)

    def run_forever(self, interval, batch_size):
        self.stdout.write(
            f"Shipping {settings.LOG_SHIP_FILE} every {interval:g}s. Press Ctrl+C to stop."
        )
        index_ready = False
        failing = False
        try:
            while True:
                # a long-running process must not keep a dead database connection
                close_old_connections()
                try:
                    if not index_ready:
                        shipping.ensure_index()
                        index_ready = True
                    result = shipping.ship_logs(batch_size=batch_size)
                except shipping.ShippingError as error:
                    # logged once per outage, not on every retry: the warning
                    # goes to the shipped file
                    if not failing:
                        logger.warning("Log shipping failed, retrying every %gs: %s", interval, error)
                    failing = True
                    self.stderr.write(f"{error} (retrying in {interval:g}s)")
                else:
                    if failing:
                        logger.warning("Log shipping works again")
                    failing = False
                    if result.sent or result.failed or result.invalid:
                        self.report(result)
                time.sleep(interval)
        except KeyboardInterrupt:
            self.stdout.write("Stopped.")

    def report(self, result):
        message = f"Shipped {result.sent} log entries"
        if result.failed:
            message += f", {result.failed} rejected by Elasticsearch"
        if result.invalid:
            message += f", {result.invalid} invalid lines skipped"
        style = self.style.WARNING if result.failed or result.invalid else self.style.SUCCESS
        self.stdout.write(style(message + "."))
