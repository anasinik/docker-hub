from django.contrib.auth import get_user
from django.test import TestCase
from django.urls import reverse

from accounts.forms import AdminRegistrationForm
from accounts.models import Role, User

PASSWORD = "Tr1cky-pass-2025"
INITIAL_PASSWORD = "Init1al-pass-2025"
NEW_PASSWORD = "N3w-secure-pass-2025"


def registration_data(**overrides):
    data = {
        "username": "admin2",
        "email": "admin2@example.com",
        "password1": INITIAL_PASSWORD,
        "password2": INITIAL_PASSWORD,
    }
    data.update(overrides)
    return data


class AdminRegistrationFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)

    def test_creates_admin_who_must_change_password(self):
        form = AdminRegistrationForm(data=registration_data())

        self.assertTrue(form.is_valid(), form.errors)
        admin = form.save()

        admin.refresh_from_db()
        self.assertEqual(admin.role, Role.ADMIN)
        self.assertTrue(admin.is_staff)
        self.assertFalse(admin.is_superuser)
        self.assertTrue(admin.password_change_required)
        self.assertTrue(admin.check_password(INITIAL_PASSWORD))

    def test_posted_role_is_ignored(self):
        form = AdminRegistrationForm(data=registration_data(role=Role.SUPER_ADMIN))

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().role, Role.ADMIN)

    def test_username_and_email_are_lowercased(self):
        form = AdminRegistrationForm(data=registration_data(username=" Admin2 ", email="Admin2@Example.com"))

        self.assertTrue(form.is_valid(), form.errors)
        admin = form.save()
        self.assertEqual(admin.username, "admin2")
        self.assertEqual(admin.email, "admin2@example.com")

    def test_reserved_usernames_are_allowed(self):
        form = AdminRegistrationForm(data=registration_data(username="support"))

        self.assertTrue(form.is_valid(), form.errors)

    def test_taken_username_and_email_are_rejected(self):
        cases = ({"username": "ALICE"}, {"email": "Alice@Example.com"})
        for overrides in cases:
            with self.subTest(**overrides):
                form = AdminRegistrationForm(data=registration_data(**overrides))

                self.assertFalse(form.is_valid())
                self.assertIn(next(iter(overrides)), form.errors)

    def test_invalid_username_is_rejected(self):
        form = AdminRegistrationForm(data=registration_data(username="ad"))

        self.assertFalse(form.is_valid())
        self.assertIn("username", form.errors)

    def test_password_rules_apply(self):
        cases = (
            {"password1": "12345678", "password2": "12345678"},
            {"password2": "Different-pass-2025"},
        )
        for overrides in cases:
            with self.subTest(**overrides):
                form = AdminRegistrationForm(data=registration_data(**overrides))

                self.assertFalse(form.is_valid())
                self.assertIn("password2", form.errors)


class AdminRegistrationAccessTests(TestCase):
    """Only the super admin may list and register administrators."""

    urls = (reverse("accounts:admin_list"), reverse("accounts:admin_create"))

    @classmethod
    def setUpTestData(cls):
        cls.root = User.objects.create_superuser(username="root1", email="root@example.com", password=PASSWORD)
        cls.admin = User.objects.create_admin(username="admin1", email="admin1@example.com", password=PASSWORD)
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)

    def test_anonymous_user_is_sent_to_login(self):
        for url in self.urls:
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}", fetch_redirect_response=False)

    def test_admins_and_regular_users_get_403(self):
        for user in (self.admin, self.alice):
            self.client.force_login(user)
            for url in self.urls:
                with self.subTest(role=user.role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_admin_cannot_register_an_admin(self):
        self.client.force_login(self.admin)

        response = self.client.post(reverse("accounts:admin_create"), registration_data())

        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="admin2").exists())

    def test_super_admin_has_access(self):
        self.client.force_login(self.root)
        for url in self.urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_header_link_is_shown_to_super_admin_only(self):
        link = f'href="{reverse("accounts:admin_list")}"'
        for user, visible in ((self.root, True), (self.admin, False), (self.alice, False)):
            with self.subTest(role=user.role):
                self.client.force_login(user)

                response = self.client.get(reverse("core:home"))

                if visible:
                    self.assertContains(response, link)
                else:
                    self.assertNotContains(response, link)


