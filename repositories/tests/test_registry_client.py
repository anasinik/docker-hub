from io import StringIO
from unittest.mock import Mock, patch

import requests
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from repositories.models import Repository, Visibility
from repositories.services.registry.base import (
    DOCKER_MANIFEST,
    DOCKER_MANIFEST_LIST,
    OCI_INDEX,
    OCI_MANIFEST,
    ManifestInfo,
    RegistryError,
)
from repositories.services.registry.factory import get_registry_client
from repositories.services.registry.http import HttpRegistryClient
from repositories.services.registry.mock import MockRegistryClient
from repositories.tests.registry_keys import decode, token_settings

HTTP_CLIENT_CLASS = "repositories.services.registry.http.HttpRegistryClient"
REQUESTS_GET = "repositories.services.registry.http.requests.get"
REQUESTS_REQUEST = "repositories.services.registry.http.requests.request"
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


class MockRegistryClientTests(SimpleTestCase):
    def test_mock_is_always_available(self):
        self.assertTrue(MockRegistryClient().is_available())

    def test_mock_has_no_images(self):
        client = MockRegistryClient()

        self.assertEqual(client.list_tags("alice/web"), [])
        self.assertIsNone(client.get_digest("alice/web", "latest"))
        self.assertEqual(client.delete_repository("alice/web"), 0)


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


@override_settings(REGISTRY_CLIENT_CLASS=HTTP_CLIENT_CLASS, REGISTRY_URL="http://registry.test:5000")
class RepositoryDetailWithHttpClientTests(TestCase):
    """The detail page reads tags from the database, so it works while the registry is down."""

    @patch(REQUESTS_REQUEST, side_effect=requests.ConnectionError("Connection refused"))
    def test_detail_page_does_not_call_registry(self, mock_request):
        owner = User.objects.create_user(username="owner1", email="owner1@example.com", password="Tr1cky-pass-2026")
        repository = Repository.objects.create(owner=owner, name="app", visibility=Visibility.PUBLIC)

        response = self.client.get(reverse("repositories:detail", kwargs={"pk": repository.pk}))

        self.assertEqual(response.status_code, 200)
        mock_request.assert_not_called()


def api_response(status_code=200, json_body=None, headers=None, next_url=None):
    response = Mock(status_code=status_code, headers=headers or {}, url="http://registry.test:5000/v2/")
    response.request.method = "GET"
    response.json.return_value = json_body if json_body is not None else {}
    response.links = {"next": {"url": next_url}} if next_url else {}
    return response


def token_access(call):
    """The ``access`` claim of the token sent in a mocked ``requests.request`` call."""
    token = call.kwargs["headers"]["Authorization"].removeprefix("Bearer ")
    return decode(token)["access"]


IMAGE_MANIFEST = {
    "mediaType": DOCKER_MANIFEST,
    "config": {"size": 1000},
    "layers": [{"size": 20000}, {"size": 300}],
}


