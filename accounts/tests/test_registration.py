from django.contrib.auth import get_user
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, User

PASSWORD = "Tr1cky-pass-2025"


class SignUpViewTests(TestCase):
    """Integration tests for self-registration, using the test client."""

    url = reverse("accounts:register")

    def post_sign_up(self, **overrides):
        data = {
            "username": "alice",
            "email": "alice@example.com",
            "password1": PASSWORD,
            "password2": PASSWORD,
        }
        data.update(overrides)
        return self.client.post(self.url, data, follow=True)

    def test_sign_up_page_renders(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/register.html")
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="email"')
        self.assertContains(response, 'name="password1"')
        self.assertContains(response, 'name="password2"')
        self.assertNotContains(response, 'name="role"')

    def test_header_links_to_sign_up_for_visitors(self):
        response = self.client.get(reverse("core:home"))

        self.assertContains(response, f'href="{self.url}"')

    def test_successful_sign_up(self):
        response = self.post_sign_up()

        self.assertRedirects(response, reverse("core:home"))
        user = User.objects.get(username="alice")
        self.assertEqual(user.email, "alice@example.com")
        self.assertEqual(user.role, Role.REGULAR_USER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertContains(response, "Welcome, alice! Your account has been created.")

    def test_user_is_logged_in_after_sign_up(self):
        self.post_sign_up()

        logged_in_user = get_user(self.client)
        self.assertTrue(logged_in_user.is_authenticated)
        self.assertEqual(logged_in_user.username, "alice")

    def test_posted_role_is_ignored(self):
        for role in (Role.SUPER_ADMIN, Role.ADMIN):
            with self.subTest(role=role):
                self.client.logout()
                username = f"user{role.lower().replace('_', '')}"

                self.post_sign_up(username=username, email=f"{username}@example.com", role=role)

                user = User.objects.get(username=username)
                self.assertEqual(user.role, Role.REGULAR_USER)
                self.assertFalse(user.is_staff)

    def test_invalid_data_shows_errors_and_creates_no_user(self):
        response = self.post_sign_up(username="library", password2="Different-pass-2025")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/register.html")
        self.assertContains(response, "This username is reserved.")
        self.assertContains(response, "The two password fields didn’t match.")
        self.assertFalse(User.objects.exists())
        self.assertFalse(get_user(self.client).is_authenticated)

    def test_duplicate_username_and_email_are_rejected(self):
        User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)

        response = self.post_sign_up(username="Alice", email="ALICE@example.com")

        self.assertContains(response, "A user with that username already exists.")
        self.assertContains(response, "A user with this email already exists.")
        self.assertEqual(User.objects.count(), 1)

    def test_logged_in_user_is_redirected_away(self):
        user = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        self.client.force_login(user)

        for method in (self.client.get, self.client.post):
            with self.subTest(method=method.__name__):
                response = method(self.url)

                self.assertRedirects(response, reverse("core:home"))

        self.assertEqual(User.objects.count(), 1)
