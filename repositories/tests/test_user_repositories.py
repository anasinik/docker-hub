from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from repositories.models import Repository, RepositoryStar, Visibility

PASSWORD = "Tr1cky-pass-2025"


class UserRepositoryListViewTests(TestCase):
    url = reverse("repositories:list")

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        cls.bob = User.objects.create_user(username="bob1", email="bob@example.com", password=PASSWORD)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(self.url)

        login_url = reverse(settings.LOGIN_URL)
        self.assertRedirects(response, f"{login_url}?next={self.url}", fetch_redirect_response=False)

    def test_admins_are_forbidden(self):
        admin = User.objects.create_admin(username="admin1", email="admin@example.com", password=PASSWORD)
        self.client.force_login(admin)

        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_shows_own_public_and_private_repositories_only(self):
        Repository.objects.create(owner=self.alice, name="public-app")
        Repository.objects.create(owner=self.alice, name="secret-app", visibility=Visibility.PRIVATE)
        Repository.objects.create(owner=self.bob, name="bobs-app")
        self.client.force_login(self.alice)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "repositories/repository_list.html")
        names = [repository.name for repository in response.context["repositories"]]
        self.assertCountEqual(names, ["public-app", "secret-app"])
        self.assertContains(response, "alice/secret-app")
        self.assertContains(response, "Private")
        self.assertNotContains(response, "bobs-app")

    def test_most_recently_updated_first(self):
        older = Repository.objects.create(owner=self.alice, name="older")
        newer = Repository.objects.create(owner=self.alice, name="newer")
        now = timezone.now()
        Repository.objects.filter(pk=newer.pk).update(updated_at=now - timedelta(hours=1))
        Repository.objects.filter(pk=older.pk).update(updated_at=now)
        self.client.force_login(self.alice)

        names = [repository.name for repository in self.client.get(self.url).context["repositories"]]

        self.assertEqual(names, ["older", "newer"])

    def test_shows_star_count(self):
        repository = Repository.objects.create(owner=self.alice, name="starred")
        RepositoryStar.objects.create(repository=repository, user=self.bob)
        self.client.force_login(self.alice)

        listed = self.client.get(self.url).context["repositories"][0]

        self.assertEqual(listed.star_count, 1)

    def test_empty_list_message(self):
        self.client.force_login(self.alice)

        response = self.client.get(self.url)

        self.assertContains(response, "You don't have any repositories yet.")
        self.assertContains(response, f'href="{reverse("repositories:create")}"')

    def test_pagination(self):
        for i in range(13):
            Repository.objects.create(owner=self.alice, name=f"app-{i:02d}")
        self.client.force_login(self.alice)

        first = self.client.get(self.url)
        second = self.client.get(self.url, {"page": 2})

        self.assertEqual(len(first.context["repositories"]), 12)
        self.assertContains(first, "Page 1 of 2")
        self.assertEqual(len(second.context["repositories"]), 1)

    def test_header_links_to_list_for_regular_users_only(self):
        home = reverse("core:home")
        link = f'href="{self.url}"'

        self.assertNotContains(self.client.get(home), link)

        self.client.force_login(self.alice)
        self.assertContains(self.client.get(home), link)

        admin = User.objects.create_admin(username="admin1", email="admin@example.com", password=PASSWORD)
        self.client.force_login(admin)
        self.assertNotContains(self.client.get(home), link)
