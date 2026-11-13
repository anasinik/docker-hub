from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import User
from repositories.models import Repository, Visibility

PASSWORD = "Tr1cky-pass-2025"


class RepositoryModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        cls.bob = User.objects.create_user(username="bob1", email="bob@example.com", password=PASSWORD)

    def test_defaults(self):
        repository = Repository.objects.create(owner=self.alice, name="nginx")

        self.assertEqual(repository.visibility, Visibility.PUBLIC)
        self.assertTrue(repository.is_public)
        self.assertFalse(repository.is_official)
        self.assertEqual(repository.description, "")
        self.assertIsNotNone(repository.created_at)
        self.assertIsNotNone(repository.updated_at)

    def test_registry_path_and_str(self):
        repository = Repository.objects.create(owner=self.alice, name="my-app")

        self.assertEqual(repository.registry_path, "alice/my-app")
        self.assertEqual(str(repository), "alice/my-app")

    def test_owner_reverse_relation(self):
        Repository.objects.create(owner=self.alice, name="nginx")
        Repository.objects.create(owner=self.alice, name="redis")

        self.assertQuerySetEqual(
            self.alice.repositories.values_list("name", flat=True),
            ["nginx", "redis"],
            ordered=False,
        )

    def test_name_is_unique_per_owner(self):
        Repository.objects.create(owner=self.alice, name="nginx")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Repository.objects.create(owner=self.alice, name="nginx")

    def test_same_name_allowed_for_different_owners(self):
        Repository.objects.create(owner=self.alice, name="nginx")
        Repository.objects.create(owner=self.bob, name="nginx")

        self.assertEqual(Repository.objects.filter(name="nginx").count(), 2)

    def test_valid_names(self):
        for name in ("ab", "nginx", "my-app", "my_app", "my.app", "app2", "a-b_c.d", "a" * 100):
            with self.subTest(name=name):
                Repository(owner=self.alice, name=name).full_clean()

    def test_invalid_names(self):
        invalid = (
            "a",  # too short
            "a" * 101,  # too long
            "MyApp",  # uppercase
            "my app",  # space
            "-app",  # leading separator
            "app-",  # trailing separator
            "my--app",  # consecutive separators
            "my/app",  # slash belongs to the registry path, not the name
            "app!",
        )
        for name in invalid:
            with self.subTest(name=name):
                with self.assertRaises(ValidationError) as context:
                    Repository(owner=self.alice, name=name).full_clean()
                self.assertIn("name", context.exception.message_dict)

    def test_description_max_length(self):
        Repository(owner=self.alice, name="nginx", description="a" * 100).full_clean()

        with self.assertRaises(ValidationError) as context:
            Repository(owner=self.alice, name="nginx", description="a" * 101).full_clean()
        self.assertIn("description", context.exception.message_dict)

    def test_full_clean_reports_duplicate_name(self):
        Repository.objects.create(owner=self.alice, name="nginx")

        with self.assertRaisesMessage(ValidationError, "You already have a repository with this name."):
            Repository(owner=self.alice, name="nginx").full_clean()

    def test_repositories_are_deleted_with_owner(self):
        Repository.objects.create(owner=self.alice, name="nginx")

        self.alice.delete()

        self.assertFalse(Repository.objects.exists())
