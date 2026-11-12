from django.test import TestCase

from accounts.forms import SignUpForm
from accounts.models import Role, User

PASSWORD = "Tr1cky-pass-2025"


def form_data(**overrides):
    data = {
        "username": "alice",
        "email": "alice@example.com",
        "password1": PASSWORD,
        "password2": PASSWORD,
    }
    data.update(overrides)
    return data


class SignUpFormTests(TestCase):
    def test_valid_form_creates_regular_user(self):
        form = SignUpForm(data=form_data())

        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.username, "alice")
        self.assertEqual(user.email, "alice@example.com")
        self.assertEqual(user.role, Role.REGULAR_USER)
        self.assertTrue(user.check_password(PASSWORD))

    def test_form_has_no_role_field(self):
        self.assertNotIn("role", SignUpForm().fields)

    def test_role_in_data_is_ignored(self):
        form = SignUpForm(data=form_data(role=Role.SUPER_ADMIN))

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().role, Role.REGULAR_USER)

    def test_username_and_email_are_lowercased(self):
        form = SignUpForm(data=form_data(username="  Alice ", email="Alice@Example.COM"))

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["username"], "alice")
        self.assertEqual(form.cleaned_data["email"], "alice@example.com")

    def test_invalid_username_format(self):
        for username in ("abc", "alice.smith", "alice_smith", "a" * 31):
            with self.subTest(username=username):
                form = SignUpForm(data=form_data(username=username))

                self.assertFalse(form.is_valid())
                self.assertIn("username", form.errors)

    def test_reserved_username(self):
        for username in ("library", "admin", "Official"):
            with self.subTest(username=username):
                form = SignUpForm(data=form_data(username=username))

                self.assertFalse(form.is_valid())
                self.assertEqual(form.errors["username"], ["This username is reserved."])

    def test_duplicate_username(self):
        User.objects.create_user(username="alice", email="other@example.com", password=PASSWORD)

        form = SignUpForm(data=form_data(username="ALICE"))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["username"], ["A user with that username already exists."])

    def test_duplicate_email(self):
        User.objects.create_user(username="other", email="alice@example.com", password=PASSWORD)

        form = SignUpForm(data=form_data(email="ALICE@example.com"))

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["email"], ["A user with this email already exists."])

    def test_required_fields(self):
        form = SignUpForm(data={})

        self.assertFalse(form.is_valid())
        for field in ("username", "email", "password1", "password2"):
            with self.subTest(field=field):
                self.assertIn(field, form.errors)

    def test_invalid_email(self):
        form = SignUpForm(data=form_data(email="not-an-email"))

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_password_mismatch(self):
        form = SignUpForm(data=form_data(password2="Different-pass-2025"))

        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)

    def test_weak_passwords(self):
        for password in ("short1", "12345678901", "password123", "alice@example.com"):
            with self.subTest(password=password):
                form = SignUpForm(data=form_data(password1=password, password2=password))

                self.assertFalse(form.is_valid())
                self.assertIn("password2", form.errors)
