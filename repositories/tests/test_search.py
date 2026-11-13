from django.test import TestCase
from django.urls import reverse

from accounts.models import Badge, User
from repositories.models import Repository, RepositoryStar, Visibility

PASSWORD = "Tr1cky-pass-2026"


class RepositorySearchViewTests(TestCase):
    """Integration tests for repository search and relevance ranking."""

    url = reverse("repository_search")

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        cls.bob = User.objects.create_user(username="bob1", email="bob@example.com", password=PASSWORD)
        cls.carol = User.objects.create_user(username="carol", email="carol@example.com", password=PASSWORD)
        cls.david = User.objects.create_user(username="david", email="david@example.com", password=PASSWORD)
        cls.nginxteam = User.objects.create_user(username="nginxteam",email="nginxteam@example.com",password=PASSWORD)

        cls.voters = [
            User.objects.create_user(username=f"voter{i}", email=f"voter{i}@example.com", password=PASSWORD)
            for i in range(1, 5)
        ]

        cls.exact_match = Repository.objects.create(owner=cls.alice, name="nginx")
        cls.prefix_match = Repository.objects.create(owner=cls.bob, name="nginx-proxy")
        cls.contains_match = Repository.objects.create(owner=cls.carol, name="my-nginx")
        cls.owner_match = Repository.objects.create(owner=cls.nginxteam, name="webapp")
        cls.description_match = Repository.objects.create(owner=cls.david, name="api", description="Reverse proxy using nginx.")

        cls.private_repository = Repository.objects.create(owner=cls.alice, name="private-app", visibility=Visibility.PRIVATE)

    def get_result_ids(self, response):
        """Return repository IDs from the current result page."""
        page = response.context["page_obj"]
        return list(page.object_list.values_list("pk", flat=True))

    def add_stars(self, repository, count):
        for user in self.voters[:count]:
            RepositoryStar.objects.create(repository=repository, user=user)

    def test_search_page_renders(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "repositories/repository_search.html")

    def test_only_public_repositories_are_returned(self):
        response = self.client.get(self.url)

        result_ids = self.get_result_ids(response)

        self.assertIn(self.exact_match.pk, result_ids)
        self.assertNotIn(self.private_repository.pk, result_ids)

    def test_search_matches_repository_name_description_and_owner(self):
        response = self.client.get(self.url, {"q": "nginx"})

        result_ids = self.get_result_ids(response)

        self.assertEqual(
            result_ids,
            [
                self.exact_match.pk,
                self.prefix_match.pk,
                self.contains_match.pk,
                self.owner_match.pk,
                self.description_match.pk,
            ],
        )

    def test_text_relevance_takes_priority_over_star_count(self):
        self.add_stars(self.description_match, 4)

        response = self.client.get(self.url, {"q": "nginx"})

        result_ids = self.get_result_ids(response)

        self.assertEqual(result_ids[0], self.exact_match.pk)
        self.assertEqual(result_ids[-1], self.description_match.pk)

    def test_star_count_breaks_equal_text_relevance(self):
        first = Repository.objects.create(owner=self.alice, name="nginx-alpha")
        second = Repository.objects.create(owner=self.bob, name="nginx-beta")

        self.add_stars(second, 2)

        response = self.client.get(self.url, {"q": "nginx-"})

        result_ids = self.get_result_ids(response)

        self.assertLess(result_ids.index(second.pk), result_ids.index(first.pk))

    def test_results_without_search_query_are_sorted_by_star_count(self):
        first = Repository.objects.create(owner=self.alice, name="redis")
        second = Repository.objects.create(owner=self.bob, name="postgres")

        self.add_stars(second, 3)
        self.add_stars(first, 1)

        response = self.client.get(self.url)
        result_ids = self.get_result_ids(response)

        self.assertLess(result_ids.index(second.pk), result_ids.index(first.pk))

    def test_official_filter(self):
        official = Repository.objects.create(owner=self.alice, name="official-app", is_official=True)

        response = self.client.get(self.url, {"official": "1"})

        result_ids = self.get_result_ids(response)

        self.assertIn(official.pk, result_ids)
        self.assertNotIn(self.exact_match.pk, result_ids)

    def test_community_filter(self):
        response = self.client.get(self.url, {"official": "0"})

        result_ids = self.get_result_ids(response)

        self.assertIn(self.exact_match.pk, result_ids)
        self.assertNotIn(
            Repository.objects.create(owner=self.alice, name="official-app", is_official=True).pk,
            result_ids,
        )

    def test_multiple_badge_filters(self):
        verified_user = User.objects.create_user(
            username="verified",
            email="verified@example.com",
            password=PASSWORD,
            badge=Badge.VERIFIED_PUBLISHER,
        )
        sponsored_user = User.objects.create_user(
            username="sponsored",
            email="sponsored@example.com",
            password=PASSWORD,
            badge=Badge.SPONSORED_OSS,
        )
        regular_user = User.objects.create_user(username="regular", email="regular@example.com", password=PASSWORD)

        verified = Repository.objects.create(owner=verified_user, name="verified-app")
        sponsored = Repository.objects.create(owner=sponsored_user, name="sponsored-app")
        regular = Repository.objects.create(owner=regular_user, name="regular-app")

        response = self.client.get(self.url, { "badge": [Badge.VERIFIED_PUBLISHER, Badge.SPONSORED_OSS] })

        result_ids = self.get_result_ids(response)

        self.assertIn(verified.pk, result_ids)
        self.assertIn(sponsored.pk, result_ids)
        self.assertNotIn(regular.pk, result_ids)