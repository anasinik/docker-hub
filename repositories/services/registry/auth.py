"""Token authentication for the container registry.

The registry (Distribution) does not know our users. When a Docker client
needs access it is sent to our token endpoint (the "realm"), we check the
user's credentials, decide which actions they may perform on each requested
repository and return a signed JWT. The registry only verifies the signature
with the certificate from ``rootcertbundle``.

See https://distribution.github.io/distribution/spec/auth/token/ and
https://distribution.github.io/distribution/spec/auth/jwt/
"""

import base64
import datetime
import hashlib
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from django.conf import settings

from repositories.models import Repository, Visibility

REPOSITORY = "repository"
PULL = "pull"
PUSH = "push"
TOKEN_ALGORITHM = "RS256"

# Our own registry calls (tag sync, deleting images) use this subject. It
# contains "-", which usernames cannot, so it never matches a real user.
INTERNAL_SUBJECT = "dockerhub-app"


@dataclass(frozen=True)
class Scope:
    """One requested resource, e.g. ``repository:alice/web:pull,push``."""

    type: str
    name: str
    actions: tuple[str, ...]

    def as_access(self, actions=None):
        return {"type": self.type, "name": self.name, "actions": list(self.actions if actions is None else actions)}


def parse_scopes(values):
    """Parse scope values into ``Scope`` objects.

    Docker sends one ``scope`` parameter per resource (GET), while containerd
    sends them space-separated in a single ``scope`` field (POST); both are
    accepted. Malformed entries are skipped. Scopes for the same resource are
    merged, so ``pull`` and ``pull,push`` become one ``pull,push`` scope.
    """
    merged = {}
    for value in values:
        for item in value.split():
            parts = item.split(":")
            if len(parts) < 3:
                continue
            # The type may carry a class, e.g. "repository(plugin)"; the name
            # is everything between the type and the actions.
            scope_type, name, actions = parts[0], ":".join(parts[1:-1]), parts[-1]
            if not scope_type or not name:
                continue
            key = (scope_type, name)
            known = merged.setdefault(key, [])
            for action in actions.split(","):
                action = action.strip()
                if action and action not in known:
                    known.append(action)
    return [Scope(scope_type, name, tuple(actions)) for (scope_type, name), actions in merged.items()]


def find_repository(path):
    """Return the repository stored under a registry path, or None.

    ``owner/name`` is a user's repository, a path without a slash is an
    official repository (issue #28).
    """
    if "/" in path:
        owner, _, name = path.partition("/")
        if "/" in name:
            return None
        return (
            Repository.objects.select_related("owner")
            .filter(owner__username=owner, name=name, is_official=False)
            .first()
        )
    return Repository.objects.filter(name=path, is_official=True).first()


def granted_actions(user, repository):
    """Actions ``user`` may perform on ``repository`` (anonymous user allowed)."""
    if repository is None:
        # Repositories are created on the platform first; pushing to an
        # unknown path does not create one.
        return set()

    authenticated = user is not None and user.is_authenticated
    is_public = repository.visibility == Visibility.PUBLIC

    if repository.is_official:
        is_admin = authenticated and user.is_admin
        actions = {PULL} if is_public or is_admin else set()
        if is_admin:
            actions.add(PUSH)
        return actions

    if authenticated and repository.owner_id == user.pk:
        return {PULL, PUSH}
    # Admins get no access to other users' private repositories.
    return {PULL} if is_public else set()


def resolve_access(user, scopes):
    """Return ``(access, denied)`` for the requested scopes.

    ``access`` is the list for the token's ``access`` claim. ``denied`` lists
    the scopes where at least one requested action was refused, for logging.
    """
    access = []
    denied = []
    for scope in scopes:
        allowed = set()
        if scope.type == REPOSITORY:
            allowed = granted_actions(user, find_repository(scope.name))
        actions = [action for action in scope.actions if action in allowed]
        if actions:
            access.append(scope.as_access(actions))
        if len(actions) < len(scope.actions):
            denied.append(scope)
    return access, denied


def key_id(public_key):
    """Key ID in the libtrust format that the registry matches against its certificates.

    SHA-256 of the DER encoded public key, first 240 bits, base32, 12 groups of 4.
    """
    der = public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    encoded = base64.b32encode(hashlib.sha256(der).digest()[:30]).decode()
    return ":".join(encoded[i : i + 4] for i in range(0, len(encoded), 4))


@lru_cache(maxsize=4)
def _load_private_key(path):
    return serialization.load_pem_private_key(Path(path).read_bytes(), password=None)


def load_private_key():
    """Load the signing key from REGISTRY_TOKEN_PRIVATE_KEY_PATH (raises OSError if missing)."""
    return _load_private_key(str(settings.REGISTRY_TOKEN_PRIVATE_KEY_PATH))


def issue_token(subject, access):
    """Sign a registry token and return the JSON body for the token endpoint."""
    private_key = load_private_key()
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    ttl = int(settings.REGISTRY_TOKEN_TTL)
    claims = {
        "iss": settings.REGISTRY_TOKEN_ISSUER,
        "sub": subject,
        "aud": settings.REGISTRY_TOKEN_SERVICE,
        "iat": now,
        # Small leeway for clock differences between the app and the registry.
        "nbf": now - datetime.timedelta(seconds=10),
        "exp": now + datetime.timedelta(seconds=ttl),
        "jti": uuid.uuid4().hex,
        "access": access,
    }
    token = jwt.encode(
        claims,
        private_key,
        algorithm=TOKEN_ALGORITHM,
        headers={"kid": key_id(private_key.public_key())},
    )
    return {
        # "token" is the registry spec, "access_token" the OAuth2 name; clients use either.
        "token": token,
        "access_token": token,
        "expires_in": ttl,
        "issued_at": now.isoformat().replace("+00:00", "Z"),
    }


def issue_internal_token(access):
    """Token for the application's own registry calls.

    Not limited by the user rules, so it can also grant ``delete`` and
    ``registry:catalog:*``. Never returned to clients.
    """
    return issue_token(INTERNAL_SUBJECT, access)["token"]


def generate_key_pair(common_name, days=5 * 365):
    """Create an RSA key and a self-signed certificate, both PEM encoded."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=days))
        .sign(private_key, hashes.SHA256())
    )
    key_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return key_pem, certificate.public_bytes(serialization.Encoding.PEM)
