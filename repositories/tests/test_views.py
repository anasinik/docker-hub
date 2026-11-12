from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from repositories.models import Repository, Visibility

PASSWORD = "Tr1cky-pass-2025"


class RepositoryCreateViewTests(TestCase):
    """Integration tests for creating a repository, using the test client."""

    url = reverse("repositories:create")

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        cls.bob = User.objects.create_user(username="bob1", email="bob@example.com", password=PASSWORD)

    def post_create(self, **overrides):
        data = {"name": "nginx", "description": "Web server", "visibility": Visibility.PUBLIC}
        data.update(overrides)
        return self.client.post(self.url, data, follow=True)

    def test_anonymous_user_is_redirected_to_login(self):
        for method in (self.client.get, self.client.post):
            with self.subTest(method=method.__name__):
                response = method(self.url)

                login_url = reverse(settings.LOGIN_URL)
                self.assertRedirects(response, f"{login_url}?next={self.url}", fetch_redirect_response=False)

        self.assertFalse(Repository.objects.exists())

    def test_create_page_renders(self):
        self.client.force_login(self.alice)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "repositories/repository_form.html")
        self.assertContains(response, 'name="name"')
        self.assertContains(response, 'name="description"')
        self.assertContains(response, 'name="visibility"')
        self.assertNotContains(response, 'name="owner"')
        self.assertNotContains(response, 'name="is_official"')
        self.assertContains(response, "alice/&lt;name&gt;")

    def test_header_links_to_create_page_for_logged_in_users(self):
        home = reverse("core:home")

        self.assertNotContains(self.client.get(home), f'href="{self.url}"')

        self.client.force_login(self.alice)
        self.assertContains(self.client.get(home), f'href="{self.url}"')

    def test_successful_create(self):
        self.client.force_login(self.alice)

        response = self.post_create(name="My-App", visibility=Visibility.PRIVATE)

        self.assertRedirects(response, reverse("core:home"))
        repository = Repository.objects.get()
        self.assertEqual(repository.owner, self.alice)
        self.assertEqual(repository.name, "my-app")
        self.assertEqual(repository.visibility, Visibility.PRIVATE)
        self.assertFalse(repository.is_official)
        self.assertContains(response, "Repository alice/my-app has been created.")

    def test_create_is_logged(self):
        self.client.force_login(self.alice)

        with self.assertLogs("repositories.views", level="INFO") as logs:
            self.post_create()

        self.assertIn("Repository created: path=alice/nginx", logs.output[0])

    def test_posted_owner_and_official_flag_are_ignored(self):
        self.client.force_login(self.alice)

        self.post_create(owner=self.bob.pk, is_official="on")

        repository = Repository.objects.get()
        self.assertEqual(repository.owner, self.alice)
        self.assertFalse(repository.is_official)

    def test_invalid_data_shows_errors_and_creates_nothing(self):
        self.client.force_login(self.alice)

        response = self.post_create(name="my app", visibility="SECRET")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "repositories/repository_form.html")
        self.assertContains(response, "Repository name must be 2-100 characters long")
        self.assertContains(response, "Select a valid choice.")
        self.assertFalse(Repository.objects.exists())

    def test_duplicate_name_is_rejected(self):
        Repository.objects.create(owner=self.alice, name="nginx")
        self.client.force_login(self.alice)

        response = self.post_create(name="nginx")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You already have a repository with this name.")
        self.assertEqual(Repository.objects.count(), 1)

    def test_admins_are_forbidden(self):
        admins = (
            User.objects.create_admin(username="admin1", email="admin@example.com", password=PASSWORD),
            User.objects.create_superuser(username="root1", email="root@example.com", password=PASSWORD),
        )
        for admin in admins:
            with self.subTest(role=admin.role):
                self.client.force_login(admin)

                self.assertEqual(self.client.get(self.url).status_code, 403)
                self.assertEqual(self.client.post(self.url, {"name": "nginx", "visibility": "PUBLIC"}).status_code, 403)

        self.assertFalse(Repository.objects.exists())

    def test_header_hides_create_link_from_admins(self):
        admin = User.objects.create_admin(username="admin1", email="admin@example.com", password=PASSWORD)
        self.client.force_login(admin)

        self.assertNotContains(self.client.get(reverse("core:home")), f'href="{self.url}"')
