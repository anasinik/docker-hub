import json
import os
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings
from elasticsearch import ConnectionError as ESConnectionError

from analytics import shipping
from analytics.models import LogShippingState
from analytics.shipping import ShipResult, ShippingError


def log_line(message, level="INFO", **extra):
    entry = {"timestamp": "2026-11-25T10:00:00.000+00:00", "level": level, "logger": "test", "message": message}
    entry.update(extra)
    return (json.dumps(entry) + "\n").encode()


class TempLogFileMixin:
    def setUp(self):
        super().setUp()
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.path = Path(temp_dir.name) / "app.json.log"

    def append(self, *lines):
        with open(self.path, "ab") as file:
            file.write(b"".join(lines))


class ReadBatchesTests(TempLogFileMixin, SimpleTestCase):
    def test_yields_lines_with_offsets_in_batches(self):
        lines = [log_line(f"m{i}") for i in range(5)]
        self.append(*lines)

        batches = list(shipping.read_batches(self.path, 0, batch_size=2))

        self.assertEqual([len(batch) for batch, _ in batches], [2, 2, 1])
        first_batch, first_end = batches[0]
        self.assertEqual(first_batch[0], (0, lines[0]))
        self.assertEqual(first_batch[1], (len(lines[0]), lines[1]))
        self.assertEqual(first_end, len(lines[0]) + len(lines[1]))
        self.assertEqual(batches[-1][1], self.path.stat().st_size)

    def test_starts_at_offset(self):
        first, second = log_line("old"), log_line("new")
        self.append(first, second)

        batches = list(shipping.read_batches(self.path, len(first), batch_size=10))

        self.assertEqual(batches, [([(len(first), second)], len(first) + len(second))])

    def test_stops_before_line_that_is_still_being_written(self):
        complete = log_line("done")
        self.append(complete, b'{"timestamp": "2026-11-25T')

        batches = list(shipping.read_batches(self.path, 0, batch_size=10))

        self.assertEqual(batches, [([(0, complete)], len(complete))])

    def test_nothing_new(self):
        self.append(log_line("m"))

        self.assertEqual(list(shipping.read_batches(self.path, self.path.stat().st_size, 10)), [])


class ParseLineTests(SimpleTestCase):
    def test_returns_log_entry(self):
        entry = shipping.parse_line(log_line("hello", level="ERROR", repo_id=7))

        self.assertEqual(entry["message"], "hello")
        self.assertEqual(entry["level"], "ERROR")
        self.assertEqual(entry["repo_id"], 7)

    def test_rejects_lines_that_are_not_log_entries(self):
        cases = {
            "not json": b"Traceback (most recent call last):\n",
            "json list": b"[1, 2]\n",
            "missing level": b'{"timestamp": "2026-11-25T10:00:00Z", "message": "x"}\n',
        }
        for name, raw in cases.items():
            with self.subTest(name):
                self.assertIsNone(shipping.parse_line(raw))

    def test_invalid_utf8_does_not_raise(self):
        raw = log_line("x").replace(b'"x"', b'"\xff"')

        self.assertEqual(shipping.parse_line(raw)["message"], "�")


class DocumentIdTests(SimpleTestCase):
    def test_same_line_gets_same_id(self):
        line = log_line("m")

        self.assertEqual(shipping.document_id("1", 0, line), shipping.document_id("1", 0, line))

    def test_file_offset_or_content_change_the_id(self):
        base = shipping.document_id("1", 0, log_line("m"))

        self.assertNotEqual(base, shipping.document_id("2", 0, log_line("m")))
        self.assertNotEqual(base, shipping.document_id("1", 10, log_line("m")))
        self.assertNotEqual(base, shipping.document_id("1", 0, log_line("other")))


