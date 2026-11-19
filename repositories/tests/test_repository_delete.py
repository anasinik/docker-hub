from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from repositories.models import Repository, RepositoryStar, Visibility

PASSWORD = "Tr1cky-pass-2025"


class RepositoryDeleteViewTests(TestCase):
    """Integration tests for deleting a repository, using the test client."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        cls.bob = User.objects.create_user(username="bob1", email="bob@example.com", password=PASSWORD)

    def setUp(self):
        self.repository = Repository.objects.create(owner=self.alice, name="nginx")
        self.url = reverse("repositories:delete", args=[self.repository.pk])

    def post_delete(self, confirm_name="nginx", url=None):
        return self.client.post(url or self.url, {"confirm_name": confirm_name}, follow=True)

    def assert_not_deleted(self):
        self.assertTrue(Repository.objects.filter(pk=self.repository.pk).exists())

    def test_anonymous_user_is_redirected_to_login(self):
        for method in (self.client.get, self.client.post):
            with self.subTest(method=method.__name__):
                response = method(self.url)

                login_url = reverse(settings.LOGIN_URL)
                self.assertRedirects(response, f"{login_url}?next={self.url}", fetch_redirect_response=False)

        self.assert_not_deleted()

    def test_admins_are_forbidden(self):
        admins = (
            User.objects.create_admin(username="admin1", email="admin@example.com", password=PASSWORD),
            User.objects.create_superuser(username="root1", email="root@example.com", password=PASSWORD),
        )
        for admin in admins:
            with self.subTest(role=admin.role):
                self.client.force_login(admin)

                self.assertEqual(self.client.get(self.url).status_code, 403)
                self.assertEqual(self.post_delete().status_code, 403)

        self.assert_not_deleted()

    def test_other_users_repository_is_not_found(self):
        self.client.force_login(self.bob)

        for visibility in (Visibility.PUBLIC, Visibility.PRIVATE):
            with self.subTest(visibility=visibility):
                Repository.objects.filter(pk=self.repository.pk).update(visibility=visibility)

                self.assertEqual(self.client.get(self.url).status_code, 404)
                self.assertEqual(self.post_delete().status_code, 404)

        self.assert_not_deleted()

    def test_missing_repository_is_not_found(self):
        self.client.force_login(self.alice)

        url = reverse("repositories:delete", args=[self.repository.pk + 1000])

        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.post_delete(url=url).status_code, 404)

    def test_confirmation_page_renders(self):
        self.client.force_login(self.alice)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "repositories/repository_confirm_delete.html")
        self.assertContains(response, "alice/nginx")
        self.assertContains(response, 'name="confirm_name"')
        self.assertContains(response, "<code>nginx</code>")
        self.assert_not_deleted()

    def test_successful_delete(self):
        self.client.force_login(self.alice)

        response = self.post_delete()

        self.assertRedirects(response, reverse("repositories:list"))
        self.assertFalse(Repository.objects.filter(pk=self.repository.pk).exists())
        self.assertContains(response, "Repository alice/nginx has been deleted.")
        self.assertNotIn(self.repository, response.context["repositories"])

    def test_stars_are_deleted_with_repository(self):
        RepositoryStar.objects.create(repository=self.repository, user=self.bob)
        self.client.force_login(self.alice)

        self.post_delete()

        self.assertFalse(RepositoryStar.objects.exists())
        self.assertTrue(User.objects.filter(pk=self.bob.pk).exists())

    def test_other_repositories_are_kept(self):
        other = Repository.objects.create(owner=self.alice, name="redis")
        bobs = Repository.objects.create(owner=self.bob, name="nginx")
        self.client.force_login(self.alice)

        self.post_delete()

        self.assertEqual(set(Repository.objects.all()), {other, bobs})

    def test_deleted_repository_disappears_from_search_and_detail(self):
        detail_url = reverse("repositories:detail", args=[self.repository.pk])
        self.client.force_login(self.alice)

        self.post_delete()

        self.assertNotIn(self.repository, self.client.get(reverse("repository_search")).context["repositories"])
        self.assertEqual(self.client.get(detail_url).status_code, 404)

    def test_wrong_name_deletes_nothing(self):
        self.client.force_login(self.alice)

        for value in ("redis", "alice/nginx", ""):
            with self.subTest(confirm_name=value):
                response = self.post_delete(confirm_name=value)

                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "repositories/repository_confirm_delete.html")
                self.assertTrue(response.context["form"].errors)

        self.assertContains(self.post_delete(confirm_name="redis"), "The name does not match this repository.")
        self.assert_not_deleted()

    def test_delete_is_logged(self):
        repository_id = self.repository.pk
        self.client.force_login(self.alice)

        with self.assertLogs("repositories.views", level="INFO") as logs:
            self.post_delete()

        self.assertIn(f"Repository deleted: path=alice/nginx id={repository_id}", logs.output[0])
        self.assertEqual(logs.records[0].repo_id, repository_id)

    def test_settings_page_links_to_delete(self):
        self.client.force_login(self.alice)

        response = self.client.get(reverse("repositories:settings", args=[self.repository.pk]))

        self.assertContains(response, "Danger zone")
        self.assertContains(response, f'href="{self.url}"')
