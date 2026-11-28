import datetime
import json
from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import CommandError, call_command
from django.db import IntegrityError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from repositories.models import Repository, Tag
from repositories.services.registry.base import (
    DOCKER_MANIFEST,
    OCI_INDEX,
    OCI_MANIFEST,
    ManifestInfo,
    RegistryError,
)
from repositories.services.registry.events import repositories_to_sync
from repositories.services.registry import sync as sync_module
from repositories.services.registry.mock import MockRegistryClient
from repositories.services.registry.factory import get_registry_client
from repositories.services.registry.sync import SyncNotConfiguredError, sync_repository
from repositories.tests.registry_keys import KEY_DIR, token_settings

PASSWORD = "Tr1cky-pass-2025"
EVENTS_TOKEN = "events-secret"
SYNC_CLIENT = "repositories.services.registry.sync.get_registry_client"
VIEWS_CLIENT = "repositories.views.get_registry_client"
PUSHED_AT = datetime.datetime(2026, 11, 25, 14, 58, 50, 655493, tzinfo=datetime.timezone.utc)


class FakeRegistry:
    """In-memory registry: ``{path: {tag: ManifestInfo}}``; counts manifest downloads."""

    def __init__(self, images=None, error=None):
        self.images = images or {}
        self.error = error
        self.manifest_downloads = []

    def _check(self):
        if self.error:
            raise self.error

    def list_tags(self, path):
        self._check()
        return list(self.images.get(path, {}))

    def get_digest(self, path, tag):
        self._check()
        manifest = self.images.get(path, {}).get(tag)
        return manifest.digest if manifest else None

    def get_manifest(self, path, reference):
        self._check()
        self.manifest_downloads.append((path, reference))
        for manifest in self.images.get(path, {}).values():
            if manifest.digest == reference:
                return manifest
        raise RegistryError(f"unknown manifest {reference}")


def image(digest, size=100, media_type=OCI_MANIFEST):
    return ManifestInfo(digest=digest, media_type=media_type, size=size)


def event(action="push", repository="alice/web", tag="1.0", media_type=OCI_INDEX, digest="sha256:abc",
          timestamp="2026-11-25T14:58:50.655493298Z"):
    target = {"repository": repository, "mediaType": media_type, "digest": digest}
    if tag:
        target["tag"] = tag
    return {"action": action, "target": target, "timestamp": timestamp}


class RepositoriesToSyncTests(SimpleTestCase):
    """Which notification events start a sync."""

    def test_tagged_push_starts_sync_with_event_time(self):
        self.assertEqual(repositories_to_sync({"events": [event()]}), {"alice/web": {"1.0": PUSHED_AT}})

    def test_multi_arch_push_starts_one_sync(self):
        # One untagged event per platform and attestation manifest, then the tagged index
        events = [event(tag=None, media_type=OCI_MANIFEST, digest=f"sha256:{n}") for n in range(17)]
        events.append(event(tag="1.0", media_type=OCI_INDEX))

        self.assertEqual(list(repositories_to_sync({"events": events})), ["alice/web"])

    def test_push_time_is_kept_per_tag(self):
        def at(hour):
            return datetime.datetime(2026, 11, 25, hour, tzinfo=datetime.timezone.utc)

        events = [
            event(tag="1.0", timestamp="2026-11-25T10:00:00Z"),
            event(tag="latest", timestamp="2026-11-25T11:00:00Z"),
            event(tag="1.0", timestamp="2026-11-25T12:00:00Z"),
            event(repository="bob1/api", timestamp="2026-11-25T09:00:00Z"),
        ]

        paths = repositories_to_sync({"events": events})

        self.assertEqual(paths["alice/web"], {"1.0": at(12), "latest": at(11)})
        self.assertEqual(paths["bob1/api"], {"1.0": at(9)})

    def test_manifest_delete_starts_sync_but_tag_deletes_do_not(self):
        manifest_delete = event(action="delete", tag=None, media_type=None, digest="sha256:abc")
        tag_delete = event(action="delete", tag="1.0", media_type=None, digest=None)

        self.assertEqual(repositories_to_sync({"events": [manifest_delete]}), {"alice/web": {}})
        self.assertEqual(repositories_to_sync({"events": [tag_delete]}), {})

    def test_blob_and_pull_events_are_skipped(self):
        events = [
            event(media_type="application/octet-stream"),
            event(action="pull"),
            event(action="mount"),
            {"action": "push"},
            "not an event",
        ]

        self.assertEqual(repositories_to_sync({"events": events}), {})

    def test_missing_timestamp_uses_current_time(self):
        before = timezone.now()

        paths = repositories_to_sync({"events": [event(timestamp=None)]})

        self.assertGreaterEqual(paths["alice/web"]["1.0"], before)

    def test_payload_without_events_list_is_rejected(self):
        for payload in ([], {}, {"events": "x"}, None):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                repositories_to_sync(payload)