@token_settings(REGISTRY_URL="http://registry.test:5000")
class HttpRegistryClientApiTests(SimpleTestCase):
    """Registry API v2 calls, with ``requests.request`` mocked."""

    def setUp(self):
        patcher = patch(REQUESTS_REQUEST)
        self.request = patcher.start()
        self.addCleanup(patcher.stop)
        self.client = HttpRegistryClient()

    def test_list_tags_sends_pull_token_for_repository(self):
        self.request.return_value = api_response(json_body={"name": "alice/web", "tags": ["1.0", "latest"]})

        self.assertEqual(self.client.list_tags("alice/web"), ["1.0", "latest"])

        call = self.request.call_args
        self.assertEqual(call.args, ("GET", "http://registry.test:5000/v2/alice/web/tags/list?n=100"))
        self.assertEqual(token_access(call), [{"type": "repository", "name": "alice/web", "actions": ["pull"]}])
        self.assertEqual(call.kwargs["timeout"], self.client.timeout)

    def test_list_tags_follows_pagination(self):
        self.request.side_effect = [
            api_response(json_body={"tags": ["a"]}, next_url="/v2/alice/web/tags/list?last=a&n=100"),
            api_response(json_body={"tags": ["b"]}),
        ]

        self.assertEqual(self.client.list_tags("alice/web"), ["a", "b"])
        self.assertEqual(
            self.request.call_args_list[1].args[1], "http://registry.test:5000/v2/alice/web/tags/list?last=a&n=100"
        )

    def test_list_tags_of_unknown_or_emptied_repository_is_empty(self):
        for response in (api_response(404), api_response(json_body={"name": "alice/web", "tags": None})):
            with self.subTest(status=response.status_code):
                self.request.return_value = response

                self.assertEqual(self.client.list_tags("alice/web"), [])

    def test_errors_raise_registry_error(self):
        for side_effect in (requests.ConnectionError("refused"), api_response(401), api_response(500)):
            with self.subTest(side_effect=side_effect):
                self.request.side_effect = [side_effect]

                with self.assertRaises(RegistryError):
                    self.client.list_tags("alice/web")

    def test_manifest_requests_accept_all_manifest_types(self):
        self.request.return_value = api_response(headers={"Docker-Content-Digest": "sha256:abc"})

        self.assertEqual(self.client.get_digest("alice/web", "latest"), "sha256:abc")

        call = self.request.call_args
        self.assertEqual(call.args, ("HEAD", "http://registry.test:5000/v2/alice/web/manifests/latest"))
        accept = [media_type.strip() for media_type in call.kwargs["headers"]["Accept"].split(",")]
        self.assertCountEqual(accept, [DOCKER_MANIFEST, DOCKER_MANIFEST_LIST, OCI_MANIFEST, OCI_INDEX])

    def test_get_digest_of_missing_tag_is_none(self):
        self.request.return_value = api_response(404)

        self.assertIsNone(self.client.get_digest("alice/web", "gone"))

    def test_get_manifest_sums_config_and_layers(self):
        self.request.return_value = api_response(
            json_body=IMAGE_MANIFEST, headers={"Docker-Content-Digest": "sha256:img"}
        )

        self.assertEqual(
            self.client.get_manifest("alice/web", "sha256:img"),
            ManifestInfo(digest="sha256:img", media_type=DOCKER_MANIFEST, size=21300),
        )

    def test_get_manifest_of_index_sums_platforms_without_attestations(self):
        index = {
            "mediaType": OCI_INDEX,
            "manifests": [
                {"digest": "sha256:amd64", "mediaType": OCI_MANIFEST, "platform": {"os": "linux", "architecture": "amd64"}},
                {"digest": "sha256:arm64", "mediaType": OCI_MANIFEST, "platform": {"os": "linux", "architecture": "arm64"}},
                {
                    "digest": "sha256:att",
                    "mediaType": OCI_MANIFEST,
                    "platform": {"os": "unknown", "architecture": "unknown"},
                    "annotations": {"vnd.docker.reference.type": "attestation-manifest"},
                },
            ],
        }
        self.request.side_effect = [
            api_response(json_body=index, headers={"Docker-Content-Digest": "sha256:index"}),
            api_response(json_body=IMAGE_MANIFEST),
            api_response(json_body={"config": {"size": 10}, "layers": [{"size": 90}]}),
        ]

        info = self.client.get_manifest("alice/web", "sha256:index")

        self.assertEqual(info, ManifestInfo(digest="sha256:index", media_type=OCI_INDEX, size=21400))
        fetched = [call.args[1].rsplit("/", 1)[1] for call in self.request.call_args_list]
        self.assertEqual(fetched, ["sha256:index", "sha256:amd64", "sha256:arm64"])

    def test_delete_manifest_sends_delete_token(self):
        self.request.return_value = api_response(202)

        self.assertTrue(self.client.delete_manifest("alice/web", "sha256:abc"))

        call = self.request.call_args
        self.assertEqual(call.args, ("DELETE", "http://registry.test:5000/v2/alice/web/manifests/sha256:abc"))
        self.assertEqual(token_access(call), [{"type": "repository", "name": "alice/web", "actions": ["delete"]}])

    def test_delete_manifest_that_is_already_gone(self):
        self.request.return_value = api_response(404)

        self.assertFalse(self.client.delete_manifest("alice/web", "sha256:abc"))

    def test_delete_repository_deletes_each_digest_once(self):
        self.request.side_effect = [
            api_response(json_body={"tags": ["1.0", "latest", "old"]}),
            api_response(headers={"Docker-Content-Digest": "sha256:same"}),
            api_response(headers={"Docker-Content-Digest": "sha256:same"}),
            api_response(headers={"Docker-Content-Digest": "sha256:old"}),
            api_response(202),
            # Removed in the meantime: counts as already deleted, not as an error
            api_response(404),
        ]

        self.assertEqual(self.client.delete_repository("alice/web"), 1)

        deletes = [call.args[1] for call in self.request.call_args_list if call.args[0] == "DELETE"]
        self.assertEqual(
            deletes,
            [
                "http://registry.test:5000/v2/alice/web/manifests/sha256:same",
                "http://registry.test:5000/v2/alice/web/manifests/sha256:old",
            ],
        )

    def test_delete_repository_without_images(self):
        self.request.return_value = api_response(404)

        self.assertEqual(self.client.delete_repository("alice/web"), 0)
        self.request.assert_called_once()
