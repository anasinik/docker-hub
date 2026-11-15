import json
import logging
import sys

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.logging import JsonFormatter
from core.middleware import RequestLoggingMiddleware

User = get_user_model()

REQUEST_LOGGER = "dockerhub.requests"


def make_record(msg="Hello %s", args=("world",), level=logging.INFO, exc_info=None, **extra):
    record = logging.LogRecord("some.module", level, __file__, 42, msg, args, exc_info, func="some_function")
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class JsonFormatterTests(SimpleTestCase):
    def setUp(self):
        self.formatter = JsonFormatter()

    def format(self, record):
        output = self.formatter.format(record)
        self.assertNotIn("\n", output)
        return json.loads(output)

    def test_contains_standard_fields(self):
        entry = self.format(make_record())

        self.assertEqual(entry["level"], "INFO")
        self.assertEqual(entry["logger"], "some.module")
        self.assertEqual(entry["message"], "Hello world")
        self.assertEqual(entry["function"], "some_function")
        self.assertEqual(entry["line"], 42)
        self.assertIn("process_id", entry)
        self.assertIn("thread_name", entry)

    def test_does_not_use_field_names_reserved_by_ecs(self):
        entry = self.format(make_record())

        self.assertNotIn("process", entry)
        self.assertNotIn("thread", entry)

    def test_timestamp_is_iso_8601_utc(self):
        record = make_record()
        record.created = 0

        self.assertEqual(self.format(record)["timestamp"], "1970-01-01T00:00:00.000+00:00")

    def test_extra_fields_are_included(self):
        entry = self.format(make_record(http_status=404, username="alice"))

        self.assertEqual(entry["http_status"], 404)
        self.assertEqual(entry["username"], "alice")

    def test_values_json_cannot_encode_are_converted_to_text(self):
        entry = self.format(make_record(payload={1, 2}))

        self.assertIsInstance(entry["payload"], str)

    def test_exception_is_included(self):
        try:
            raise ValueError("boom")
        except ValueError:
            record = make_record(level=logging.ERROR, exc_info=sys.exc_info())

        entry = self.format(record)

        self.assertIn("ValueError: boom", entry["exception"])

    def test_newlines_in_message_stay_on_one_line(self):
        entry = self.format(make_record(msg="first\nsecond", args=()))

        self.assertEqual(entry["message"], "first\nsecond")


class RequestLoggingMiddlewareTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password="Secret-pass-2025")

    def setUp(self):
        self.factory = RequestFactory()

    def run_middleware(self, request, status=200):
        middleware = RequestLoggingMiddleware(lambda request: HttpResponse(status=status))
        with self.assertLogs(REQUEST_LOGGER, level="INFO") as logs:
            response = middleware(request)
        self.assertEqual(len(logs.records), 1)
        return response, logs.records[0]

    def anonymous_request(self, path="/repositories/"):
        request = self.factory.get(path)
        request.user = AnonymousUser()
        return request

    def test_logs_request_details(self):
        request = self.factory.post("/repositories/new/")
        request.user = self.alice

        response, record = self.run_middleware(request, status=302)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(record.levelname, "INFO")
        self.assertRegex(record.getMessage(), r"^POST /repositories/new/ 302 \d+\.\dms user=alice ip=127\.0\.0\.1$")
        self.assertEqual(record.http_method, "POST")
        self.assertEqual(record.http_path, "/repositories/new/")
        self.assertEqual(record.http_status, 302)
        self.assertEqual(record.username, "alice")
        self.assertEqual(record.client_ip, "127.0.0.1")
        self.assertGreaterEqual(record.duration_ms, 0)

    def test_anonymous_user_is_logged_as_dash(self):
        _, record = self.run_middleware(self.anonymous_request())

        self.assertIn("user=-", record.getMessage())
        self.assertIsNone(record.username)

    def test_client_error_is_logged_as_warning(self):
        _, record = self.run_middleware(self.anonymous_request(), status=404)

        self.assertEqual(record.levelname, "WARNING")

    def test_server_error_is_logged_as_error(self):
        _, record = self.run_middleware(self.anonymous_request(), status=500)

        self.assertEqual(record.levelname, "ERROR")

    def test_path_cannot_forge_log_lines(self):
        _, record = self.run_middleware(self.anonymous_request("/x%0AUser logged in: username=root"))

        self.assertNotIn("\n", record.getMessage())
        self.assertIn("/x\\nUser logged in", record.getMessage())

    @override_settings(LOG_REQUESTS_SKIP_PREFIXES=["/static/", "/health/"])
    def test_skipped_paths_are_not_logged(self):
        middleware = RequestLoggingMiddleware(lambda request: HttpResponse())

        with self.assertNoLogs(REQUEST_LOGGER, level="DEBUG"):
            middleware(self.anonymous_request("/static/css/main.css"))
            middleware(self.anonymous_request("/health/"))

    def test_is_active_for_real_requests(self):
        with self.assertLogs(REQUEST_LOGGER, level="INFO") as logs:
            self.client.get(reverse("core:home"))

        self.assertIn("GET / 200", logs.output[0])

    def test_request_without_user_is_logged_as_anonymous(self):
        _, record = self.run_middleware(self.factory.get("/"), status=400)

        self.assertIn("user=-", record.getMessage())
        self.assertIsNone(record.username)

    def test_disallowed_host_returns_400_not_500(self):
        # CommonMiddleware rejects the Host before AuthenticationMiddleware sets request.user.
        with self.assertLogs(REQUEST_LOGGER, level="INFO") as logs:
            response = self.client.get(reverse("core:home"), HTTP_HOST="evil.example.com")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(logs.records[0].levelname, "WARNING")
        self.assertIn("GET / 400", logs.output[0])

    def test_health_check_is_not_logged(self):
        with self.assertNoLogs(REQUEST_LOGGER, level="DEBUG"):
            self.client.get(reverse("core:health"))


class LoggingSettingsTests(SimpleTestCase):
    def test_application_loggers_reach_the_root_handlers(self):
        for name in ("accounts.views", "repositories.views", "core.views", "django"):
            self.assertTrue(logging.getLogger(name).propagate, name)

    def test_nothing_is_written_to_files_while_testing(self):
        self.assertTrue(settings.TESTING)
        self.assertFalse(settings.LOG_TO_FILE)
        self.assertEqual(settings.LOGGING["root"]["handlers"], ["null"])

    def test_json_handler_uses_json_formatter(self):
        handler = settings.LOGGING["handlers"]["json_file"]

        self.assertEqual(handler["formatter"], "json")
        self.assertEqual(handler["filename"].name, "app.json.log")

    def test_file_handlers_are_safe_for_several_processes(self):
        for name in ("file", "json_file"):
            self.assertEqual(settings.LOGGING["handlers"][name]["class"], "logging.handlers.WatchedFileHandler", name)

    def test_runserver_access_log_is_silenced(self):
        self.assertFalse(logging.getLogger("django.server").propagate)
