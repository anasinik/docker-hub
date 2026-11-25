import atexit
import base64
import re
import shutil
import tempfile
from io import StringIO
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from django.core.management import CommandError, call_command
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from repositories.models import Repository, Visibility
from repositories.services.registry import auth
from repositories.services.registry.auth import Scope

PASSWORD = "Tr1cky-pass-2025"
SERVICE = "test-registry"
ISSUER = "test-issuer"
TTL = 120

# Created at import, because override_settings below reads KEY_PATH when the
# classes are decorated. Removed at exit, not in tearDownModule: the test runner
# reorders classes (TestCase before SimpleTestCase), so the module is torn down
# before all of its classes have run.
_key_dir = tempfile.mkdtemp()
atexit.register(shutil.rmtree, _key_dir, ignore_errors=True)
KEY_PATH = Path(_key_dir) / "token.key"
KEY_PATH.write_bytes(auth.generate_key_pair(ISSUER)[0])


def token_settings(**extra):
    values = {
        "REGISTRY_TOKEN_SERVICE": SERVICE,
        "REGISTRY_TOKEN_ISSUER": ISSUER,
        "REGISTRY_TOKEN_PRIVATE_KEY_PATH": KEY_PATH,
        "REGISTRY_TOKEN_TTL": TTL,
    }
    values.update(extra)
    return override_settings(**values)


def public_key():
    return serialization.load_pem_private_key(KEY_PATH.read_bytes(), password=None).public_key()


def decode(token):
    return jwt.decode(token, public_key(), algorithms=["RS256"], audience=SERVICE, issuer=ISSUER)


def basic_auth(username, password):
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"HTTP_AUTHORIZATION": f"Basic {encoded}"}


class ParseScopesTests(SimpleTestCase):
    def test_parses_single_scope(self):
        self.assertEqual(
            auth.parse_scopes(["repository:alice/web:pull,push"]),
            [Scope("repository", "alice/web", ("pull", "push"))],
        )

    def test_parses_multiple_values(self):
        scopes = auth.parse_scopes(["repository:alice/web:pull", "repository:bob1/api:push"])

        self.assertEqual(
            scopes,
            [Scope("repository", "alice/web", ("pull",)), Scope("repository", "bob1/api", ("push",))],
        )

    def test_parses_space_separated_scopes(self):
        scopes = auth.parse_scopes(["repository:alice/web:pull repository:bob1/api:pull"])

        self.assertEqual([scope.name for scope in scopes], ["alice/web", "bob1/api"])

    def test_merges_scopes_for_the_same_repository(self):
        scopes = auth.parse_scopes(["repository:alice/web:pull repository:alice/web:pull,push"])

        self.assertEqual(scopes, [Scope("repository", "alice/web", ("pull", "push"))])

    def test_skips_malformed_scopes(self):
        self.assertEqual(auth.parse_scopes(["", "repository", "repository:pull", ":alice/web:pull"]), [])

    def test_parses_catalog_scope(self):
        self.assertEqual(auth.parse_scopes(["registry:catalog:*"]), [Scope("registry", "catalog", ("*",))])


@token_settings()
class IssueTokenTests(SimpleTestCase):
    def test_key_id_has_libtrust_format(self):
        kid = auth.key_id(public_key())

        self.assertRegex(kid, r"^([A-Z2-7]{4}:){11}[A-Z2-7]{4}$")
        self.assertEqual(kid, auth.key_id(public_key()))

    def test_token_is_signed_and_has_registry_claims(self):
        access = [{"type": "repository", "name": "alice/web", "actions": ["pull"]}]

        body = auth.issue_token("alice", access)
        claims = decode(body["token"])

        self.assertEqual(body["access_token"], body["token"])
        self.assertEqual(body["expires_in"], TTL)
        self.assertTrue(body["issued_at"].endswith("Z"))
        self.assertEqual(claims["sub"], "alice")
        self.assertEqual(claims["access"], access)
        self.assertEqual(claims["exp"] - claims["iat"], TTL)
        self.assertLess(claims["nbf"], claims["iat"])
        self.assertTrue(claims["jti"])
        self.assertEqual(jwt.get_unverified_header(body["token"])["kid"], auth.key_id(public_key()))

    def test_token_from_another_key_is_rejected(self):
        other_key_pem, _ = auth.generate_key_pair("other")
        other_key = serialization.load_pem_private_key(other_key_pem, password=None)
        forged = jwt.encode({"sub": "alice", "aud": SERVICE, "iss": ISSUER}, other_key, algorithm="RS256")

        with self.assertRaises(jwt.InvalidSignatureError):
            decode(forged)

    def test_internal_token_can_grant_delete_and_catalog(self):
        access = [
            {"type": "repository", "name": "alice/web", "actions": ["delete"]},
            {"type": "registry", "name": "catalog", "actions": ["*"]},
        ]

        claims = decode(auth.issue_internal_token(access))

        self.assertEqual(claims["sub"], auth.INTERNAL_SUBJECT)
        self.assertEqual(claims["access"], access)

    def test_internal_subject_is_not_a_valid_username(self):
        self.assertIsNone(re.fullmatch(r"[a-z0-9]{4,30}", auth.INTERNAL_SUBJECT))


