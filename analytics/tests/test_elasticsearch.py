from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from analytics.documents import LogEntry
from analytics.elasticsearch import connection_kwargs

COMMAND = "analytics.management.commands.init_elasticsearch"


class ConnectionKwargsTests(SimpleTestCase):
    @override_settings(
        ELASTICSEARCH_URL="http://elasticsearch:9200",
        ELASTICSEARCH_USERNAME="elastic",
        ELASTICSEARCH_PASSWORD="secret",
        ELASTICSEARCH_TIMEOUT=10,
    )
    def test_uses_url_timeout_and_basic_auth_from_settings(self):
        self.assertEqual(
            connection_kwargs(),
            {
                "hosts": ["http://elasticsearch:9200"],
                "request_timeout": 10,
                "basic_auth": ("elastic", "secret"),
            },
        )

    @override_settings(ELASTICSEARCH_PASSWORD="")
    def test_no_basic_auth_without_password(self):
        self.assertNotIn("basic_auth", connection_kwargs())


class LogEntryMappingTests(SimpleTestCase):
    def setUp(self):
        self.mapping = LogEntry._doc_type.mapping.to_dict()
        self.properties = self.mapping["properties"]

    def field_type(self, name):
        return self.properties[name]["type"]

    def test_json_formatter_fields_are_mapped(self):
        expected = {
            "timestamp": "date",
            "level": "keyword",
            "logger": "keyword",
            "message": "text",
            "module": "keyword",
            "function": "keyword",
            "line": "integer",
            "process_id": "integer",
            "thread_name": "keyword",
            "exception": "text",
            "stack": "text",
        }
        for name, field_type in expected.items():
            with self.subTest(field=name):
                self.assertEqual(self.field_type(name), field_type)

    def test_request_log_fields_are_mapped(self):
        expected = {
            "http_method": "keyword",
            "http_path": "keyword",
            "http_status": "integer",
            "duration_ms": "float",
            "username": "keyword",
            "client_ip": "ip",
        }
        for name, field_type in expected.items():
            with self.subTest(field=name):
                self.assertEqual(self.field_type(name), field_type)

    def test_message_has_keyword_subfield_for_exact_match(self):
        self.assertEqual(self.properties["message"]["fields"]["raw"]["type"], "keyword")

    def test_unknown_string_fields_become_keywords(self):
        template = self.mapping["dynamic_templates"][0]["strings_as_keywords"]
        self.assertEqual(template["match_mapping_type"], "string")
        self.assertEqual(template["mapping"]["type"], "keyword")

    def test_index_name_comes_from_settings(self):
        from django.conf import settings

        self.assertEqual(LogEntry._index._name, settings.ELASTICSEARCH_LOG_INDEX)


class InitElasticsearchCommandTests(SimpleTestCase):
    def setUp(self):
        client_patcher = mock.patch(f"{COMMAND}.get_client")
        self.client = client_patcher.start().return_value
        self.addCleanup(client_patcher.stop)

        init_patcher = mock.patch.object(LogEntry, "init")
        self.init = init_patcher.start()
        self.addCleanup(init_patcher.stop)

        self.index = mock.MagicMock(_name="dockerhub-logs-test")
        index_patcher = mock.patch.object(LogEntry, "_index", self.index)
        index_patcher.start()
        self.addCleanup(index_patcher.stop)

    def run_command(self, *args):
        out = StringIO()
        call_command("init_elasticsearch", *args, stdout=out)
        return out.getvalue()

    def test_fails_when_elasticsearch_is_not_reachable(self):
        self.client.ping.return_value = False

        with self.assertRaisesMessage(CommandError, "not reachable"):
            self.run_command()
        self.init.assert_not_called()

    def test_creates_index(self):
        self.client.ping.return_value = True

        output = self.run_command()

        self.init.assert_called_once_with()
        self.index.delete.assert_not_called()
        self.assertIn("dockerhub-logs-test", output)

    def test_recreate_deletes_existing_index_first(self):
        self.client.ping.return_value = True
        self.index.exists.return_value = True

        self.run_command("--recreate")

        self.index.delete.assert_called_once_with()
        self.init.assert_called_once_with()

    def test_recreate_skips_delete_when_index_does_not_exist(self):
        self.client.ping.return_value = True
        self.index.exists.return_value = False

        self.run_command("--recreate")

        self.index.delete.assert_not_called()
        self.init.assert_called_once_with()
