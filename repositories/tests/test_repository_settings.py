from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from repositories.models import Repository, Visibility

PASSWORD = "Tr1cky-pass-2025"


class RepositorySettingsViewTests(TestCase):
    """Integration tests for editing repository settings, using the test client."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        cls.bob = User.objects.create_user(username="bob1", email="bob@example.com", password=PASSWORD)

    def setUp(self):
        self.repository = Repository.objects.create(owner=self.alice, name="nginx", description="Web server")
        self.url = reverse("repositories:settings", args=[self.repository.pk])
        self.detail_url = reverse("repositories:detail", args=[self.repository.pk])

    def post_settings(self, url=None, **overrides):
        data = {"description": "Reverse proxy", "visibility": Visibility.PRIVATE}
        data.update(overrides)
        return self.client.post(url or self.url, data, follow=True)

    def assert_unchanged(self):
        self.repository.refresh_from_db()
        self.assertEqual(self.repository.name, "nginx")
        self.assertEqual(self.repository.description, "Web server")
        self.assertEqual(self.repository.visibility, Visibility.PUBLIC)

    def test_anonymous_user_is_redirected_to_login(self):
        for method in (self.client.get, self.client.post):
            with self.subTest(method=method.__name__):
                response = method(self.url)

                login_url = reverse(settings.LOGIN_URL)
                self.assertRedirects(response, f"{login_url}?next={self.url}", fetch_redirect_response=False)

        self.assert_unchanged()

    def test_admins_are_forbidden(self):
        admins = (
            User.objects.create_admin(username="admin1", email="admin@example.com", password=PASSWORD),
            User.objects.create_superuser(username="root1", email="root@example.com", password=PASSWORD),
        )
        for admin in admins:
            with self.subTest(role=admin.role):
                self.client.force_login(admin)

                self.assertEqual(self.client.get(self.url).status_code, 403)
                self.assertEqual(self.post_settings().status_code, 403)

        self.assert_unchanged()

    def test_other_users_repository_is_not_found(self):
        self.client.force_login(self.bob)

        for visibility in (Visibility.PRIVATE, Visibility.PUBLIC):
            with self.subTest(visibility=visibility):
                Repository.objects.filter(pk=self.repository.pk).update(visibility=visibility)

                self.assertEqual(self.client.get(self.url).status_code, 404)
                self.assertEqual(self.post_settings(visibility=Visibility.PRIVATE, description="hacked").status_code, 404)

                self.repository.refresh_from_db()
                self.assertEqual(self.repository.description, "Web server")
                self.assertEqual(self.repository.visibility, visibility)

    def test_missing_repository_is_not_found(self):
        self.client.force_login(self.alice)

        response = self.client.get(reverse("repositories:settings", args=[self.repository.pk + 1000]))

        self.assertEqual(response.status_code, 404)

    def test_settings_page_renders_current_values(self):
        self.client.force_login(self.alice)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "repositories/repository_settings.html")
        self.assertContains(response, "alice/nginx")
        self.assertContains(response, 'name="description"')
        self.assertContains(response, "Web server</textarea>")
        self.assertContains(response, 'name="visibility"')
        self.assertContains(response, '<option value="PUBLIC" selected>')
        self.assertNotContains(response, 'name="name"')
        self.assertNotContains(response, 'name="owner"')
        self.assertNotContains(response, 'name="is_official"')

    def test_successful_update(self):
        self.client.force_login(self.alice)

        response = self.post_settings()

        self.assertRedirects(response, self.detail_url)
        self.repository.refresh_from_db()
        self.assertEqual(self.repository.description, "Reverse proxy")
        self.assertEqual(self.repository.visibility, Visibility.PRIVATE)
        self.assertContains(response, "Repository alice/nginx has been updated.")

    def test_visibility_change_affects_search(self):
        search_url = reverse("repository_search")
        self.client.force_login(self.alice)

        self.post_settings(visibility=Visibility.PRIVATE)
        self.assertNotIn(self.repository, self.client.get(search_url).context["repositories"])

        self.post_settings(visibility=Visibility.PUBLIC)
        self.assertIn(self.repository, self.client.get(search_url).context["repositories"])

    def test_posted_name_owner_and_official_flag_are_ignored(self):
        self.client.force_login(self.alice)

        self.post_settings(name="renamed", owner=self.bob.pk, is_official="on")

        self.repository.refresh_from_db()
        self.assertEqual(self.repository.name, "nginx")
        self.assertEqual(self.repository.owner, self.alice)
        self.assertFalse(self.repository.is_official)

    def test_invalid_data_shows_errors_and_changes_nothing(self):
        self.client.force_login(self.alice)

        response = self.post_settings(description="a" * 101, visibility="SECRET")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "repositories/repository_settings.html")
        self.assertContains(response, "Ensure this value has at most 100 characters")
        self.assertContains(response, "Select a valid choice.")
        self.assert_unchanged()

    def test_update_is_logged(self):
        self.client.force_login(self.alice)

        with self.assertLogs("repositories.views", level="INFO") as logs:
            self.post_settings()

        self.assertIn("Repository settings updated: path=alice/nginx", logs.output[0])
        self.assertIn("visibility=PRIVATE", logs.output[0])

    def test_detail_page_shows_settings_link_only_to_owner(self):
        link = f'href="{self.url}"'

        self.assertNotContains(self.client.get(self.detail_url), link)

        self.client.force_login(self.bob)
        self.assertNotContains(self.client.get(self.detail_url), link)

        self.client.force_login(self.alice)
        self.assertContains(self.client.get(self.detail_url), link)
