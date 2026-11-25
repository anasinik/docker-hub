import os
import stat
import sys
import tempfile
from io import StringIO
from pathlib import Path
from unittest import skipIf

from django.contrib.auth import get_user
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.forms import AccountPasswordChangeForm
from accounts.models import Role, User

PASSWORD = "Tr1cky-pass-2025"
NEW_PASSWORD = "N3w-secure-pass-2025"


class SetupSuperAdminCommandTests(TestCase):
    """``manage.py setup_super_admin``: creates the super admin on the first start."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.password_file = Path(directory.name) / "secrets" / "superadmin_password.txt"
        settings_override = override_settings(
            SUPER_ADMIN_USERNAME="superadmin",
            SUPER_ADMIN_EMAIL="superadmin@example.com",
            SUPER_ADMIN_PASSWORD_FILE=self.password_file,
        )
        settings_override.enable()
        self.addCleanup(settings_override.disable)

    def run_command(self):
        stdout = StringIO()
        call_command("setup_super_admin", stdout=stdout)
        return stdout.getvalue()

    def read_password(self):
        return self.password_file.read_text(encoding="utf-8").strip()

    def test_creates_super_admin_that_must_change_password(self):
        with self.assertLogs("accounts.management.commands.setup_super_admin", level="INFO") as logs:
            output = self.run_command()

        user = User.objects.get(role=Role.SUPER_ADMIN)
        self.assertEqual(user.username, "superadmin")
        self.assertEqual(user.email, "superadmin@example.com")
        self.assertTrue(user.password_change_required)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        self.assertIn(str(self.password_file), output)
        self.assertIn("Super admin created: username=superadmin", logs.output[0])

    def test_password_is_written_to_the_file(self):
        self.run_command()

        password = self.read_password()
        user = User.objects.get(role=Role.SUPER_ADMIN)
        self.assertGreaterEqual(len(password), 20)
        self.assertTrue(user.check_password(password))

    def test_password_is_not_printed_or_logged(self):
        with self.assertLogs("accounts.management.commands.setup_super_admin", level="INFO") as logs:
            output = self.run_command()

        password = self.read_password()
        self.assertNotIn(password, output)
        self.assertNotIn(password, "\n".join(logs.output))

    @skipIf(sys.platform == "win32", "Windows does not support POSIX file modes")
    def test_password_file_is_readable_only_by_owner(self):
        self.run_command()

        self.assertEqual(stat.S_IMODE(os.stat(self.password_file).st_mode), 0o600)

    def test_passwords_differ_between_installations(self):
        self.run_command()
        first = self.read_password()
        User.objects.filter(role=Role.SUPER_ADMIN).delete()

        self.run_command()

        self.assertNotEqual(self.read_password(), first)

    def test_running_again_changes_nothing(self):
        self.run_command()
        password = self.read_password()

        output = self.run_command()

        self.assertIn("already exists", output)
        self.assertEqual(User.objects.filter(role=Role.SUPER_ADMIN).count(), 1)
        self.assertEqual(self.read_password(), password)
        self.assertTrue(User.objects.get(role=Role.SUPER_ADMIN).check_password(password))

    def test_existing_super_admin_is_kept(self):
        User.objects.create_superuser(username="root1", email="root@example.com", password=PASSWORD)

        output = self.run_command()

        self.assertIn("Super admin already exists: root1", output)
        self.assertFalse(self.password_file.exists())

    def test_username_taken_by_another_user_is_an_error(self):
        User.objects.create_admin(username="superadmin", email="other@example.com", password=PASSWORD)

        with self.assertRaisesMessage(CommandError, "already exists and is not the super admin"):
            self.run_command()

        self.assertFalse(User.objects.filter(role=Role.SUPER_ADMIN).exists())
        self.assertFalse(self.password_file.exists())

    def test_email_taken_by_another_user_is_an_error(self):
        User.objects.create_user(username="alice", email="SuperAdmin@example.com", password=PASSWORD)

        with self.assertRaisesMessage(CommandError, "is already used"):
            self.run_command()

    def test_invalid_settings_are_errors(self):
        cases = (
            ({"SUPER_ADMIN_USERNAME": "Super-Admin"}, "SUPER_ADMIN_USERNAME"),
            ({"SUPER_ADMIN_EMAIL": "not-an-email"}, "SUPER_ADMIN_EMAIL"),
        )
        for values, message in cases:
            with self.subTest(**values), override_settings(**values):
                with self.assertRaisesMessage(CommandError, message):
                    self.run_command()

                self.assertFalse(User.objects.filter(role=Role.SUPER_ADMIN).exists())

    def test_no_account_is_created_if_the_file_cannot_be_written(self):
        # A directory in place of the file makes the write fail.
        self.password_file.mkdir(parents=True)

        with self.assertRaisesMessage(CommandError, "Cannot write the password file"):
            self.run_command()

        self.assertFalse(User.objects.filter(role=Role.SUPER_ADMIN).exists())


class PasswordChangeRequiredMiddlewareTests(TestCase):
    """Integration tests: a user who must change the password can only do that."""

    change_url = reverse("accounts:password_change")

    @classmethod
    def setUpTestData(cls):
        cls.root = User.objects.create_superuser(username="root1", email="root@example.com", password=PASSWORD)
        User.objects.filter(pk=cls.root.pk).update(password_change_required=True)

    def setUp(self):
        self.client.force_login(self.root)

    def test_pages_redirect_to_password_change(self):
        urls = (
            reverse("core:home"),
            reverse("accounts:list"),
            reverse("repository_search"),
            reverse("repositories:list"),
            "/admin/",
        )
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertRedirects(response, self.change_url, fetch_redirect_response=False)

    def test_post_requests_are_redirected_too(self):
        response = self.client.post(reverse("repositories:create"), {"name": "app"})

        self.assertRedirects(response, self.change_url, fetch_redirect_response=False)

    def test_htmx_requests_get_hx_redirect(self):
        response = self.client.get(reverse("accounts:list"), headers={"HX-Request": "true"})

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], self.change_url)

    def test_password_change_page_is_available(self):
        response = self.client.get(self.change_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/password_change.html")
        self.assertContains(response, "You signed in with the initial password")

    def test_health_check_is_available(self):
        self.assertEqual(self.client.get(reverse("core:health")).status_code, 200)

    def test_user_can_sign_out(self):
        response = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(response, reverse("core:home"), fetch_redirect_response=False)
        self.assertFalse(get_user(self.client).is_authenticated)

    def test_sign_in_leads_to_password_change(self):
        self.client.logout()

        response = self.client.post(reverse("accounts:login"), {"username": "root1", "password": PASSWORD}, follow=True)

        self.assertRedirects(response, self.change_url)
        self.assertTrue(get_user(self.client).is_authenticated)

    def test_other_users_are_not_affected(self):
        alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        self.client.force_login(alice)

        self.assertEqual(self.client.get(reverse("core:home")).status_code, 200)

    def test_anonymous_users_are_not_affected(self):
        self.client.logout()

        self.assertEqual(self.client.get(reverse("core:home")).status_code, 200)


class PasswordChangeViewTests(TestCase):
    """Integration tests for /accounts/password/."""

    url = reverse("accounts:password_change")

    @classmethod
    def setUpTestData(cls):
        cls.root = User.objects.create_superuser(username="root1", email="root@example.com", password=PASSWORD)
        User.objects.filter(pk=cls.root.pk).update(password_change_required=True)

    def setUp(self):
        self.client.force_login(self.root)

    def change_password(self, old=PASSWORD, new=NEW_PASSWORD, confirm=None):
        data = {"old_password": old, "new_password1": new, "new_password2": confirm or new}
        return self.client.post(self.url, data)

    def test_change_gives_access_to_the_system(self):
        with self.assertLogs("accounts.views", level="INFO") as logs:
            response = self.change_password()

        self.assertRedirects(response, reverse("core:home"))
        self.root.refresh_from_db()
        self.assertFalse(self.root.password_change_required)
        self.assertTrue(self.root.check_password(NEW_PASSWORD))
        self.assertIn("Password changed: username=root1", logs.output[0])
        # The session stays valid, and admin pages are no longer redirected.
        self.assertEqual(self.client.get(reverse("accounts:list")).status_code, 200)

    def test_new_password_works_for_sign_in(self):
        self.change_password()
        self.client.logout()

        response = self.client.post(reverse("accounts:login"), {"username": "root1", "password": NEW_PASSWORD})

        self.assertRedirects(response, reverse("core:home"))

    def test_wrong_current_password_is_rejected(self):
        response = self.change_password(old="Wrong-pass-2025")

        self.assertEqual(response.status_code, 200)
        self.assertIn("old_password", response.context["form"].errors)
        self.root.refresh_from_db()
        self.assertTrue(self.root.password_change_required)

    def test_same_password_is_rejected(self):
        response = self.change_password(new=PASSWORD)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["form"].errors["new_password1"],
            ["The new password must be different from the current one."],
        )
        self.root.refresh_from_db()
        self.assertTrue(self.root.password_change_required)

    def test_weak_password_is_rejected(self):
        response = self.change_password(new="12345678")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.root.refresh_from_db()
        self.assertTrue(self.root.password_change_required)

    def test_anonymous_user_is_sent_to_login(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={self.url}", fetch_redirect_response=False)

    def test_regular_user_can_change_password(self):
        alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        self.client.force_login(alice)

        response = self.change_password()

        self.assertRedirects(response, reverse("core:home"))
        alice.refresh_from_db()
        self.assertTrue(alice.check_password(NEW_PASSWORD))


class AccountPasswordChangeFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)

    def make_form(self, new=NEW_PASSWORD):
        return AccountPasswordChangeForm(
            self.user, data={"old_password": PASSWORD, "new_password1": new, "new_password2": new}
        )

    def test_save_clears_password_change_required(self):
        self.user.password_change_required = True
        form = self.make_form()

        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        self.user.refresh_from_db()
        self.assertFalse(self.user.password_change_required)
        self.assertTrue(self.user.check_password(NEW_PASSWORD))

    def test_new_password_must_differ(self):
        form = self.make_form(new=PASSWORD)

        self.assertFalse(form.is_valid())
        self.assertIn("new_password1", form.errors)
