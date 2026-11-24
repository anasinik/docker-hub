from urllib.parse import parse_qs, urlsplit

from django.test import TestCase
from django.urls import reverse

from accounts.models import Badge, Role, User


PASSWORD = "Tr1cky-pass-2026"


class UserBadgeAssignViewTests(TestCase):
    """Integration tests for administrator badge assignment."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(username="admin", email="admin@example.com", password=PASSWORD, role=Role.ADMIN)
        cls.target = cls.create_regular_user(username="target", badge=Badge.NONE)
        cls.verified_target = cls.create_regular_user(username="needle-target", badge=Badge.VERIFIED_PUBLISHER)
        cls.verified_other = cls.create_regular_user(username="needle-other", badge=Badge.VERIFIED_PUBLISHER)
        cls.sponsored_other = cls.create_regular_user(username="needle-sponsored", badge=Badge.SPONSORED_OSS)
        cls.another_admin = User.objects.create_user(username="another-admin", email="another-admin@example.com", password=PASSWORD, role=Role.ADMIN)

    @classmethod
    def create_regular_user(cls, username, badge=Badge.NONE):
        return User.objects.create_user(username=username, email=f"{username}@example.com", password=PASSWORD, role=Role.REGULAR_USER, badge=badge)

    def setUp(self):
        self.client.force_login(self.admin)

    def get_url(self, account=None):
        account = account or self.target
        return reverse("accounts:assign_badge", kwargs={"pk": account.pk})

    def get_result_ids(self, response):
        return [account.pk for account in response.context["users"]]

    def test_admin_can_assign_verified_publisher_badge(self):
        response = self.client.post(self.get_url(), {"badge": Badge.VERIFIED_PUBLISHER})

        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertEqual(self.target.badge, Badge.VERIFIED_PUBLISHER)

    def test_admin_can_assign_sponsored_oss_badge(self):
        response = self.client.post(self.get_url(), {"badge": Badge.SPONSORED_OSS})

        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertEqual(self.target.badge, Badge.SPONSORED_OSS)

    def test_admin_can_remove_user_badge(self):
        self.target.badge = Badge.VERIFIED_PUBLISHER
        self.target.save(update_fields=["badge"])

        response = self.client.post(self.get_url(), {"badge": Badge.NONE})

        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertEqual(self.target.badge, Badge.NONE)

    def test_htmx_assignment_returns_search_content_partial(self):
        response = self.client.post(self.get_url(), {"badge": Badge.VERIFIED_PUBLISHER}, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/partials/user_search_content.html")
        self.assertContains(response, 'id="search-content"')
        self.assertContains(response, f"Badge for user &#x27;{self.target.username}&#x27; has been updated")
        self.target.refresh_from_db()
        self.assertEqual(self.target.badge, Badge.VERIFIED_PUBLISHER)

    def test_htmx_assignment_preserves_search_query(self):
        response = self.client.post(self.get_url(), {"badge": Badge.VERIFIED_PUBLISHER, "q": "needle"}, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["query"], "needle")

        result_ids = self.get_result_ids(response)

        self.assertIn(self.verified_target.pk, result_ids)
        self.assertIn(self.verified_other.pk, result_ids)
        self.assertIn(self.sponsored_other.pk, result_ids)

        self.assertContains(response, 'value="needle"')

    def test_htmx_assignment_preserves_badge_filters(self):
        response = self.client.post(
            self.get_url(self.verified_target),
            {
                "badge": Badge.SPONSORED_OSS,
                "q": "needle",
                "filter_badge": [Badge.VERIFIED_PUBLISHER],
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_badges"], [Badge.VERIFIED_PUBLISHER])

        result_ids = self.get_result_ids(response)

        self.assertNotIn(self.verified_target.pk, result_ids)
        self.assertIn(self.verified_other.pk, result_ids)
        self.assertNotIn(self.sponsored_other.pk, result_ids)

        self.assertEqual(response.context["paginator"].count, 1)

    def test_htmx_assignment_updates_results_without_badge_filter(self):
        response = self.client.post(self.get_url(self.target), {"badge": Badge.SPONSORED_OSS, "q": "target"}, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.badge, Badge.SPONSORED_OSS)
        self.assertIn(self.target.pk, self.get_result_ids(response))

    def test_invalid_badge_does_not_update_user(self):
        original_badge = self.target.badge

        response = self.client.post(self.get_url(), {"badge": "INVALID_BADGE"}, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/partials/user_search_content.html")
        self.assertContains(response, "Invalid badge selection.")
        self.target.refresh_from_db()
        self.assertEqual(self.target.badge, original_badge)

    def test_missing_badge_does_not_update_user(self):
        response = self.client.post(self.get_url(), {}, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid badge selection.")
        self.target.refresh_from_db()
        self.assertEqual(self.target.badge, Badge.NONE)

    def test_normal_post_preserves_search_parameters(self):
        response = self.client.post(
            self.get_url(),
            {
                "badge": Badge.VERIFIED_PUBLISHER,
                "q": "needle",
                "filter_badge": [Badge.VERIFIED_PUBLISHER, Badge.SPONSORED_OSS],
            },
        )

        self.assertEqual(response.status_code, 302)

        parsed_url = urlsplit(response.url)
        query_params = parse_qs(parsed_url.query)

        self.assertEqual(parsed_url.path, reverse("accounts:list"))
        self.assertEqual(query_params["q"], ["needle"])
        self.assertEqual(query_params["badge"], [Badge.VERIFIED_PUBLISHER, Badge.SPONSORED_OSS])

        self.target.refresh_from_db()

        self.assertEqual(self.target.badge, Badge.VERIFIED_PUBLISHER)

    def test_regular_user_cannot_assign_badges(self):
        self.client.force_login(self.target)

        response = self.client.post(self.get_url(self.verified_target), {"badge": Badge.SPONSORED_OSS})

        self.assertNotEqual(response.status_code, 200)
        self.verified_target.refresh_from_db()
        self.assertEqual(self.verified_target.badge, Badge.VERIFIED_PUBLISHER)

    def test_anonymous_user_cannot_assign_badges(self):
        self.client.logout()

        response = self.client.post(self.get_url(), {"badge": Badge.VERIFIED_PUBLISHER})

        self.assertNotEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.badge, Badge.NONE)

    def test_admin_cannot_assign_badge_to_another_admin(self):
        response = self.client.post(self.get_url(self.another_admin), {"badge": Badge.VERIFIED_PUBLISHER})

        self.assertEqual(response.status_code, 404)
        self.another_admin.refresh_from_db()
        self.assertEqual(self.another_admin.badge, Badge.NONE)