
from unittest.mock import Mock, patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from repositories.models import Repository, RepositoryStar, Tag, Visibility

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
        now = timezone.now()
        self.tags = [
            Tag.objects.create(
                repository=self.public_repository, name="latest", digest="sha256:abc123", pushed_at=now
            ),
            Tag.objects.create(
                repository=self.public_repository,
                name="1.0.0",
                digest="sha256:def456",
                pushed_at=now - timezone.timedelta(days=1),
            ),
        ]

        self.registry_client = Mock()

        # Tags come from the database (synced on push); the page must not call the registry.
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

    def test_tags_are_read_from_database(self):
        response = self.client.get(self.get_detail_url(self.public_repository))

        self.assertFalse(self.registry_client.method_calls)

        self.assertEqual(list(response.context["tags"]), self.tags)

        self.assertContains(response, "latest")
        self.assertContains(response, "1.0.0")
        self.assertContains(response, "sha256:abc123")
        self.assertContains(response, "sha256:def456")

    def test_empty_tag_list_is_displayed(self):
        empty_repository = Repository.objects.create(owner=self.alice, name="empty")

        response = self.client.get(self.get_detail_url(empty_repository))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["tags"]), [])
        self.assertContains(response, "No tags available")

    def test_only_tags_of_this_repository_are_shown(self):
        other = Repository.objects.create(owner=self.bob, name="other")
        Tag.objects.create(repository=other, name="v9", digest="sha256:999", pushed_at=timezone.now())

        response = self.client.get(self.get_detail_url(self.public_repository))

        self.assertEqual([tag.name for tag in response.context["tags"]], ["latest", "1.0.0"])
        self.assertNotContains(response, "sha256:999")
