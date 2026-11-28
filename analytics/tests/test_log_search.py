from datetime import datetime, timezone as dt_timezone
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from elasticsearch import ConnectionError as ESConnectionError
from elasticsearch_dsl import Search
from elasticsearch_dsl.response import Response

from accounts.models import Role, User
from analytics.forms import LogSearchForm
from analytics.search import (
    MAX_RESULT_WINDOW,
    LogHit,
    LogSearchCriteria,
    LogSearchError,
    LogSearchResult,
    build_search,
    search_logs,
)

PASSWORD = "Tr1cky-pass-2026"
BELGRADE = ZoneInfo("Europe/Belgrade")


def es_response(search, documents=(), total=None, relation="eq"):
    """An Elasticsearch response for ``search`` with the given ``_source`` documents."""
    hits = [
        {"_index": "dockerhub-logs", "_id": str(i), "_score": document.pop("_score", None), "_source": document}
        for i, document in enumerate(documents)
    ]
    body = {
        "took": 1,
        "timed_out": False,
        "hits": {
            "total": {"value": len(hits) if total is None else total, "relation": relation},
            "max_score": None,
            "hits": hits,
        },
    }
    return Response(search, body)


class BuildSearchTests(SimpleTestCase):
    def query(self, **criteria):
        return build_search(LogSearchCriteria(**criteria)).to_dict()

    def test_no_criteria_returns_all_entries_newest_first(self):
        body = self.query()

        self.assertNotIn("query", body)
        self.assertEqual(body["sort"], [{"timestamp": {"order": "desc"}}])

    def test_missing_index_returns_no_results_instead_of_error(self):
        self.assertTrue(build_search(LogSearchCriteria())._params["ignore_unavailable"])

    def test_after_and_before_are_an_inclusive_timestamp_range(self):
        after = datetime(2026, 11, 1, 8, 0, tzinfo=dt_timezone.utc)
        before = datetime(2026, 11, 2, 8, 0, tzinfo=dt_timezone.utc)

        body = self.query(after=after, before=before)

        self.assertEqual(
            body["query"]["bool"]["filter"],
            [{"range": {"timestamp": {"gte": "2026-11-01T08:00:00+00:00", "lte": "2026-11-02T08:00:00+00:00"}}}],
        )

    def test_only_after(self):
        body = self.query(after=datetime(2026, 11, 1, tzinfo=dt_timezone.utc))

        self.assertEqual(
            body["query"]["bool"]["filter"], [{"range": {"timestamp": {"gte": "2026-11-01T00:00:00+00:00"}}}]
        )

    def test_local_time_keeps_its_offset(self):
        body = self.query(before=datetime(2026, 11, 28, 14, 30, tzinfo=BELGRADE))

        self.assertEqual(
            body["query"]["bool"]["filter"], [{"range": {"timestamp": {"lte": "2026-11-28T14:30:00+01:00"}}}]
        )

    def test_levels_are_a_terms_filter(self):
        body = self.query(levels=("WARNING", "ERROR"))

        self.assertEqual(body["query"]["bool"]["filter"], [{"terms": {"level": ["WARNING", "ERROR"]}}])
        self.assertEqual(body["sort"], [{"timestamp": {"order": "desc"}}])

    def test_text_is_scored_and_sorted_by_relevance(self):
        body = self.query(text="error occured")
        query = body["query"]["bool"]

        self.assertEqual(query["must"], [{"match": {"message": {"query": "error occured", "operator": "and"}}}])
        self.assertEqual(query["should"], [{"match_phrase": {"message": {"query": "error occured", "boost": 2}}}])
        self.assertEqual(body["sort"], ["_score", {"timestamp": {"order": "desc"}}])

    def test_all_criteria_are_combined(self):
        body = self.query(
            after=datetime(2026, 11, 1, tzinfo=dt_timezone.utc), levels=("ERROR",), text="registry"
        )
        query = body["query"]["bool"]

        self.assertEqual(len(query["filter"]), 2)
        self.assertIn({"terms": {"level": ["ERROR"]}}, query["filter"])
        self.assertEqual(len(query["must"]), 1)


