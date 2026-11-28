from django.contrib.auth import get_user
from django.test import TestCase
from django.urls import reverse

from accounts.forms import LoginForm
from accounts.models import User

PASSWORD = "Tr1cky-pass-2025"
INVALID_LOGIN = "Incorrect username/email or password."


class LoginFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)

    def make_form(self, username, password=PASSWORD):
        return LoginForm(data={"username": username, "password": password})

    def assert_logs_in_alice(self, identifier):
        form = self.make_form(identifier)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.get_user(), self.alice)

    def assert_invalid_login(self, form):
        self.assertFalse(form.is_valid())
        self.assertEqual(form.non_field_errors(), [INVALID_LOGIN])

    def test_login_with_username(self):
        self.assert_logs_in_alice("alice")

    def test_username_ignores_case_and_whitespace(self):
        self.assert_logs_in_alice("  Alice ")

    def test_login_with_email(self):
        self.assert_logs_in_alice("alice@example.com")

    def test_email_ignores_case_and_whitespace(self):
        self.assert_logs_in_alice(" ALICE@Example.com ")

    def test_long_email_is_accepted(self):
        email = f"{'a' * 40}@example.com"
        user = User.objects.create_user(username="longmail", email=email, password=PASSWORD)

        form = self.make_form(email)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.get_user(), user)

    def test_wrong_password(self):
        self.assert_invalid_login(self.make_form("alice", "Wrong-pass-2025"))

    def test_unknown_username_and_email_get_the_same_error(self):
        for identifier in ("nobody", "nobody@example.com"):
            with self.subTest(identifier=identifier):
                self.assert_invalid_login(self.make_form(identifier))

    def test_inactive_user_cannot_log_in(self):
        User.objects.filter(pk=self.alice.pk).update(is_active=False)

        self.assert_invalid_login(self.make_form("alice"))

    def test_required_fields(self):
        form = LoginForm(data={})

        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)
        self.assertIn("password", form.errors)


class LoginViewTests(TestCase):
    """Integration tests for signing in, using the test client."""

    url = reverse("accounts:login")

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)

    def post_login(self, username="alice", password=PASSWORD, url=None, **extra):
        return self.client.post(url or self.url, {"username": username, "password": password, **extra}, follow=True)

    def assert_logged_in_as(self, user):
        logged_in_user = get_user(self.client)
        self.assertTrue(logged_in_user.is_authenticated)
        self.assertEqual(logged_in_user.pk, user.pk)

    def test_login_page_renders(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/login.html")
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')
        self.assertContains(response, f'href="{reverse("accounts:register")}"')

    def test_successful_login_redirects_home(self):
        response = self.post_login()

        self.assertRedirects(response, reverse("core:home"))
        self.assert_logged_in_as(self.alice)

    def test_login_with_email(self):
        self.post_login(username="alice@example.com")

        self.assert_logged_in_as(self.alice)

    def test_admins_sign_in_on_the_same_page(self):
        admins = (
            User.objects.create_admin(username="admin1", email="admin@example.com", password=PASSWORD),
            User.objects.create_superuser(username="root1", email="root@example.com", password=PASSWORD),
        )
        for admin in admins:
            with self.subTest(role=admin.role):
                self.client.logout()

                self.post_login(username=admin.username)

                self.assert_logged_in_as(admin)

    def test_invalid_credentials_show_error_and_do_not_log_in(self):
        response = self.post_login(password="Wrong-pass-2025")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/login.html")
        self.assertContains(response, INVALID_LOGIN)
        self.assertFalse(get_user(self.client).is_authenticated)

    def test_redirects_to_safe_next_url(self):
        next_url = reverse("repositories:create")

        response = self.post_login(url=f"{self.url}?next={next_url}")

        self.assertRedirects(response, next_url)

    def test_next_url_is_kept_in_the_form(self):
        next_url = reverse("repositories:create")

        response = self.client.get(f"{self.url}?next={next_url}")

        self.assertContains(response, f'name="next" value="{next_url}"')

    def test_external_next_url_is_ignored(self):
        response = self.post_login(next="https://evil.example.com/")

        self.assertRedirects(response, reverse("core:home"))

    def test_protected_page_sends_visitor_back_after_login(self):
        protected_url = reverse("repositories:create")

        response = self.client.get(protected_url)
        self.assertRedirects(response, f"{self.url}?next={protected_url}")

        response = self.post_login(url=response.url)
        self.assertRedirects(response, protected_url)

    def test_logged_in_user_is_redirected_away(self):
        self.client.force_login(self.alice)

        response = self.client.get(self.url)

        self.assertRedirects(response, reverse("core:home"))

    def test_sign_up_page_links_to_login(self):
        response = self.client.get(reverse("accounts:register"))

        self.assertContains(response, f'href="{self.url}"')


class LogoutViewTests(TestCase):
    url = reverse("accounts:logout")

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)

    def test_logout_signs_out_and_redirects_home(self):
        self.client.force_login(self.alice)

        response = self.client.post(self.url, follow=True)

        self.assertRedirects(response, reverse("core:home"))
        self.assertFalse(get_user(self.client).is_authenticated)
        self.assertContains(response, "You have been signed out.")

    def test_logout_requires_post(self):
        self.client.force_login(self.alice)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 405)
        self.assertTrue(get_user(self.client).is_authenticated)

    def test_logout_when_not_logged_in(self):
        response = self.client.post(self.url, follow=True)

        self.assertRedirects(response, reverse("core:home"))
        self.assertNotContains(response, "You have been signed out.")

    def test_protected_page_needs_login_again_after_logout(self):
        self.client.force_login(self.alice)
        self.client.post(self.url)

        response = self.client.get(reverse("repositories:create"))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("accounts:login")))


