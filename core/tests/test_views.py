from unittest.mock import patch

from django.db import OperationalError
from django.test import TestCase
from django.urls import reverse


class CoreViewsTests(TestCase):
    def test_home_page_renders(self):
        response = self.client.get(reverse("core:home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/home.html")
        self.assertTemplateUsed(response, "base.html")

    def test_health_check_reports_ok(self):
        response = self.client.get(reverse("core:health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_health_check_logs_database_failure(self):
        with patch("core.views.connection.cursor", side_effect=OperationalError("connection refused")):
            with self.assertLogs("core.views", level="ERROR") as logs:
                response = self.client.get(reverse("core:health"))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "error", "database": "unavailable"})
        self.assertEqual(logs.records[0].levelname, "ERROR")
        self.assertIn("Health check failed: database unavailable: connection refused", logs.output[0])