class SyncRepositoryTests(TestCase):
    """Unit tests for ``sync_repository`` with an in-memory registry."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)

    def setUp(self):
        self.repository = Repository.objects.create(owner=self.alice, name="web")

    def sync(self, registry, time=PUSHED_AT):
        # Every tag in the registry was pushed at ``time``
        pushed_at = {name: time for name in registry.images.get("alice/web", {})}
        return sync_repository(self.repository, pushed_at=pushed_at, client=registry)

    def tags(self):
        return {tag.name: (tag.digest, tag.size, tag.pushed_at) for tag in self.repository.tags.all()}

    def test_new_tags_are_added(self):
        registry = FakeRegistry({"alice/web": {"1.0": image("sha256:a", 10), "latest": image("sha256:a", 10)}})

        with self.assertLogs("repositories.services.registry.sync", "INFO") as logs:
            result = self.sync(registry)

        self.assertEqual((result.added, result.updated, result.removed), (2, 0, 0))
        self.assertEqual(self.tags(), {"1.0": ("sha256:a", 10, PUSHED_AT), "latest": ("sha256:a", 10, PUSHED_AT)})
        self.assertIn("Tags synced: path=alice/web added=2 updated=0 removed=0", logs.output[0])
        self.assertEqual(logs.records[0].repo_id, self.repository.pk)

    def test_changed_digest_is_updated(self):
        Tag.objects.create(repository=self.repository, name="latest", digest="sha256:old", size=1, pushed_at=PUSHED_AT)
        later = PUSHED_AT + datetime.timedelta(hours=1)

        result = self.sync(FakeRegistry({"alice/web": {"latest": image("sha256:new", 50, DOCKER_MANIFEST)}}), later)

        self.assertEqual((result.added, result.updated, result.removed), (0, 1, 0))
        tag = self.repository.tags.get()
        self.assertEqual((tag.digest, tag.size, tag.media_type, tag.pushed_at), ("sha256:new", 50, DOCKER_MANIFEST, later))

    def test_unchanged_tag_keeps_push_time_and_is_not_downloaded(self):
        Tag.objects.create(repository=self.repository, name="1.0", digest="sha256:a", size=10, pushed_at=PUSHED_AT)
        registry = FakeRegistry({"alice/web": {"1.0": image("sha256:a", 10), "2.0": image("sha256:b", 20)}})

        with self.assertLogs("repositories.services.registry.sync", "INFO"):
            result = self.sync(registry, PUSHED_AT + datetime.timedelta(days=1))

        self.assertEqual((result.added, result.updated), (1, 0))
        self.assertEqual(self.repository.tags.get(name="1.0").pushed_at, PUSHED_AT)
        self.assertEqual(registry.manifest_downloads, [("alice/web", "sha256:b")])

    def test_tags_missing_in_registry_are_removed(self):
        Tag.objects.create(repository=self.repository, name="old", digest="sha256:x", pushed_at=PUSHED_AT)

        result = self.sync(FakeRegistry())

        self.assertEqual(result.removed, 1)
        self.assertFalse(self.repository.tags.exists())

    def test_nothing_changed_is_not_logged(self):
        Tag.objects.create(repository=self.repository, name="1.0", digest="sha256:a", pushed_at=PUSHED_AT)

        with self.assertNoLogs("repositories.services.registry.sync", "INFO"):
            result = self.sync(FakeRegistry({"alice/web": {"1.0": image("sha256:a")}}))

        self.assertFalse(result.changed)

    def test_registry_error_changes_nothing(self):
        Tag.objects.create(repository=self.repository, name="1.0", digest="sha256:a", pushed_at=PUSHED_AT)

        with self.assertRaises(RegistryError):
            self.sync(FakeRegistry(error=RegistryError("down")))

        self.assertEqual(list(self.repository.tags.values_list("name", flat=True)), ["1.0"])

    def test_tag_without_push_event_gets_current_time(self):
        before = timezone.now()
        registry = FakeRegistry({"alice/web": {"1.0": image("sha256:a"), "latest": image("sha256:a")}})

        with self.assertLogs("repositories.services.registry.sync", "INFO"):
            sync_repository(self.repository, pushed_at={"1.0": PUSHED_AT}, client=registry)

        self.assertEqual(self.repository.tags.get(name="1.0").pushed_at, PUSHED_AT)
        self.assertGreaterEqual(self.repository.tags.get(name="latest").pushed_at, before)

    def test_concurrent_sync_creating_the_same_tag_is_retried(self):
        registry = FakeRegistry({"alice/web": {"1.0": image("sha256:a")}})
        real_write = sync_module._write_tags
        calls = []

        def write_once_failing(*args):
            # The first write fails as if another sync had just created the tag
            calls.append(args)
            if len(calls) == 1:
                raise IntegrityError("duplicate")
            return real_write(*args)

        with patch.object(sync_module, "_write_tags", side_effect=write_once_failing) as write:
            with self.assertLogs("repositories.services.registry.sync", "INFO"):
                result = self.sync(registry)

        self.assertEqual(write.call_count, 2)
        self.assertEqual(result.added, 1)
        self.assertEqual(self.repository.tags.count(), 1)

    def test_uses_configured_client_by_default(self):
        with patch(SYNC_CLIENT, return_value=FakeRegistry({"alice/web": {"1.0": image("sha256:a")}})):
            with self.assertLogs("repositories.services.registry.sync", "INFO"):
                result = sync_repository(self.repository)

        self.assertEqual(result.added, 1)


class TagModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        cls.repository = Repository.objects.create(owner=cls.alice, name="web")

    def test_str_is_image_reference(self):
        tag = Tag.objects.create(repository=self.repository, name="1.0", digest="sha256:a", pushed_at=PUSHED_AT)

        self.assertEqual(str(tag), "alice/web:1.0")

    def test_tag_name_is_unique_per_repository(self):
        Tag.objects.create(repository=self.repository, name="1.0", digest="sha256:a", pushed_at=PUSHED_AT)
        other = Repository.objects.create(owner=self.alice, name="api")
        Tag.objects.create(repository=other, name="1.0", digest="sha256:a", pushed_at=PUSHED_AT)

        with self.assertRaises(IntegrityError):
            Tag.objects.create(repository=self.repository, name="1.0", digest="sha256:b", pushed_at=PUSHED_AT)

    def test_newest_tags_come_first(self):
        Tag.objects.create(repository=self.repository, name="old", digest="sha256:a", pushed_at=PUSHED_AT)
        Tag.objects.create(
            repository=self.repository, name="new", digest="sha256:b", pushed_at=PUSHED_AT + datetime.timedelta(1)
        )

        self.assertEqual([tag.name for tag in self.repository.tags.all()], ["new", "old"])


@override_settings(REGISTRY_EVENTS_TOKEN=EVENTS_TOKEN)
class RegistryEventsViewTests(TestCase):
    """Integration tests for the notifications webhook, using the test client."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        cls.repository = Repository.objects.create(owner=cls.alice, name="web")

    def setUp(self):
        self.url = reverse("registry_events")
        self.registry = FakeRegistry({"alice/web": {"1.0": image("sha256:abc", 123)}})
        patcher = patch(SYNC_CLIENT, return_value=self.registry)
        patcher.start()
        self.addCleanup(patcher.stop)

    def post_events(self, events, token=EVENTS_TOKEN, body=None):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"} if token else {}
        data = body if body is not None else json.dumps({"events": events})
        return self.client.post(
            self.url, data, content_type="application/vnd.docker.distribution.events.v1+json", **headers
        )

    def test_push_event_syncs_tags(self):
        response = self.post_events([event()])

        self.assertEqual(response.status_code, 200)
        tag = self.repository.tags.get()
        self.assertEqual((tag.name, tag.digest, tag.size, tag.pushed_at), ("1.0", "sha256:abc", 123, PUSHED_AT))

    def test_tags_appear_on_detail_page(self):
        self.post_events([event()])

        response = self.client.get(reverse("repositories:detail", args=[self.repository.pk]))

        self.assertContains(response, "sha256:abc")

    def test_repeated_event_does_not_duplicate_tags(self):
        self.post_events([event()])
        response = self.post_events([event()])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.repository.tags.count(), 1)

    def test_delete_event_removes_tags(self):
        self.post_events([event()])
        self.registry.images = {}

        self.post_events([event(action="delete", tag=None, media_type=None)])

        self.assertFalse(self.repository.tags.exists())

    def test_multi_arch_push_syncs_once(self):
        events = [event(tag=None, media_type=OCI_MANIFEST, digest=f"sha256:{n}") for n in range(5)]
        events.append(event())

        with patch("repositories.views.sync_repository") as sync:
            self.post_events(events)

        sync.assert_called_once_with(self.repository, pushed_at={"1.0": PUSHED_AT}, client=self.registry)

    def test_missing_or_wrong_token_is_rejected(self):
        for token in (None, "wrong-secret"):
            with self.subTest(token=token), self.assertLogs("repositories.views", "WARNING"):
                response = self.post_events([event()], token=token)

                self.assertEqual(response.status_code, 401)
        self.assertFalse(self.repository.tags.exists())

    @override_settings(REGISTRY_EVENTS_TOKEN="")
    def test_endpoint_is_disabled_without_configured_token(self):
        with self.assertLogs("repositories.views", "ERROR"):
            response = self.post_events([event()], token="")

        self.assertEqual(response.status_code, 503)

    def test_malformed_body_returns_400(self):
        for body in ("not json", json.dumps({"no": "events"})):
            with self.subTest(body=body), self.assertLogs("repositories.views", "WARNING"):
                self.assertEqual(self.post_events([], body=body).status_code, 400)

    def test_unknown_repository_is_logged_and_ignored(self):
        # E.g. delete events that arrive after the repository was deleted: not a warning
        with self.assertLogs("repositories.views", "INFO") as logs:
            response = self.post_events([event(repository="alice/missing")])

        self.assertEqual(response.status_code, 200)
        self.assertEqual([record.levelname for record in logs.records], ["INFO"])
        self.assertIn("Registry event for unknown repository: path='alice/missing'", logs.output[0])

    def test_registry_error_is_logged_and_still_returns_200(self):
        self.registry.error = RegistryError("down")

        with self.assertLogs("repositories.views", "WARNING") as logs:
            response = self.post_events([event()])

        self.assertEqual(response.status_code, 200)
        self.assertIn("Registry unavailable, tags not synced: path=alice/web", logs.output[0])
        self.assertEqual(logs.records[0].repo_id, self.repository.pk)

    def test_only_post_is_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)