class HeaderTests(TestCase):
    login_url = reverse("accounts:login")
    logout_url = reverse("accounts:logout")

    def test_visitor_sees_sign_in_and_sign_up(self):
        response = self.client.get(reverse("core:home"))

        self.assertContains(response, f'href="{self.login_url}"')
        self.assertContains(response, f'href="{reverse("accounts:register")}"')
        self.assertNotContains(response, f'action="{self.logout_url}"')

    def test_sign_in_link_returns_to_current_page(self):
        search_url = reverse("repository_search")

        response = self.client.get(search_url, {"q": "nginx"})

        self.assertContains(response, f'href="{self.login_url}?next={search_url}%3Fq%3Dnginx"')

    def test_sign_in_link_on_account_pages_has_no_next(self):
        for name in ("accounts:login", "accounts:register"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))

                self.assertContains(response, f'href="{self.login_url}"')
                self.assertNotContains(response, f'href="{self.login_url}?next=')

    def test_logged_in_user_sees_username_and_sign_out(self):
        user = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        self.client.force_login(user)

        response = self.client.get(reverse("core:home"))

        self.assertContains(
            response, f'<a href="{reverse("accounts:profile")}" title="Your profile">alice</a>', html=True
        )
        self.assertContains(response, f'action="{self.logout_url}"')
        self.assertNotContains(response, f'href="{self.login_url}')


class AuthenticationLoggingTests(TestCase):
    logger_name = "accounts.signals"

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)

    def test_successful_login_is_logged(self):
        with self.assertLogs(self.logger_name, level="INFO") as logs:
            self.client.post(reverse("accounts:login"), {"username": "alice", "password": PASSWORD})

        self.assertEqual(len(logs.records), 1)
        self.assertEqual(logs.records[0].levelname, "INFO")
        self.assertIn(f"User logged in: username=alice id={self.alice.pk} ip=127.0.0.1", logs.output[0])

    def test_failed_login_is_logged_as_warning_without_password(self):
        with self.assertLogs(self.logger_name, level="INFO") as logs:
            self.client.post(reverse("accounts:login"), {"username": "alice", "password": "Wrong-pass-2025"})

        self.assertEqual(logs.records[0].levelname, "WARNING")
        self.assertIn("Login failed: username='alice' ip=127.0.0.1", logs.output[0])
        self.assertNotIn("Wrong-pass-2025", logs.output[0])

    def test_failed_login_username_cannot_forge_log_lines(self):
        with self.assertLogs(self.logger_name, level="INFO") as logs:
            self.client.post(
                reverse("accounts:login"),
                {"username": "nobody\nUser logged in: username=root", "password": PASSWORD},
            )

        self.assertNotIn("\n", logs.output[0])

    def test_logout_is_logged(self):
        self.client.force_login(self.alice)

        with self.assertLogs(self.logger_name, level="INFO") as logs:
            self.client.post(reverse("accounts:logout"))

        self.assertIn(f"User logged out: username=alice id={self.alice.pk}", logs.output[0])