@mock.patch.object(Search, "execute", autospec=True)
class SearchLogsTests(SimpleTestCase):
    def test_returns_hits_and_total(self, execute):
        execute.side_effect = lambda search: es_response(
            search,
            [
                {
                    "timestamp": "2026-11-28T10:00:00.000+00:00",
                    "level": "ERROR",
                    "logger": "repositories.views",
                    "message": "Registry unavailable",
                    "exception": "Traceback ...",
                    "_score": 1.5,
                },
                {"timestamp": "2026-11-28T09:00:00.000+00:00", "level": "INFO", "message": "Started"},
            ],
            total=2,
        )

        result = search_logs(LogSearchCriteria(text="registry"))

        self.assertEqual(result.total, 2)
        self.assertTrue(result.total_is_exact)
        first, second = result.hits
        self.assertEqual(first.timestamp, datetime(2026, 11, 28, 10, 0, tzinfo=dt_timezone.utc))
        self.assertEqual(first.level, "ERROR")
        self.assertEqual(first.logger, "repositories.views")
        self.assertEqual(first.message, "Registry unavailable")
        self.assertEqual(first.exception, "Traceback ...")
        self.assertEqual(first.score, 1.5)
        self.assertEqual(second.logger, "")
        self.assertEqual(second.exception, "")

    def test_requests_the_given_page(self, execute):
        execute.side_effect = lambda search: es_response(search)

        search_logs(LogSearchCriteria(), page=3, per_page=20)

        body = execute.call_args.args[0].to_dict()
        self.assertEqual(body["from"], 40)
        self.assertEqual(body["size"], 20)
        self.assertEqual(body["track_total_hits"], MAX_RESULT_WINDOW)

    def test_last_page_stops_at_result_window(self, execute):
        execute.side_effect = lambda search: es_response(search)

        search_logs(LogSearchCriteria(), page=7, per_page=1500)  # 9000..10500

        body = execute.call_args.args[0].to_dict()
        self.assertEqual(body["from"], 9000)
        self.assertEqual(body["size"], 1000)

    def test_large_total_is_capped_and_marked_inexact(self, execute):
        execute.side_effect = lambda search: es_response(search, total=MAX_RESULT_WINDOW, relation="gte")

        result = search_logs(LogSearchCriteria())

        self.assertEqual(result.total, MAX_RESULT_WINDOW)
        self.assertFalse(result.total_is_exact)

    def test_page_outside_result_window_is_rejected(self, execute):
        for page in (0, MAX_RESULT_WINDOW // 50 + 1):
            with self.subTest(page=page), self.assertRaises(ValueError):
                search_logs(LogSearchCriteria(), page=page, per_page=50)
        execute.assert_not_called()

    def test_elasticsearch_errors_become_log_search_error(self, execute):
        execute.side_effect = ESConnectionError("connection refused")

        with self.assertRaises(LogSearchError):
            search_logs(LogSearchCriteria())


class LogSearchFormTests(SimpleTestCase):
    def test_empty_form_is_valid_with_empty_criteria(self):
        form = LogSearchForm({})

        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.to_criteria().is_empty())

    def test_converts_input_to_criteria_in_site_time_zone(self):
        form = LogSearchForm(
            {
                "after": "2026-11-28T08:00",
                "before": "2026-11-28T18:30:15",
                "levels": ["WARNING", "ERROR"],
                "text": "  error occured  ",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        criteria = form.to_criteria()
        self.assertEqual(criteria.after, datetime(2026, 11, 28, 8, 0, tzinfo=BELGRADE))
        self.assertEqual(criteria.before, datetime(2026, 11, 28, 18, 30, 15, tzinfo=BELGRADE))
        self.assertEqual(criteria.levels, ("WARNING", "ERROR"))
        self.assertEqual(criteria.text, "error occured")

    def test_after_later_than_before_is_invalid(self):
        form = LogSearchForm({"after": "2026-11-28T10:00", "before": "2026-11-28T09:00"})

        self.assertFalse(form.is_valid())
        self.assertIn("must not be later", form.non_field_errors()[0])

    def test_same_after_and_before_is_valid(self):
        form = LogSearchForm({"after": "2026-11-28T10:00", "before": "2026-11-28T10:00"})

        self.assertTrue(form.is_valid(), form.errors)

    def test_unknown_level_is_invalid(self):
        form = LogSearchForm({"levels": ["FATAL"]})

        self.assertFalse(form.is_valid())
        self.assertIn("levels", form.errors)

    def test_invalid_date_is_invalid(self):
        form = LogSearchForm({"after": "yesterday"})

        self.assertFalse(form.is_valid())
        self.assertIn("after", form.errors)

    def test_text_is_limited_to_200_characters(self):
        form = LogSearchForm({"text": "x" * 201})

        self.assertFalse(form.is_valid())
        self.assertIn("text", form.errors)


@mock.patch("analytics.views.search_logs")
class LogSearchViewTests(TestCase):
    url = reverse("analytics:log_search")

    @classmethod
    def setUpTestData(cls):
        cls.admin = cls.create_user("admin", Role.ADMIN)
        cls.super_admin = cls.create_user("super-admin", Role.SUPER_ADMIN)
        cls.regular_user = cls.create_user("regular", Role.REGULAR_USER)

    @classmethod
    def create_user(cls, username, role):
        return User.objects.create_user(
            username=username, email=f"{username}@example.com", password=PASSWORD, role=role
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def result(self, *hits, total=None, exact=True):
        return LogSearchResult(hits=list(hits), total=len(hits) if total is None else total, total_is_exact=exact)

    def hit(self, message="Repository created", level="INFO", **fields):
        return LogHit(
            timestamp=fields.pop("timestamp", datetime(2026, 11, 28, 9, 0, tzinfo=dt_timezone.utc)),
            level=level,
            logger=fields.pop("logger", "repositories.views"),
            message=message,
            **fields,
        )

    def test_anonymous_user_is_redirected_to_login(self, search_logs):
        self.client.logout()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)
        search_logs.assert_not_called()

    def test_regular_user_is_forbidden(self, search_logs):
        self.client.force_login(self.regular_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)
        search_logs.assert_not_called()

    def test_admin_and_super_admin_can_search(self, search_logs):
        search_logs.return_value = self.result()
        for user in (self.admin, self.super_admin):
            with self.subTest(user=user.username):
                self.client.force_login(user)

                response = self.client.get(self.url)

                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "analytics/log_search.html")

    def test_htmx_request_renders_partial_template(self, search_logs):
        search_logs.return_value = self.result()

        response = self.client.get(self.url, HTTP_HX_REQUEST="true")

        self.assertTemplateUsed(response, "analytics/partials/log_search_content.html")
        self.assertTemplateNotUsed(response, "analytics/log_search.html")

    def test_without_criteria_shows_newest_entries(self, search_logs):
        search_logs.return_value = self.result(self.hit())

        response = self.client.get(self.url)

        criteria = search_logs.call_args.args[0]
        self.assertTrue(criteria.is_empty())
        self.assertEqual(search_logs.call_args.kwargs, {"page": 1, "per_page": 50})
        self.assertContains(response, "newest first")

    def test_passes_criteria_from_query_string(self, search_logs):
        search_logs.return_value = self.result()

        self.client.get(
            self.url,
            {"after": "2026-11-28T08:00", "levels": ["WARNING", "ERROR"], "text": "error occured", "page": "2"},
        )

        criteria = search_logs.call_args.args[0]
        self.assertEqual(criteria.after, datetime(2026, 11, 28, 8, 0, tzinfo=BELGRADE))
        self.assertIsNone(criteria.before)
        self.assertEqual(criteria.levels, ("WARNING", "ERROR"))
        self.assertEqual(criteria.text, "error occured")
        self.assertEqual(search_logs.call_args.kwargs["page"], 2)

    def test_renders_entries(self, search_logs):
        search_logs.return_value = self.result(
            self.hit("Registry unavailable", level="ERROR", exception="Traceback: boom", score=2.5),
            self.hit("Login failed", level="WARNING", logger="accounts.views", score=1.0),
        )

        response = self.client.get(self.url, {"text": "registry"})

        self.assertContains(response, "2 log entries, most relevant first")
        self.assertContains(response, "Registry unavailable")
        self.assertContains(response, "Traceback: boom")
        self.assertContains(response, "accounts.views")
        self.assertContains(response, '<span class="log-level log-level-error">ERROR</span>', html=True)
        self.assertContains(response, "2.50")
        # stored in UTC, shown in the site time zone
        self.assertContains(response, "2026-11-28 10:00:00")

    def test_message_is_escaped(self, search_logs):
        search_logs.return_value = self.result(self.hit("<script>alert(1)</script>"))

        response = self.client.get(self.url)

        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;")

    def test_no_results(self, search_logs):
        search_logs.return_value = self.result()

        response = self.client.get(self.url, {"text": "nothing"})

        self.assertContains(response, "No log entries match these criteria.")

    def test_inexact_total(self, search_logs):
        search_logs.return_value = self.result(self.hit(), total=MAX_RESULT_WINDOW, exact=False)

        response = self.client.get(self.url)

        self.assertContains(response, f"At least {MAX_RESULT_WINDOW} log entries")

    def test_pagination_keeps_criteria(self, search_logs):
        search_logs.return_value = self.result(*[self.hit() for _ in range(50)], total=120)

        response = self.client.get(self.url, {"levels": "ERROR", "text": "boom"})

        page = response.context["page_obj"]
        self.assertTrue(response.context["is_paginated"])
        self.assertEqual(page.number, 1)
        self.assertEqual(response.context["paginator"].num_pages, 3)
        self.assertContains(response, "Page 1 of 3")
        self.assertContains(response, 'href="?levels=ERROR&amp;text=boom&page=2"')

    def test_invalid_form_does_not_search(self, search_logs):
        response = self.client.get(self.url, {"after": "2026-11-28T10:00", "before": "2026-11-28T09:00"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "must not be later")
        search_logs.assert_not_called()

    def test_invalid_page_returns_404(self, search_logs):
        for page in ("abc", "0", "-1", str(MAX_RESULT_WINDOW // 50 + 1)):
            with self.subTest(page=page):
                response = self.client.get(self.url, {"page": page})

                self.assertEqual(response.status_code, 404)
        search_logs.assert_not_called()

    def test_empty_page_after_the_last_returns_404(self, search_logs):
        search_logs.return_value = self.result(total=10)

        response = self.client.get(self.url, {"page": "5"})

        self.assertEqual(response.status_code, 404)

    def test_elasticsearch_unavailable_shows_error(self, search_logs):
        search_logs.side_effect = LogSearchError("connection refused")

        with self.assertLogs("analytics.views", level="WARNING") as logs:
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Log search is unavailable right now.")
        self.assertIn("Log search failed: connection refused", logs.output[0])

    def test_search_is_logged(self, search_logs):
        search_logs.return_value = self.result(self.hit())

        with self.assertLogs("analytics.views", level="INFO") as logs:
            self.client.get(self.url, {"levels": ["ERROR"], "text": "boom"})

        self.assertIn("Log search:", logs.output[0])
        self.assertIn("levels=ERROR", logs.output[0])
        self.assertIn("text='boom'", logs.output[0])
        self.assertIn("by=admin", logs.output[0])


class AnalyticsNavigationTests(TestCase):
    def test_link_is_shown_to_admins_only(self):
        admin = User.objects.create_user(username="admin", password=PASSWORD, role=Role.ADMIN)
        regular = User.objects.create_user(username="regular", password=PASSWORD, role=Role.REGULAR_USER)
        url = reverse("analytics:log_search")

        self.client.force_login(admin)
        self.assertContains(self.client.get(reverse("core:home")), f'href="{url}"')

        self.client.force_login(regular)
        self.assertNotContains(self.client.get(reverse("core:home")), f'href="{url}"')
