from django.test import TestCase

from accounts.identifiers import normalize_login_identifier
from accounts.models import User


class NormalizeLoginIdentifierTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.create_user(username="alice", email="alice@example.com", password="Tr1cky-pass-2025")

    def test_username_is_lowercased_and_stripped(self):
        self.assertEqual(normalize_login_identifier("  Alice "), "alice")

    def test_email_is_replaced_by_username(self):
        self.assertEqual(normalize_login_identifier("alice@example.com"), "alice")

    def test_email_is_matched_without_case(self):
        self.assertEqual(normalize_login_identifier(" ALICE@Example.COM "), "alice")

    def test_unknown_email_is_returned_unchanged(self):
        self.assertEqual(normalize_login_identifier("nobody@example.com"), "nobody@example.com")

    def test_fullwidth_characters_are_normalized(self):
        # NFKC, like Django's UsernameField on the login page
        self.assertEqual(normalize_login_identifier("ａｌｉｃｅ"), "alice")
