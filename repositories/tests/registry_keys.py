"""Signing key and settings shared by the registry tests (no real key on disk needed)."""

import atexit
import shutil
import tempfile
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from django.test import override_settings

from repositories.services.registry import auth

SERVICE = "test-registry"
ISSUER = "test-issuer"
TTL = 120

# Created at import, because override_settings reads KEY_PATH when the test
# classes are decorated. Removed at exit, not in tearDownModule: the test runner
# reorders classes (TestCase before SimpleTestCase), so a module is torn down
# before all of its classes have run.
_key_dir = tempfile.mkdtemp()
atexit.register(shutil.rmtree, _key_dir, ignore_errors=True)
KEY_DIR = Path(_key_dir)
KEY_PATH = KEY_DIR / "token.key"
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