class RepositoryDeleteWithRegistryTests(TestCase):
    """Deleting a repository also deletes its images from the registry."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)

    def setUp(self):
        self.repository = Repository.objects.create(owner=self.alice, name="web")
        Tag.objects.create(repository=self.repository, name="1.0", digest="sha256:a", pushed_at=PUSHED_AT)
        self.registry = Mock()
        self.registry.delete_repository.return_value = 1
        patcher = patch(VIEWS_CLIENT, return_value=self.registry)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client.force_login(self.alice)

    def delete(self):
        return self.client.post(
            reverse("repositories:delete", args=[self.repository.pk]), {"confirm_name": "web"}, follow=True
        )

    def test_images_and_tags_are_deleted_with_repository(self):
        with self.assertLogs("repositories.views", "INFO") as logs:
            response = self.delete()

        self.registry.delete_repository.assert_called_once_with("alice/web")
        self.assertRedirects(response, reverse("repositories:list"))
        self.assertFalse(Repository.objects.filter(pk=self.repository.pk).exists())
        self.assertFalse(Tag.objects.exists())
        self.assertIn("Repository deleted: path=alice/web", logs.output[-1])
        self.assertIn("manifests=1", logs.output[-1])

    def test_repository_without_images_is_deleted(self):
        # The registry answers 404 for a repository it does not know: delete_repository returns 0
        self.registry.delete_repository.return_value = 0

        self.delete()

        self.assertFalse(Repository.objects.filter(pk=self.repository.pk).exists())

    def test_repository_is_kept_when_registry_is_unavailable(self):
        self.registry.delete_repository.side_effect = RegistryError("Connection refused")

        with self.assertLogs("repositories.views", "WARNING") as logs:
            response = self.delete()

        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "The repository was kept", status_code=503)
        self.assertTrue(Repository.objects.filter(pk=self.repository.pk).exists())
        self.assertTrue(Tag.objects.exists())
        self.assertIn("Registry unavailable, repository not deleted: path=alice/web", logs.output[0])
        self.assertEqual(logs.records[0].repo_id, self.repository.pk)

    def test_wrong_confirmation_does_not_call_registry(self):
        self.client.post(reverse("repositories:delete", args=[self.repository.pk]), {"confirm_name": "nope"})

        self.registry.delete_repository.assert_not_called()


class SyncRegistryCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        cls.web = Repository.objects.create(owner=cls.alice, name="web")
        cls.api = Repository.objects.create(owner=cls.alice, name="api")

    def run_command(self, registry, *args):
        out = StringIO()
        with patch(SYNC_CLIENT, return_value=registry):
            call_command("sync_registry", *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_syncs_all_repositories(self):
        registry = FakeRegistry({"alice/web": {"1.0": image("sha256:a")}, "alice/api": {"2.0": image("sha256:b")}})

        with self.assertLogs("repositories.services.registry.sync", "INFO"):
            output = self.run_command(registry)

        self.assertIn("alice/web: added=1 updated=0 removed=0", output)
        self.assertIn("alice/api: added=1 updated=0 removed=0", output)
        self.assertIn("Registry sync finished.", output)
        self.assertEqual(Tag.objects.count(), 2)

    def test_syncs_one_repository(self):
        registry = FakeRegistry({"alice/web": {"1.0": image("sha256:a")}, "alice/api": {"2.0": image("sha256:b")}})

        with self.assertLogs("repositories.services.registry.sync", "INFO"):
            output = self.run_command(registry, "--repository", "alice/web")

        self.assertNotIn("alice/api", output)
        self.assertEqual(list(Tag.objects.values_list("name", flat=True)), ["1.0"])

    def test_unknown_repository_fails(self):
        with self.assertRaisesMessage(CommandError, "alice/missing does not exist"):
            self.run_command(FakeRegistry(), "--repository", "alice/missing")

    def test_registry_error_fails_after_trying_all(self):
        with self.assertRaisesMessage(CommandError, "2 repositories could not be synced"):
            self.run_command(FakeRegistry(error=RegistryError("down")))


@override_settings(
    REGISTRY_CLIENT_CLASS="repositories.services.registry.mock.MockRegistryClient",
    REGISTRY_EVENTS_TOKEN=EVENTS_TOKEN,
)
class SyncWithMockClientTests(TestCase):
    """A sync with the mock (no images) would delete every tag, so it is refused."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        cls.repository = Repository.objects.create(owner=cls.alice, name="web")

    def setUp(self):
        Tag.objects.create(repository=self.repository, name="1.0", digest="sha256:a", pushed_at=PUSHED_AT)

    def assert_tags_kept(self):
        self.assertEqual(list(self.repository.tags.values_list("name", flat=True)), ["1.0"])

    def test_sync_repository_refuses_mock(self):
        for client in (None, MockRegistryClient()):
            with self.subTest(client=client), self.assertRaises(SyncNotConfiguredError):
                sync_repository(self.repository, client=client)
        self.assert_tags_kept()

    def test_webhook_refuses_mock(self):
        with self.assertLogs("repositories.views", "WARNING") as logs:
            response = self.client.post(
                reverse("registry_events"),
                json.dumps({"events": [event(action="delete", tag=None, media_type=None)]}),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {EVENTS_TOKEN}",
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("MockRegistryClient", response.json()["error"])
        self.assertIn("Registry events not synced: REGISTRY_CLIENT_CLASS is MockRegistryClient", logs.output[0])
        self.assert_tags_kept()

    def test_command_refuses_mock(self):
        with self.assertLogs("repositories.management.commands.sync_registry", "WARNING") as logs:
            with self.assertRaisesMessage(CommandError, "REGISTRY_CLIENT_CLASS is MockRegistryClient"):
                call_command("sync_registry", stdout=StringIO())

        self.assertIn("Registry sync refused", logs.output[0])
        self.assert_tags_kept()


HTTP_CLIENT_CLASS = "repositories.services.registry.http.HttpRegistryClient"
REQUESTS_REQUEST = "repositories.services.registry.http.requests.request"


def http_response(status_code=200, json_body=None, headers=None, url="http://registry.test:5000/v2/"):
    response = Mock(status_code=status_code, headers=headers or {}, url=url, links={})
    response.request.method = "GET"
    if isinstance(json_body, Exception):
        response.json.side_effect = json_body
    else:
        response.json.return_value = json_body if json_body is not None else {}
    return response


@token_settings(
    REGISTRY_CLIENT_CLASS=HTTP_CLIENT_CLASS,
    REGISTRY_URL="http://registry.test:5000",
    REGISTRY_EVENTS_TOKEN=EVENTS_TOKEN,
)
class HttpClientErrorHandlingTests(TestCase):
    """Token and JSON errors of the real client are RegistryErrors, so callers handle them."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        # Created first, so sync_registry fails on it before reaching alice/web
        cls.api = Repository.objects.create(owner=cls.alice, name="api")
        cls.web = Repository.objects.create(owner=cls.alice, name="web")

    def setUp(self):
        Tag.objects.create(repository=self.web, name="old", digest="sha256:old", pushed_at=PUSHED_AT)
        patcher = patch(REQUESTS_REQUEST)
        self.request = patcher.start()
        self.addCleanup(patcher.stop)

    def missing_key(self):
        return token_settings(REGISTRY_TOKEN_PRIVATE_KEY_PATH=KEY_DIR / "missing.key")

    def test_webhook_returns_200_when_token_cannot_be_signed(self):
        with self.missing_key(), self.assertLogs("repositories.views", "WARNING") as logs:
            response = self.client.post(
                reverse("registry_events"),
                json.dumps({"events": [event(repository="alice/web")]}),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {EVENTS_TOKEN}",
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Registry unavailable, tags not synced: path=alice/web", logs.output[0])
        self.assertIn("Cannot sign a registry token", logs.output[0])
        self.request.assert_not_called()
        self.assertEqual(list(self.web.tags.values_list("name", flat=True)), ["old"])

    def test_delete_returns_503_when_token_cannot_be_signed(self):
        self.client.force_login(self.alice)

        with self.missing_key(), self.assertLogs("repositories.views", "WARNING"):
            response = self.client.post(reverse("repositories:delete", args=[self.web.pk]), {"confirm_name": "web"})

        self.assertEqual(response.status_code, 503)
        self.assertTrue(Repository.objects.filter(pk=self.web.pk).exists())

    def test_sync_registry_continues_after_invalid_json(self):
        def registry(method, url, **kwargs):
            if url.endswith("/v2/alice/api/tags/list?n=100"):
                return http_response(json_body=ValueError("Expecting value"), url=url)
            if url.endswith("/v2/alice/web/tags/list?n=100"):
                return http_response(json_body={"tags": ["1.0"]}, url=url)
            if method == "HEAD":
                return http_response(headers={"Docker-Content-Digest": "sha256:new"}, url=url)
            return http_response(
                json_body={"mediaType": OCI_MANIFEST, "config": {"size": 1}, "layers": [{"size": 2}]},
                headers={"Docker-Content-Digest": "sha256:new"},
                url=url,
            )

        self.request.side_effect = registry
        out, err = StringIO(), StringIO()

        with self.assertLogs("repositories.services.registry.sync", "INFO"):
            with self.assertRaisesMessage(CommandError, "1 repositories could not be synced"):
                call_command("sync_registry", stdout=out, stderr=err)

        self.assertIn("alice/api: ", err.getvalue())
        self.assertIn("did not return JSON", err.getvalue())
        self.assertIn("alice/web: added=1 updated=0 removed=1", out.getvalue())
        self.assertEqual(list(self.web.tags.values_list("name", "digest", "size")), [("1.0", "sha256:new", 3)])


@token_settings(REGISTRY_CLIENT_CLASS=HTTP_CLIENT_CLASS, REGISTRY_URL="http://registry.test:5000")
class OfficialRepositoryRegistryTests(TestCase):
    """Official repositories live at ``<name>`` in the registry, without an owner prefix."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_admin(username="admin1", email="admin@example.com", password=PASSWORD)
        cls.official = Repository.objects.create(owner=cls.admin, name="nginx", is_official=True)

    def test_sync_uses_path_without_owner(self):
        registry = FakeRegistry({"nginx": {"latest": image("sha256:off", 42)}})

        with patch(SYNC_CLIENT, return_value=registry), self.assertLogs("repositories.services.registry.sync", "INFO"):
            output = StringIO()
            call_command("sync_registry", "--repository", "nginx", stdout=output)

        self.assertIn("nginx: added=1", output.getvalue())
        self.assertEqual(self.official.tags.get().digest, "sha256:off")

    @override_settings(REGISTRY_EVENTS_TOKEN=EVENTS_TOKEN)
    def test_webhook_syncs_official_repository(self):
        registry = FakeRegistry({"nginx": {"latest": image("sha256:off")}})

        with patch(SYNC_CLIENT, return_value=registry), self.assertLogs("repositories.services.registry.sync", "INFO"):
            response = self.client.post(
                reverse("registry_events"),
                json.dumps({"events": [event(repository="nginx", tag="latest")]}),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {EVENTS_TOKEN}",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.official.tags.get().name, "latest")

    @patch(REQUESTS_REQUEST)
    def test_delete_uses_path_without_owner(self, request):
        request.side_effect = [
            http_response(json_body={"tags": ["latest"]}),
            http_response(headers={"Docker-Content-Digest": "sha256:off"}),
            http_response(202),
        ]

        deleted = get_registry_client().delete_repository(self.official.registry_path)

        self.assertEqual(deleted, 1)
        urls = [call.args[1] for call in request.call_args_list]
        self.assertEqual(
            urls,
            [
                "http://registry.test:5000/v2/nginx/tags/list?n=100",
                "http://registry.test:5000/v2/nginx/manifests/latest",
                "http://registry.test:5000/v2/nginx/manifests/sha256:off",
            ],
        )
