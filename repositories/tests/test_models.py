from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.aggregates import Count
from django.test import TestCase

from accounts.models import User
from repositories.models import Repository, RepositoryStar, Visibility

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

    def test_official_repository_path_has_no_owner_prefix(self):
        repository = Repository.objects.create(owner=self.alice, name="nginx", is_official=True)

        self.assertEqual(repository.registry_path, "nginx")
        self.assertEqual(str(repository), "nginx")

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


class RepositoryStarModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        cls.bob = User.objects.create_user(username="bob1", email="bob@example.com", password=PASSWORD)
        cls.carol = User.objects.create_user(username="carol", email="carol@example.com", password=PASSWORD)

        cls.repository = Repository.objects.create(owner=cls.alice, name="nginx")

    def test_create_star(self):
        star = RepositoryStar.objects.create(repository=self.repository, user=self.bob)

        self.assertEqual(star.repository, self.repository)
        self.assertEqual(star.user, self.bob)
        self.assertIsNotNone(star.created_at)

    def test_user_can_star_repository_only_once(self):
        RepositoryStar.objects.create(repository=self.repository, user=self.bob)

        with self.assertRaises(IntegrityError), transaction.atomic():
            RepositoryStar.objects.create(repository=self.repository, user=self.bob)

    def test_repository_starred_by_relation(self):
        RepositoryStar.objects.create(repository=self.repository, user=self.bob)
        RepositoryStar.objects.create(repository=self.repository, user=self.carol)

        self.assertQuerySetEqual(
            self.repository.starred_by.values_list("username", flat=True),
            ["bob1", "carol"],
            ordered=False,
        )

    def test_user_starred_repositories_relation(self):
        RepositoryStar.objects.create(repository=self.repository, user=self.bob)

        self.assertQuerySetEqual(
            self.bob.starred_repositories.values_list("pk", flat=True),
            [self.repository.pk],
        )

    def test_stars_are_deleted_with_repository(self):
        RepositoryStar.objects.create(repository=self.repository, user=self.bob)

        self.repository.delete()

        self.assertFalse(RepositoryStar.objects.exists())

    def test_stars_are_deleted_with_user(self):
        RepositoryStar.objects.create(repository=self.repository, user=self.bob)

        self.bob.delete()

        self.assertFalse(RepositoryStar.objects.exists())

    def test_star_count_annotation(self):
        RepositoryStar.objects.create(repository=self.repository, user=self.bob)
        RepositoryStar.objects.create(repository=self.repository, user=self.carol)

        repository = (
            Repository.objects
            .annotate(star_count=Count("starred_by", distinct=True))
            .get(pk=self.repository.pk)
        )

        self.assertEqual(repository.star_count, 2)