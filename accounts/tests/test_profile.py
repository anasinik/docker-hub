from django.test import TestCase
from django.urls import reverse

from accounts.forms import ProfileForm
from accounts.models import Badge, Role, User

PASSWORD = "Tr1cky-pass-2025"


class ProfileFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        User.objects.create_user(username="bob1", email="bob@example.com", password=PASSWORD)

    def make_form(self, **data):
        values = {"first_name": "Alice", "last_name": "Smith", "email": "alice@example.com", **data}
        return ProfileForm(data=values, instance=self.alice)

    def test_has_only_name_and_email(self):
        self.assertEqual(list(ProfileForm().fields), ["first_name", "last_name", "email"])

    def test_email_is_lowercased_and_stripped(self):
        form = self.make_form(email="  Alice.New@Example.COM ")

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["email"], "alice.new@example.com")

    def test_own_email_is_accepted(self):
        form = self.make_form(email="ALICE@example.com")

        self.assertTrue(form.is_valid(), form.errors)

    def test_email_of_another_user_is_rejected(self):
        form = self.make_form(email="Bob@Example.com")

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["email"], ["A user with this email already exists."])

    def test_email_is_required_and_validated(self):
        for email in ("", "not-an-email"):
            with self.subTest(email=email):
                self.assertIn("email", self.make_form(email=email).errors)

    def test_names_are_optional(self):
        form = self.make_form(first_name="", last_name="")

        self.assertTrue(form.is_valid(), form.errors)

    def test_names_have_a_maximum_length(self):
        form = self.make_form(first_name="a" * 151)

        self.assertIn("first_name", form.errors)


class ProfileViewTests(TestCase):
    """Integration tests for /accounts/profile/."""

    url = reverse("accounts:profile")

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(
            username="alice",
            email="alice@example.com",
            password=PASSWORD,
            first_name="Alice",
            last_name="Smith",
            badge=Badge.VERIFIED_PUBLISHER,
        )
        cls.admin = User.objects.create_admin(username="admin1", email="admin1@example.com", password=PASSWORD)

    def test_anonymous_user_is_sent_to_login(self):
        response = self.client.get(self.url)

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={self.url}", fetch_redirect_response=False)

    def test_regular_user_sees_own_profile(self):
        self.client.force_login(self.alice)

        response = self.client.get(self.url)

        self.assertTemplateUsed(response, "accounts/profile.html")
        for text in ("alice", "Alice Smith", "alice@example.com", "Regular user", "Verified Publisher"):
            self.assertContains(response, text)
        self.assertContains(response, f'href="{reverse("accounts:profile_edit")}"')
        self.assertContains(response, f'href="{reverse("accounts:password_change")}"')

    def test_missing_name_is_shown_as_not_set(self):
        self.client.force_login(self.admin)

        response = self.client.get(self.url)

        self.assertContains(response, "Not set")

    def test_admin_sees_role_but_no_badge(self):
        self.client.force_login(self.admin)

        response = self.client.get(self.url)

        self.assertContains(response, "admin1@example.com")
        self.assertContains(response, "Admin")
        self.assertNotContains(response, "Publisher badge")

    def test_super_admin_has_a_profile(self):
        root = User.objects.create_superuser(username="root1", email="root@example.com", password=PASSWORD)
        self.client.force_login(root)

        response = self.client.get(self.url)

        self.assertContains(response, "Super admin")

    def test_header_links_to_profile(self):
        self.client.force_login(self.alice)

        response = self.client.get(reverse("core:home"))

        self.assertContains(response, f'href="{self.url}"')

    def test_user_who_must_change_password_is_redirected(self):
        User.objects.filter(pk=self.admin.pk).update(password_change_required=True)
        self.client.force_login(self.admin)

        for url in (self.url, reverse("accounts:profile_edit")):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertRedirects(response, reverse("accounts:password_change"), fetch_redirect_response=False)


class ProfileUpdateViewTests(TestCase):
    """Integration tests for /accounts/profile/edit/."""

    url = reverse("accounts:profile_edit")

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        cls.bob = User.objects.create_user(username="bob1", email="bob@example.com", password=PASSWORD)

    def setUp(self):
        self.client.force_login(self.alice)

    def post_profile(self, **data):
        values = {"first_name": "Alice", "last_name": "Smith", "email": "alice@example.com", **data}
        return self.client.post(self.url, values)

    def test_anonymous_user_is_sent_to_login(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={self.url}", fetch_redirect_response=False)

    def test_form_shows_current_values(self):
        User.objects.filter(pk=self.alice.pk).update(first_name="Alice")

        response = self.client.get(self.url)

        self.assertTemplateUsed(response, "accounts/profile_form.html")
        self.assertContains(response, 'value="Alice"')
        self.assertContains(response, 'value="alice@example.com"')
        self.assertNotContains(response, 'name="username"')

    def test_update_saves_and_redirects_to_profile(self):
        with self.assertLogs("accounts.views", level="INFO") as logs:
            response = self.post_profile(email="alice.new@example.com")

        self.assertRedirects(response, reverse("accounts:profile"), fetch_redirect_response=False)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.first_name, "Alice")
        self.assertEqual(self.alice.last_name, "Smith")
        self.assertEqual(self.alice.email, "alice.new@example.com")
        self.assertIn("Profile updated: username=alice", logs.output[0])
        self.assertIn("fields=first_name,last_name,email", logs.output[0])

        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "Your profile has been updated.")
        self.assertContains(response, "alice.new@example.com")

    def test_new_email_works_for_sign_in(self):
        self.post_profile(email="alice.new@example.com")
        self.client.logout()

        response = self.client.post(
            reverse("accounts:login"), {"username": "alice.new@example.com", "password": PASSWORD}
        )

        self.assertRedirects(response, reverse("core:home"))

    def test_nothing_changed(self):
        User.objects.filter(pk=self.alice.pk).update(first_name="Alice", last_name="Smith")

        with self.assertNoLogs("accounts.views", level="INFO"):
            response = self.post_profile()

        self.assertRedirects(response, reverse("accounts:profile"), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse("accounts:profile")), "Nothing was changed.")

    def test_email_of_another_user_shows_error_and_changes_nothing(self):
        response = self.post_profile(first_name="Changed", email="bob@example.com")

        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.email, "alice@example.com")
        self.assertEqual(self.alice.first_name, "")
        # The header still shows the saved user, not the rejected values.
        self.assertEqual(response.context["user"].email, "alice@example.com")

    def test_username_role_and_badge_cannot_be_changed(self):
        self.post_profile(username="mallory", role=Role.SUPER_ADMIN, badge=Badge.SPONSORED_OSS, is_staff="on")

        self.alice.refresh_from_db()
        self.assertEqual(self.alice.username, "alice")
        self.assertEqual(self.alice.role, Role.REGULAR_USER)
        self.assertEqual(self.alice.badge, Badge.NONE)
        self.assertFalse(self.alice.is_staff)

    def test_only_own_profile_is_edited(self):
        self.post_profile(email="alice.new@example.com", pk=self.bob.pk, id=self.bob.pk)

        self.bob.refresh_from_db()
        self.assertEqual(self.bob.email, "bob@example.com")
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.email, "alice.new@example.com")

    def test_user_stays_signed_in(self):
        self.post_profile(email="alice.new@example.com")

        self.assertEqual(self.client.get(reverse("accounts:profile")).status_code, 200)