class AccessRulesTests(TestCase):
    """Unit tests for the permission rules, without the HTTP layer."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        cls.bob = User.objects.create_user(username="bob1", email="bob@example.com", password=PASSWORD)
        cls.admin = User.objects.create_admin(username="admin1", email="admin@example.com", password=PASSWORD)
        cls.public = Repository.objects.create(owner=cls.alice, name="web")
        cls.private = Repository.objects.create(owner=cls.alice, name="secret", visibility=Visibility.PRIVATE)
        cls.official = Repository.objects.create(owner=cls.admin, name="nginx", is_official=True)
        cls.official_private = Repository.objects.create(
            owner=cls.admin, name="internal", is_official=True, visibility=Visibility.PRIVATE
        )

    def test_owner_can_pull_and_push_own_repositories(self):
        for repository in (self.public, self.private):
            self.assertEqual(auth.granted_actions(self.alice, repository), {"pull", "push"})

    def test_other_user_can_only_pull_public_repository(self):
        self.assertEqual(auth.granted_actions(self.bob, self.public), {"pull"})
        self.assertEqual(auth.granted_actions(self.bob, self.private), set())

    def test_anonymous_user_can_only_pull_public_repository(self):
        self.assertEqual(auth.granted_actions(None, self.public), {"pull"})
        self.assertEqual(auth.granted_actions(None, self.private), set())

    def test_admin_has_no_access_to_other_users_private_repository(self):
        self.assertEqual(auth.granted_actions(self.admin, self.public), {"pull"})
        self.assertEqual(auth.granted_actions(self.admin, self.private), set())

    def test_only_admins_push_official_repositories(self):
        self.assertEqual(auth.granted_actions(self.admin, self.official), {"pull", "push"})
        self.assertEqual(auth.granted_actions(self.alice, self.official), {"pull"})
        self.assertEqual(auth.granted_actions(None, self.official), {"pull"})

    def test_private_official_repository_is_only_for_admins(self):
        self.assertEqual(auth.granted_actions(self.admin, self.official_private), {"pull", "push"})
        self.assertEqual(auth.granted_actions(self.alice, self.official_private), set())

    def test_unknown_repository_gets_no_access(self):
        self.assertEqual(auth.granted_actions(self.alice, None), set())

    def test_find_repository_by_registry_path(self):
        self.assertEqual(auth.find_repository("alice/web"), self.public)
        self.assertEqual(auth.find_repository("nginx"), self.official)
        self.assertIsNone(auth.find_repository("web"))
        self.assertIsNone(auth.find_repository("admin1/nginx"))
        self.assertIsNone(auth.find_repository("alice/web/extra"))
        self.assertIsNone(auth.find_repository("alice/missing"))

    def test_resolve_access_keeps_allowed_actions_and_reports_denied(self):
        scopes = auth.parse_scopes(
            ["repository:alice/web:pull,push", "repository:alice/secret:pull", "registry:catalog:*"]
        )

        access, denied = auth.resolve_access(self.bob, scopes)

        self.assertEqual(access, [{"type": "repository", "name": "alice/web", "actions": ["pull"]}])
        self.assertEqual([scope.name for scope in denied], ["alice/web", "alice/secret", "catalog"])


@token_settings()
class RegistryTokenViewTests(TestCase):
    """Integration tests for /registry/token/, using the test client."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user(username="alice", email="alice@example.com", password=PASSWORD)
        cls.bob = User.objects.create_user(username="bob1", email="bob@example.com", password=PASSWORD)
        cls.admin = User.objects.create_admin(username="admin1", email="admin@example.com", password=PASSWORD)
        Repository.objects.create(owner=cls.alice, name="web")
        Repository.objects.create(owner=cls.alice, name="secret", visibility=Visibility.PRIVATE)
        Repository.objects.create(owner=cls.admin, name="nginx", is_official=True)

    def setUp(self):
        self.url = reverse("registry_token")

    def get_token(self, scopes=(), user=None, password=PASSWORD, service=SERVICE):
        headers = basic_auth(user, password) if user else {}
        params = {"service": service, "scope": list(scopes)}
        return self.client.get(self.url, params, **headers)

    def post_token(self, scope="", username="alice", password=PASSWORD, grant_type="password", client=None):
        data = {
            "grant_type": grant_type,
            "service": SERVICE,
            "client_id": "containerd-client",
            "username": username,
            "password": password,
            "scope": scope,
        }
        return (client or self.client).post(self.url, data)

    def access(self, response):
        self.assertEqual(response.status_code, 200)
        return decode(response.json()["token"])["access"]

    # docker login

    def test_docker_login_returns_token_without_access(self):
        response = self.client.get(
            self.url, {"service": SERVICE, "account": "alice", "client_id": "docker"}, **basic_auth("alice", PASSWORD)
        )

        self.assertEqual(response.status_code, 200)
        claims = decode(response.json()["token"])
        self.assertEqual(claims["sub"], "alice")
        self.assertEqual(claims["access"], [])

    def test_wrong_password_returns_401_and_is_logged_by_accounts(self):
        with self.assertLogs("accounts.signals", "WARNING") as logs, self.assertNoLogs("repositories.views", "WARNING"):
            response = self.get_token(user="alice", password="wrong-password")

        self.assertEqual(response.status_code, 401)
        self.assertIn("Basic", response["WWW-Authenticate"])
        self.assertEqual(response.json()["error"], "invalid_grant")
        self.assertIn("Login failed: username='alice'", logs.output[0])

    def test_login_accepts_same_identifiers_as_login_page(self):
        for identifier in ("Alice", "alice@example.com", "ALICE@Example.COM"):
            with self.subTest(method="GET", identifier=identifier):
                response = self.get_token(["repository:alice/secret:pull"], user=identifier)

                self.assertEqual(response.status_code, 200)
                claims = decode(response.json()["token"])
                self.assertEqual(claims["sub"], "alice")
                self.assertEqual(claims["access"][0]["name"], "alice/secret")

            with self.subTest(method="POST", identifier=identifier):
                response = self.post_token("repository:alice/secret:pull", username=identifier)

                self.assertEqual(response.status_code, 200)
                claims = decode(response.json()["token"])
                self.assertEqual(claims["sub"], "alice")
                self.assertEqual(claims["access"][0]["name"], "alice/secret")

    def test_unknown_email_returns_401(self):
        with self.subTest(method="GET"):
            self.assertEqual(self.get_token(user="nobody@example.com").status_code, 401)
        with self.subTest(method="POST"):
            self.assertEqual(self.post_token(username="nobody@example.com").status_code, 401)

    def test_inactive_user_cannot_log_in(self):
        User.objects.filter(pk=self.bob.pk).update(is_active=False)

        response = self.get_token(user="bob1")

        self.assertEqual(response.status_code, 401)

    def test_malformed_authorization_header_returns_401(self):
        for header in ("Basic not-base64!", "Bearer abc", f"Basic {base64.b64encode(b'no-colon').decode()}"):
            with self.subTest(header=header):
                response = self.client.get(self.url, HTTP_AUTHORIZATION=header)

                self.assertEqual(response.status_code, 401)

    def test_unknown_service_returns_400(self):
        response = self.get_token(["repository:alice/web:pull"], service="other-registry")

        self.assertEqual(response.status_code, 400)

    # pull and push (GET)

    def test_anonymous_user_can_pull_public_repository(self):
        access = self.access(self.get_token(["repository:alice/web:pull"]))

        self.assertEqual(access, [{"type": "repository", "name": "alice/web", "actions": ["pull"]}])

    def test_anonymous_user_cannot_pull_private_repository(self):
        with self.assertLogs("repositories.views", "WARNING") as logs:
            access = self.access(self.get_token(["repository:alice/secret:pull"]))

        self.assertEqual(access, [])
        self.assertIn("Registry access denied: username='anonymous'", logs.output[0])

    def test_owner_can_push_and_pull_private_repository(self):
        access = self.access(self.get_token(["repository:alice/secret:pull,push"], user="alice"))

        self.assertEqual(access, [{"type": "repository", "name": "alice/secret", "actions": ["pull", "push"]}])

    def test_other_user_cannot_push_to_repository(self):
        access = self.access(self.get_token(["repository:alice/web:pull,push"], user="bob1"))

        self.assertEqual(access, [{"type": "repository", "name": "alice/web", "actions": ["pull"]}])

    def test_admin_cannot_pull_other_users_private_repository(self):
        access = self.access(self.get_token(["repository:alice/secret:pull"], user="admin1"))

        self.assertEqual(access, [])

    def test_push_to_unknown_repository_is_denied(self):
        access = self.access(self.get_token(["repository:alice/missing:pull,push"], user="alice"))

        self.assertEqual(access, [])

    def test_multiple_scope_parameters_in_one_request(self):
        access = self.access(
            self.get_token(
                ["repository:alice/web:pull,push", "repository:nginx:pull", "repository:alice/secret:pull"],
                user="alice",
            )
        )

        self.assertEqual(
            access,
            [
                {"type": "repository", "name": "alice/web", "actions": ["pull", "push"]},
                {"type": "repository", "name": "nginx", "actions": ["pull"]},
                {"type": "repository", "name": "alice/secret", "actions": ["pull"]},
            ],
        )

    def test_admin_can_push_official_repository(self):
        access = self.access(self.get_token(["repository:nginx:pull,push"], user="admin1"))

        self.assertEqual(access, [{"type": "repository", "name": "nginx", "actions": ["pull", "push"]}])

    def test_regular_user_cannot_push_official_repository(self):
        access = self.access(self.get_token(["repository:nginx:pull,push"], user="alice"))

        self.assertEqual(access, [{"type": "repository", "name": "nginx", "actions": ["pull"]}])

    def test_users_cannot_get_catalog_or_delete_access(self):
        access = self.access(self.get_token(["registry:catalog:*", "repository:alice/web:delete"], user="alice"))

        self.assertEqual(access, [])

    def test_issued_token_is_logged(self):
        with self.assertLogs("repositories.views", "INFO") as logs:
            self.get_token(["repository:alice/web:pull,push"], user="alice")

        self.assertIn("Registry token issued: username=alice access=alice/web:pull,push", logs.output[-1])

    # containerd (POST, OAuth2 password grant)

    def test_password_grant_with_space_separated_scopes(self):
        response = self.post_token("repository:alice/web:pull repository:alice/web:pull,push")

        self.assertEqual(
            self.access(response), [{"type": "repository", "name": "alice/web", "actions": ["pull", "push"]}]
        )
        self.assertEqual(response.json()["access_token"], response.json()["token"])

    def test_password_grant_does_not_need_csrf_token(self):
        response = self.post_token("repository:alice/web:pull", client=Client(enforce_csrf_checks=True))

        self.assertEqual(response.status_code, 200)

    def test_password_grant_with_wrong_password_returns_401(self):
        response = self.post_token("repository:alice/web:pull", password="wrong-password")

        self.assertEqual(response.status_code, 401)

    def test_password_grant_without_credentials_returns_400(self):
        response = self.post_token("repository:alice/web:pull", username="", password="")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_request")

    def test_other_grant_types_are_not_supported(self):
        response = self.post_token(grant_type="refresh_token")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "unsupported_grant_type")

    def test_other_methods_are_not_allowed(self):
        self.assertEqual(self.client.put(self.url).status_code, 405)

    def test_missing_signing_key_returns_503(self):
        with token_settings(REGISTRY_TOKEN_PRIVATE_KEY_PATH=Path(_key_dir) / "missing.key"):
            with self.assertLogs("repositories.views", "ERROR") as logs:
                response = self.get_token(["repository:alice/web:pull"])

        self.assertEqual(response.status_code, 503)
        self.assertIn("Registry token key cannot be loaded", logs.output[0])


class GenerateRegistryKeysCommandTests(SimpleTestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        self.key_path = self.directory / "auth" / "token.key"
        self.cert_path = self.directory / "auth" / "token.crt"

    def run_command(self, *args):
        with token_settings(REGISTRY_TOKEN_PRIVATE_KEY_PATH=self.key_path):
            call_command("generate_registry_keys", *args, stdout=StringIO())

    def test_creates_key_and_matching_certificate(self):
        from cryptography import x509

        self.run_command()

        key = serialization.load_pem_private_key(self.key_path.read_bytes(), password=None)
        certificate = x509.load_pem_x509_certificate(self.cert_path.read_bytes())
        self.assertEqual(auth.key_id(certificate.public_key()), auth.key_id(key.public_key()))

    def test_refuses_to_overwrite_without_force(self):
        self.run_command()
        old_key = self.key_path.read_bytes()

        with self.assertRaises(CommandError):
            self.run_command()
        self.assertEqual(self.key_path.read_bytes(), old_key)

        self.run_command("--force")
        self.assertNotEqual(self.key_path.read_bytes(), old_key)
