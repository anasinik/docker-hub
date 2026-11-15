from django.test import TestCase

from accounts.models import User
from repositories.forms import RepositoryForm, RepositorySettingsForm
from repositories.models import Repository, Visibility

PASSWORD = "Tr1cky-pass-2025"


class RepositoryFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        cls.bob = User.objects.create_user(username="bob1", email="bob@example.com", password=PASSWORD)

    def make_form(self, owner=None, **overrides):
        data = {"name": "nginx", "description": "Web server", "visibility": Visibility.PUBLIC}
        data.update(overrides)
        return RepositoryForm(data=data, owner=owner or self.alice)

    def test_valid_form_creates_repository_for_owner(self):
        form = self.make_form(visibility=Visibility.PRIVATE)

        self.assertTrue(form.is_valid(), form.errors)
        repository = form.save()
        self.assertEqual(repository.owner, self.alice)
        self.assertEqual(repository.name, "nginx")
        self.assertEqual(repository.description, "Web server")
        self.assertEqual(repository.visibility, Visibility.PRIVATE)

    def test_form_has_no_owner_or_official_field(self):
        form = self.make_form()

        self.assertEqual(list(form.fields), ["name", "description", "visibility"])

    def test_posted_owner_and_official_flag_are_ignored(self):
        data = {"name": "nginx", "visibility": Visibility.PUBLIC, "owner": self.bob.pk, "is_official": "on"}
        form = RepositoryForm(data=data, owner=self.alice)

        self.assertTrue(form.is_valid(), form.errors)
        repository = form.save()
        self.assertEqual(repository.owner, self.alice)
        self.assertFalse(repository.is_official)

    def test_name_is_lowercased(self):
        form = self.make_form(name="  My-App ")

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["name"], "my-app")

    def test_invalid_name(self):
        form = self.make_form(name="my app")

        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)

    def test_description_is_optional(self):
        form = self.make_form(description="")

        self.assertTrue(form.is_valid(), form.errors)

    def test_description_is_limited_to_100_characters(self):
        self.assertTrue(self.make_form(description="a" * 100).is_valid())

        form = self.make_form(description="a" * 101)

        self.assertFalse(form.is_valid())
        self.assertIn("description", form.errors)

    def test_name_and_visibility_are_required(self):
        form = self.make_form(name="", visibility="")

        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)
        self.assertIn("visibility", form.errors)

    def test_unknown_visibility_is_rejected(self):
        form = self.make_form(visibility="SECRET")

        self.assertFalse(form.is_valid())
        self.assertIn("visibility", form.errors)

    def test_duplicate_name_for_same_owner_is_rejected(self):
        Repository.objects.create(owner=self.alice, name="nginx")

        form = self.make_form(name="NGINX")

        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors["name"], ["You already have a repository with this name."])

    def test_same_name_for_different_owner_is_allowed(self):
        Repository.objects.create(owner=self.bob, name="nginx")

        form = self.make_form()

        self.assertTrue(form.is_valid(), form.errors)


class RepositorySettingsFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)

    def setUp(self):
        self.repository = Repository.objects.create(owner=self.alice, name="nginx", description="Web server")

    def make_form(self, **overrides):
        data = {"description": "Reverse proxy", "visibility": Visibility.PRIVATE}
        data.update(overrides)
        return RepositorySettingsForm(data=data, instance=self.repository)

    def test_form_has_only_description_and_visibility(self):
        form = RepositorySettingsForm(instance=self.repository)

        self.assertEqual(list(form.fields), ["description", "visibility"])

    def test_valid_form_updates_description_and_visibility(self):
        form = self.make_form()

        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.repository.refresh_from_db()
        self.assertEqual(self.repository.description, "Reverse proxy")
        self.assertEqual(self.repository.visibility, Visibility.PRIVATE)

    def test_posted_name_owner_and_official_flag_are_ignored(self):
        bob = User.objects.create_user(username="bob1", email="bob@example.com", password=PASSWORD)
        form = self.make_form(name="renamed", owner=bob.pk, is_official="on")

        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.repository.refresh_from_db()
        self.assertEqual(self.repository.name, "nginx")
        self.assertEqual(self.repository.owner, self.alice)
        self.assertFalse(self.repository.is_official)

    def test_description_can_be_cleared(self):
        form = self.make_form(description="")

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().description, "")

    def test_description_is_limited_to_100_characters(self):
        self.assertTrue(self.make_form(description="a" * 100).is_valid())

        form = self.make_form(description="a" * 101)

        self.assertFalse(form.is_valid())
        self.assertIn("description", form.errors)

    def test_visibility_is_required_and_validated(self):
        for value in ("", "SECRET"):
            with self.subTest(visibility=value):
                form = self.make_form(visibility=value)

                self.assertFalse(form.is_valid())
                self.assertIn("visibility", form.errors)
