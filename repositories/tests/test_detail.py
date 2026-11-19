
from unittest.mock import Mock, patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from repositories.models import Repository, RepositoryStar, Visibility
from repositories.services.registry.base import RegistryError

PASSWORD = "Tr1cky-pass-2026"


class RepositoryDetailViewTests(TestCase):
    """Integration tests for displaying repository details."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        cls.bob = User.objects.create_user(username="bob", email="bob@example.com", password=PASSWORD)
        cls.carol = User.objects.create_user(username="carol", email="carol@example.com", password=PASSWORD)
        cls.public_repository = Repository.objects.create(
            owner=cls.alice,
            name="nginx",
            description="High-performance HTTP server.",
            visibility=Visibility.PUBLIC,
        )
        cls.private_repository = Repository.objects.create(
            owner=cls.alice,
            name="private-app",
            description="Private application.",
            visibility=Visibility.PRIVATE,
        )

    def setUp(self):
        self.tags = [
            {
                "name": "latest",
                "digest": "sha256:abc123",
                "pushed_at": timezone.now(),
            },
            {
                "name": "1.0.0",
                "digest": "sha256:def456",
                "pushed_at": None,
            },
        ]

        self.registry_client = Mock()
        self.registry_client.list_tags.return_value = self.tags

        # Prevent tests from making actual registry requests.
        patcher = patch("repositories.views.get_registry_client", return_value=self.registry_client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def get_detail_url(self, repository):
        return reverse("repositories:detail", kwargs={"pk": repository.pk})

    def test_public_repository_is_accessible_to_anonymous_users(self):
        response = self.client.get(self.get_detail_url(self.public_repository))

        self.assertEqual(response.status_code, 200)

    def test_private_repository_is_not_accessible_to_anonymous_users(self):
        response = self.client.get(self.get_detail_url(self.private_repository))

        self.assertEqual(response.status_code, 404)

    def test_owner_can_access_private_repository(self):
        self.client.force_login(self.alice)

        response = self.client.get(self.get_detail_url(self.private_repository))

        self.assertEqual(response.status_code, 200)

    def test_other_users_cannot_access_private_repository(self):
        self.client.force_login(self.bob)

        response = self.client.get(self.get_detail_url(self.private_repository))

        self.assertEqual(response.status_code, 404)

    def test_nonexistent_repository_returns_404(self):
        response = self.client.get(reverse("repositories:detail", kwargs={"pk": 9999}))

        self.assertEqual(response.status_code, 404)

    def test_detail_page_renders(self):
        response = self.client.get(self.get_detail_url(self.public_repository))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "repositories/repository_detail.html")
        self.assertContains(response, "alice/nginx")
        self.assertContains(response, "High-performance HTTP server.")

    def test_repository_details_are_available_in_context(self):
        response = self.client.get(self.get_detail_url(self.public_repository))

        repository = response.context["repository"]
 
        self.assertEqual(repository, self.public_repository)
        self.assertEqual(repository.owner, self.alice)
        self.assertEqual(repository.name, "nginx")
        self.assertEqual(repository.visibility, Visibility.PUBLIC)

    def test_official_repository_is_displayed_without_owner_prefix(self):
        repository = Repository.objects.create(owner=self.alice, name="official-app", is_official=True)

        response = self.client.get(self.get_detail_url(repository))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "official-app")
        self.assertNotContains(response, "alice/official-app")
        self.assertContains(response, "Docker Official Image")

    def test_star_count_is_displayed(self):
        RepositoryStar.objects.create(repository=self.public_repository, user=self.bob)
        RepositoryStar.objects.create(repository=self.public_repository, user=self.carol)
        response = self.client.get(self.get_detail_url(self.public_repository))

        self.assertEqual(response.context["repository"].star_count, 2)
        self.assertContains(response, "2")

    def test_is_starred_is_false_for_anonymous_user(self):
        response = self.client.get(self.get_detail_url(self.public_repository))

        self.assertFalse(response.context["is_starred"])
        self.assertNotContains(response, "Starred by you")

    def test_is_starred_is_false_when_user_has_not_starred_repository(self):
        self.client.force_login(self.bob)

        response = self.client.get(self.get_detail_url(self.public_repository))

        self.assertFalse(response.context["is_starred"])
        self.assertNotContains(response, "Starred by you")

    def test_is_starred_is_true_when_user_has_starred_repository(self):
        RepositoryStar.objects.create(repository=self.public_repository, user=self.bob)
        self.client.force_login(self.bob)

        response = self.client.get(self.get_detail_url(self.public_repository))

        self.assertTrue(response.context["is_starred"])
        self.assertContains(response, "Starred by you")

    def test_tags_are_retrieved_from_registry(self):
        response = self.client.get(self.get_detail_url(self.public_repository))

        self.registry_client.list_tags.assert_called_once_with(self.public_repository)

        self.assertEqual(response.context["tags"], self.tags)
        self.assertFalse(response.context["registry_unavailable"])

        self.assertContains(response, "latest")
        self.assertContains(response, "1.0.0")
        self.assertContains(response, "sha256:abc123")
        self.assertContains(response, "sha256:def456")

    def test_empty_tag_list_is_displayed(self):
        self.registry_client.list_tags.return_value = []

        response = self.client.get(self.get_detail_url(self.public_repository))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["tags"], [])
        self.assertFalse(response.context["registry_unavailable"])
        self.assertContains(response, "No tags available")

    def test_registry_error_is_handled(self):
        self.registry_client.list_tags.side_effect = RegistryError("Registry unavailable")

        with self.assertLogs("repositories.views", level="WARNING") as logs:
            response = self.client.get(self.get_detail_url(self.public_repository))

        self.assertEqual(logs.records[0].levelname, "WARNING")
        self.assertEqual(logs.records[0].repo_id, self.public_repository.pk)
        self.assertIn(
            f"Registry unavailable, cannot list tags: path=alice/nginx id={self.public_repository.pk} "
            "error=Registry unavailable",
            logs.output[0],
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["tags"], [])
        self.assertTrue(response.context["registry_unavailable"])
        self.assertContains(response, "Unable to retrieve tags from the container registry.")