class AdminCreateViewTests(TestCase):
    """Integration tests for /accounts/admins/new/."""

    url = reverse("accounts:admin_create")

    @classmethod
    def setUpTestData(cls):
        cls.root = User.objects.create_superuser(username="root1", email="root@example.com", password=PASSWORD)

    def setUp(self):
        self.client.force_login(self.root)

    def test_form_renders(self):
        response = self.client.get(self.url)

        self.assertTemplateUsed(response, "accounts/admin_form.html")
        for name in ("username", "email", "password1", "password2"):
            self.assertContains(response, f'name="{name}"')
        self.assertNotContains(response, 'name="role"')

    def test_registers_admin_and_redirects_to_list(self):
        with self.assertLogs("accounts.views", level="INFO") as logs:
            response = self.client.post(self.url, registration_data(), follow=True)

        self.assertRedirects(response, reverse("accounts:admin_list"))
        admin = User.objects.get(username="admin2")
        self.assertEqual(admin.role, Role.ADMIN)
        self.assertTrue(admin.password_change_required)
        self.assertContains(response, "Administrator admin2 has been registered.")
        self.assertIn("Admin registered: username=admin2", logs.output[0])
        self.assertIn("by=root1", logs.output[0])
        self.assertNotIn(INITIAL_PASSWORD, "\n".join(logs.output))

    def test_super_admin_stays_signed_in(self):
        self.client.post(self.url, registration_data())

        self.assertEqual(get_user(self.client).pk, self.root.pk)

    def test_invalid_data_shows_errors(self):
        response = self.client.post(self.url, registration_data(email="not-an-email"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.assertFalse(User.objects.filter(username="admin2").exists())

    def test_new_admin_must_change_password_then_has_admin_access(self):
        self.client.post(self.url, registration_data())
        self.client.logout()

        response = self.client.post(
            reverse("accounts:login"), {"username": "admin2", "password": INITIAL_PASSWORD}, follow=True
        )
        self.assertRedirects(response, reverse("accounts:password_change"))
        self.assertRedirects(
            self.client.get(reverse("accounts:list")), reverse("accounts:password_change"), fetch_redirect_response=False
        )

        self.client.post(
            reverse("accounts:password_change"),
            {"old_password": INITIAL_PASSWORD, "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
        )

        self.assertEqual(self.client.get(reverse("accounts:list")).status_code, 200)
        # Admins still cannot register admins.
        self.assertEqual(self.client.get(self.url).status_code, 403)


class AdminListViewTests(TestCase):
    """Integration tests for /accounts/admins/."""

    url = reverse("accounts:admin_list")

    @classmethod
    def setUpTestData(cls):
        cls.root = User.objects.create_superuser(username="root1", email="root@example.com", password=PASSWORD)
        cls.admin = User.objects.create_admin(username="admin1", email="admin1@example.com", password=PASSWORD)
        cls.pending = User.objects.create_admin(
            username="admin2", email="admin2@example.com", password=PASSWORD, password_change_required=True
        )
        User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)

    def setUp(self):
        self.client.force_login(self.root)

    def test_lists_admins_only_newest_first(self):
        response = self.client.get(self.url)

        self.assertTemplateUsed(response, "accounts/admin_list.html")
        self.assertEqual(list(response.context["admins"]), [self.pending, self.admin])
        self.assertContains(response, f'href="{reverse("accounts:admin_create")}"')

    def test_pending_password_change_is_shown(self):
        response = self.client.get(self.url)

        self.assertContains(response, "Initial password not changed", count=1)

    def test_empty_list(self):
        User.objects.filter(role=Role.ADMIN).delete()

        response = self.client.get(self.url)

        self.assertContains(response, "No administrators yet.")

    def test_list_is_paginated(self):
        User.objects.bulk_create(
            User(username=f"extra{i:02d}", email=f"extra{i}@example.com", role=Role.ADMIN, is_staff=True)
            for i in range(12)
        )

        first = self.client.get(self.url)
        second = self.client.get(self.url, {"page": 2})

        self.assertEqual(len(first.context["admins"]), 12)
        self.assertEqual(len(second.context["admins"]), 2)

    def test_htmx_request_gets_partial(self):
        response = self.client.get(self.url, headers={"HX-Request": "true"})

        self.assertTemplateUsed(response, "accounts/partials/admin_list_content.html")
        self.assertTemplateNotUsed(response, "accounts/admin_list.html")
