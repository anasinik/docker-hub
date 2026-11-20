from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Badge, Role, User

PASSWORD = "Tr1cky-pass-2026"


class UserSearchViewTests(TestCase):
    """Integration tests for user search and relevance ranking."""

    url = reverse("accounts:list")

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password=PASSWORD,
            role=Role.ADMIN,
        )

        cls.exact_match = cls.create_regular_user(username="nginx", email="exact@example.com")
        cls.prefix_match = cls.create_regular_user(username="nginx-proxy", email="prefix@example.com")
        cls.contains_match = cls.create_regular_user(username="my-nginx", email="contains@example.com",)
        cls.email_match = cls.create_regular_user(username="email-user", email="needle@example.com")

    @classmethod
    def create_regular_user(cls, username, email=None, **extra_fields):
        """Create a regular user with a unique email address."""
        return User.objects.create_user(
            username=username,
            email=email or f"{username}@example.com",
            password=PASSWORD,
            role=Role.REGULAR_USER,
            **extra_fields,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def get_result_ids(self, response):
        """Return user IDs from the current result page."""
        page = response.context["page_obj"]
        return list(page.object_list.values_list("pk", flat=True))

    def test_search_page_renders(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/user_search.html")

    def test_htmx_request_renders_partial_template(self):
        response = self.client.get(self.url, {"q": "nginx"}, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/partials/user_search_content.html")

    def test_only_regular_users_are_returned(self):
        regular_user = self.create_regular_user("regular")

        admin_user = User.objects.create_user(
            username="another-admin",
            email="another-admin@example.com",
            password=PASSWORD,
            role=Role.ADMIN,
        )

        super_admin = User.objects.create_user(
            username="super-admin",
            email="super-admin@example.com",
            password=PASSWORD,
            role=Role.SUPER_ADMIN,
        )

        response = self.client.get(self.url)
        result_ids = self.get_result_ids(response)

        self.assertIn(regular_user.pk, result_ids)
        self.assertNotIn(admin_user.pk, result_ids)
        self.assertNotIn(super_admin.pk, result_ids)
        self.assertNotIn(self.admin.pk, result_ids)

    def test_username_relevance_ranking(self):
        response = self.client.get(self.url, {"q": "nginx"})

        result_ids = self.get_result_ids(response)

        self.assertEqual(result_ids, [self.exact_match.pk, self.prefix_match.pk, self.contains_match.pk])

    def test_email_exact_match_takes_priority_over_partial_match(self):
        exact_email_match = self.create_regular_user(username="email-exact", email="search@example.com")
        partial_email_match = self.create_regular_user(username="email-partial", email="contact-search@example.com")

        response = self.client.get(self.url, {"q": "search@example.com"})
        result_ids = self.get_result_ids(response)

        self.assertEqual(result_ids, [exact_email_match.pk, partial_email_match.pk])

    def test_text_relevance_takes_priority_over_registration_date(self):
        User.objects.filter(pk=self.contains_match.pk).update(date_joined=timezone.now() + timedelta(days=1))
        response = self.client.get(self.url, {"q": "nginx"})

        result_ids = self.get_result_ids(response)

        self.assertLess(result_ids.index(self.exact_match.pk), result_ids.index(self.contains_match.pk))

    def test_registration_date_breaks_equal_text_relevance(self):
        first = self.create_regular_user("team-alpha")
        second = self.create_regular_user("team-beta")

        User.objects.filter(pk=first.pk).update(date_joined=timezone.now() - timedelta(days=2))
        User.objects.filter(pk=second.pk).update(date_joined=timezone.now() - timedelta(days=1))

        response = self.client.get(self.url, {"q": "team-"})

        result_ids = self.get_result_ids(response)

        self.assertLess(result_ids.index(second.pk), result_ids.index(first.pk))

    def test_results_without_search_query_are_sorted_by_registration_date(self):
        older_user = self.create_regular_user("older")
        newer_user = self.create_regular_user("newer")

        User.objects.filter(pk=older_user.pk).update(date_joined=timezone.now() - timedelta(days=2))
        User.objects.filter(pk=newer_user.pk).update(date_joined=timezone.now() - timedelta(days=1))

        response = self.client.get(self.url)

        result_ids = self.get_result_ids(response)

        self.assertLess(result_ids.index(newer_user.pk), result_ids.index(older_user.pk))

    def test_multiple_badge_filters(self):
        verified_user = self.create_regular_user(username="verified", badge=Badge.VERIFIED_PUBLISHER)
        sponsored_user = self.create_regular_user(username="sponsored", badge=Badge.SPONSORED_OSS)
        regular_user = self.create_regular_user(username="regular")

        response = self.client.get(self.url, { "badge": [Badge.VERIFIED_PUBLISHER, Badge.SPONSORED_OSS]})
        result_ids = self.get_result_ids(response)

        self.assertIn(verified_user.pk, result_ids)
        self.assertIn(sponsored_user.pk, result_ids)
        self.assertNotIn(regular_user.pk, result_ids)

    def test_badge_filter_combines_with_search_query(self):
        verified_match = self.create_regular_user(username="needle-verified", badge=Badge.VERIFIED_PUBLISHER)
        sponsored_match = self.create_regular_user(username="needle-sponsored", badge=Badge.SPONSORED_OSS)
        regular_match = self.create_regular_user(username="needle-regular")

        response = self.client.get(self.url, {"q": "needle", "badge": [Badge.VERIFIED_PUBLISHER]})

        result_ids = self.get_result_ids(response)

        self.assertIn(verified_match.pk, result_ids)
        self.assertNotIn(sponsored_match.pk, result_ids)
        self.assertNotIn(regular_match.pk, result_ids)

    def test_regular_users_cannot_access_user_search(self):
        self.client.force_login(self.exact_match)

        response = self.client.get(self.url)

        self.assertNotEqual(response.status_code, 200)

    def test_anonymous_users_cannot_access_user_search(self):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertNotEqual(response.status_code, 200)