class ShipLogsTests(TempLogFileMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.batches = []  # actions of every bulk call

        def fake_bulk(client, actions, **kwargs):
            actions = list(actions)
            self.batches.append(actions)
            return len(actions), []

        bulk_patcher = mock.patch("analytics.shipping.bulk", side_effect=fake_bulk)
        self.bulk = bulk_patcher.start()
        self.addCleanup(bulk_patcher.stop)

        client_patcher = mock.patch("analytics.shipping.get_client")
        client_patcher.start()
        self.addCleanup(client_patcher.stop)

    def ship(self, batch_size=100):
        return shipping.ship_logs(path=self.path, batch_size=batch_size)

    def state(self):
        return LogShippingState.objects.get(path=str(self.path))

    def shipped_messages(self):
        return [action["_source"]["message"] for batch in self.batches for action in batch]

    def test_missing_file_ships_nothing(self):
        result = self.ship()

        self.assertEqual(result, ShipResult())
        self.bulk.assert_not_called()

    def test_ships_all_lines_and_saves_offset(self):
        self.append(log_line("first"), log_line("second", level="WARNING"))

        result = self.ship()

        self.assertEqual(result, ShipResult(sent=2))
        self.assertEqual(self.shipped_messages(), ["first", "second"])
        action = self.batches[0][1]
        self.assertEqual(action["_index"], shipping.LogEntry._index._name)
        self.assertEqual(action["_source"]["level"], "WARNING")
        self.assertEqual(self.state().offset, self.path.stat().st_size)
        self.assertEqual(self.state().file_id, shipping.file_identity(self.path.stat()))

    def test_next_run_ships_only_new_lines(self):
        self.append(log_line("old"))
        self.ship()
        self.append(log_line("new"))

        result = self.ship()

        self.assertEqual(result.sent, 1)
        self.assertEqual(self.shipped_messages(), ["old", "new"])

    def test_nothing_new_sends_no_request(self):
        self.append(log_line("old"))
        self.ship()
        self.bulk.reset_mock()

        self.assertEqual(self.ship(), ShipResult())
        self.bulk.assert_not_called()

    def test_partial_line_is_shipped_once_it_is_complete(self):
        line = log_line("slow")
        self.append(line[:10])
        self.ship()
        self.assertEqual(self.shipped_messages(), [])
        self.assertEqual(self.state().offset, 0)

        self.append(line[10:])
        self.ship()

        self.assertEqual(self.shipped_messages(), ["slow"])

    def test_sends_one_bulk_request_per_batch(self):
        self.append(*[log_line(f"m{i}") for i in range(5)])

        result = self.ship(batch_size=2)

        self.assertEqual(result.sent, 5)
        self.assertEqual([len(batch) for batch in self.batches], [2, 2, 1])
        # one request per batch, even when the batch is larger than bulk()'s default of 500
        self.assertEqual([call.kwargs["chunk_size"] for call in self.bulk.call_args_list], [2, 2, 1])

    def test_invalid_lines_are_skipped_and_counted(self):
        self.append(log_line("ok"), b"plain text\n", b"\n", log_line("also ok"))

        with self.assertLogs("analytics.shipping", level="WARNING") as logs:
            result = self.ship()

        self.assertEqual(result, ShipResult(sent=2, invalid=1))
        self.assertEqual(self.shipped_messages(), ["ok", "also ok"])
        self.assertEqual(self.state().offset, self.path.stat().st_size)
        self.assertIn("Skipped 1 lines", logs.output[0])

    def test_elasticsearch_down_keeps_offset(self):
        self.append(log_line("m"))
        self.bulk.side_effect = ESConnectionError("connection refused")

        with self.assertRaises(ShippingError):
            self.ship()

        self.assertEqual(self.state().offset, 0)

    def test_failure_in_later_batch_keeps_progress_of_earlier_batches(self):
        first, second = log_line("a"), log_line("b")
        self.append(first, second)
        self.bulk.side_effect = [(1, []), ESConnectionError("connection refused")]

        with self.assertRaises(ShippingError):
            self.ship(batch_size=1)

        self.assertEqual(self.state().offset, len(first))

    def test_overloaded_elasticsearch_keeps_offset(self):
        self.append(log_line("m"))
        self.bulk.side_effect = None
        self.bulk.return_value = (0, [{"index": {"status": 429, "error": {"type": "es_rejected_execution_exception"}}}])

        with self.assertRaisesMessage(ShippingError, "could not store 1"):
            self.ship()

        self.assertEqual(self.state().offset, 0)

    def test_rejected_entry_is_counted_and_skipped(self):
        self.append(log_line("bad"), log_line("good"))
        self.bulk.side_effect = None
        self.bulk.return_value = (1, [{"index": {"status": 400, "error": {"type": "mapper_parsing_exception"}}}])

        with self.assertLogs("analytics.shipping", level="WARNING") as logs:
            result = self.ship()

        self.assertEqual(result, ShipResult(sent=1, failed=1))
        self.assertEqual(self.state().offset, self.path.stat().st_size)
        self.assertIn("mapper_parsing_exception", logs.output[0])

    def test_sending_the_same_line_again_reuses_the_document_id(self):
        self.append(log_line("m"))
        self.ship()
        first_id = self.batches[0][0]["_id"]
        LogShippingState.objects.update(offset=0)  # e.g. crash before the offset was saved

        self.ship()

        self.assertEqual(self.batches[1][0]["_id"], first_id)

    def test_truncated_file_is_read_from_the_start(self):
        self.append(log_line("old one"), log_line("old two"))
        self.ship()
        self.path.write_bytes(log_line("new"))

        with self.assertLogs("analytics.shipping", level="WARNING"):
            result = self.ship()

        self.assertEqual(result.sent, 1)
        self.assertEqual(self.shipped_messages()[-1], "new")
        self.assertEqual(self.state().offset, self.path.stat().st_size)

    def test_rotated_file_is_finished_then_new_file_is_read_from_the_start(self):
        self.append(log_line("before rotation"))
        self.ship()
        self.append(log_line("written just before rotation"))
        os.rename(self.path, f"{self.path}.1")
        self.append(log_line("after rotation"))

        result = self.ship()

        self.assertEqual(result.sent, 2)
        self.assertEqual(
            self.shipped_messages(),
            ["before rotation", "written just before rotation", "after rotation"],
        )
        state = self.state()
        self.assertEqual(state.file_id, shipping.file_identity(self.path.stat()))
        self.assertEqual(state.offset, self.path.stat().st_size)

    def test_rotated_file_that_was_removed_is_skipped(self):
        self.append(log_line("before rotation"))
        self.ship()
        os.remove(self.path)
        self.append(log_line("after rotation"))
        LogShippingState.objects.update(file_id="old-inode")

        result = self.ship()

        self.assertEqual(result.sent, 1)
        self.assertEqual(self.shipped_messages()[-1], "after rotation")


@override_settings(LOG_SHIP_FILE=Path("logs/app.json.log"))
class ShipLogsCommandTests(SimpleTestCase):
    def setUp(self):
        for name in ("ensure_index", "ship_logs"):
            patcher = mock.patch(f"analytics.shipping.{name}")
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.ship_logs.return_value = ShipResult(sent=3)

    def run_command(self, *args):
        out, err = StringIO(), StringIO()
        call_command("ship_logs", *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_runs_once_by_default(self):
        out, _ = self.run_command()

        self.ensure_index.assert_called_once_with()
        self.ship_logs.assert_called_once_with(batch_size=None)
        self.assertIn("Shipped 3 log entries.", out)

    def test_reports_rejected_and_invalid_lines(self):
        self.ship_logs.return_value = ShipResult(sent=1, failed=2, invalid=4)

        out, _ = self.run_command()

        self.assertIn("Shipped 1 log entries, 2 rejected by Elasticsearch, 4 invalid lines skipped.", out)

    def test_passes_batch_size(self):
        self.run_command("--batch-size", "50")

        self.ship_logs.assert_called_once_with(batch_size=50)

    def test_fails_when_elasticsearch_is_not_available(self):
        self.ensure_index.side_effect = ShippingError("Elasticsearch is not available")

        with self.assertRaisesMessage(CommandError, "not available"):
            self.run_command()
        self.ship_logs.assert_not_called()

    def test_rejects_invalid_arguments(self):
        for args in (["--interval", "0"], ["--batch-size", "0"]):
            with self.subTest(args=args), self.assertRaises(CommandError):
                self.run_command(*args)

    @mock.patch("analytics.management.commands.ship_logs.time.sleep")
    def test_interval_keeps_running_after_errors_until_stopped(self, sleep):
        self.ensure_index.side_effect = [ShippingError("Elasticsearch is not available"), None]
        self.ship_logs.side_effect = [ShipResult(sent=2), ShipResult()]
        sleep.side_effect = [None, None, KeyboardInterrupt]

        with self.assertLogs("analytics.management.commands.ship_logs", level="WARNING"):
            out, err = self.run_command("--interval", "5")

        self.assertEqual(self.ensure_index.call_count, 2)  # retried, then not called again
        self.assertEqual(self.ship_logs.call_count, 2)
        sleep.assert_called_with(5.0)
        self.assertIn("retrying in 5s", err)
        self.assertEqual(out.count("Shipped"), 1)  # quiet when nothing new was shipped
        self.assertIn("Stopped.", out)

    @mock.patch("analytics.management.commands.ship_logs.time.sleep")
    def test_interval_logs_an_outage_once(self, sleep):
        down = ShippingError("Elasticsearch is not available")
        self.ship_logs.side_effect = [down, down, down, ShipResult()]
        sleep.side_effect = [None, None, None, KeyboardInterrupt]

        with self.assertLogs("analytics.management.commands.ship_logs", level="WARNING") as logs:
            _, err = self.run_command("--interval", "5")

        self.assertEqual(len(logs.records), 2)
        self.assertIn("Log shipping failed", logs.records[0].getMessage())
        self.assertIn("works again", logs.records[1].getMessage())
        self.assertEqual(err.count("retrying in 5s"), 3)  # the console still shows every retry
