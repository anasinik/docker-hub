from io import StringIO
from unittest.mock import Mock, patch

import requests
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from repositories.models import Repository, Visibility
from repositories.services.registry.base import RegistryError
from repositories.services.registry.factory import get_registry_client
from repositories.services.registry.http import HttpRegistryClient
from repositories.services.registry.mock import MockRegistryClient

HTTP_CLIENT_CLASS = "repositories.services.registry.http.HttpRegistryClient"
REQUESTS_GET = "repositories.services.registry.http.requests.get"
LOGGER = "repositories.services.registry.http"


def registry_response(status_code=200, api_header=True):
    response = Mock(status_code=status_code)
    response.headers = {"Docker-Distribution-API-Version": "registry/2.0"} if api_header else {}
    return response


@override_settings(REGISTRY_URL="http://registry.test:5000", REGISTRY_TIMEOUT=3)
class HttpRegistryClientTests(SimpleTestCase):
    def test_uses_url_and_timeout_from_settings(self):
        client = HttpRegistryClient()

        self.assertEqual(client.base_url, "http://registry.test:5000")
        self.assertEqual(client.timeout, 3)

    def test_trailing_slash_is_removed_from_url(self):
        client = HttpRegistryClient(base_url="http://registry.test:5000/")

        self.assertEqual(client.base_url, "http://registry.test:5000")

    @patch(REQUESTS_GET, return_value=registry_response(200))
    def test_is_available_calls_version_endpoint(self, mock_get):
        HttpRegistryClient().is_available()

        mock_get.assert_called_once_with("http://registry.test:5000/v2/", timeout=3)

    @patch(REQUESTS_GET, return_value=registry_response(200))
    def test_is_available_when_registry_answers_200(self, mock_get):
        self.assertTrue(HttpRegistryClient().is_available())

    @patch(REQUESTS_GET, return_value=registry_response(401))
    def test_is_available_when_registry_requires_authentication(self, mock_get):
        self.assertTrue(HttpRegistryClient().is_available())

    @patch(REQUESTS_GET, return_value=registry_response(500))
    def test_not_available_on_server_error(self, mock_get):
        with self.assertLogs(LOGGER, level="WARNING") as logs:
            self.assertFalse(HttpRegistryClient().is_available())

        self.assertIn("status=500", logs.output[0])

    @patch(REQUESTS_GET, return_value=registry_response(200, api_header=False))
    def test_not_available_when_server_is_not_a_registry(self, mock_get):
        with self.assertLogs(LOGGER, level="WARNING") as logs:
            self.assertFalse(HttpRegistryClient().is_available())

        self.assertIn("not a Docker registry", logs.output[0])

    @patch(REQUESTS_GET, side_effect=requests.ConnectionError("Connection refused"))
    def test_not_available_when_connection_is_refused(self, mock_get):
        with self.assertLogs(LOGGER, level="WARNING") as logs:
            self.assertFalse(HttpRegistryClient().is_available())

        self.assertIn("Connection refused", logs.output[0])

    @patch(REQUESTS_GET, side_effect=requests.Timeout("Read timed out"))
    def test_not_available_on_timeout(self, mock_get):
        with self.assertLogs(LOGGER, level="WARNING"):
            self.assertFalse(HttpRegistryClient().is_available())

    def test_list_tags_raises_registry_error(self):
        with self.assertRaises(RegistryError):
            HttpRegistryClient().list_tags(Repository(name="app"))


class MockRegistryClientTests(SimpleTestCase):
    def test_mock_is_always_available(self):
        self.assertTrue(MockRegistryClient().is_available())


class RegistryClientFactoryTests(SimpleTestCase):
    def test_default_client_is_mock(self):
        self.assertIsInstance(get_registry_client(), MockRegistryClient)

    @override_settings(REGISTRY_CLIENT_CLASS=HTTP_CLIENT_CLASS)
    def test_http_client_is_selected_from_settings(self):
        self.assertIsInstance(get_registry_client(), HttpRegistryClient)


@override_settings(REGISTRY_URL="http://registry.test:5000")
class CheckRegistryCommandTests(TestCase):
    @patch(REQUESTS_GET, return_value=registry_response(200))
    def test_reports_available_registry(self, mock_get):
        out = StringIO()

        call_command("check_registry", stdout=out)

        self.assertIn("Registry at http://registry.test:5000 is available.", out.getvalue())
        mock_get.assert_called_once()

    @patch(REQUESTS_GET, side_effect=requests.ConnectionError("Connection refused"))
    def test_fails_when_registry_is_down(self, mock_get):
        with self.assertLogs(LOGGER, level="WARNING"):
            with self.assertRaisesMessage(CommandError, "not reachable at http://registry.test:5000"):
                call_command("check_registry")


@override_settings(REGISTRY_CLIENT_CLASS=HTTP_CLIENT_CLASS)
class RepositoryDetailWithHttpClientTests(TestCase):
    """The detail page must still render while the real client cannot list tags (#26)."""

    def test_detail_page_shows_registry_unavailable(self):
        owner = User.objects.create_user(username="owner1", email="owner1@example.com", password="Tr1cky-pass-2026")
        repository = Repository.objects.create(owner=owner, name="app", visibility=Visibility.PUBLIC)

        with self.assertLogs("repositories.views", level="WARNING"):
            response = self.client.get(reverse("repositories:detail", kwargs={"pk": repository.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["registry_unavailable"])
