import unicodedata

from .models import User


def normalize_login_identifier(identifier):
    """Turn what a user types to sign in into the username to authenticate.

    Usernames cannot contain "@" (see ``validate_username_format``), so an
    identifier with "@" is always an email address: it is matched without case
    and replaced by that user's username. An unknown email is returned as is,
    so authentication fails like for a wrong password. Usernames are lowercase,
    so any other identifier is lowercased.

    Shared by ``LoginForm`` and the registry token endpoint (``docker login``),
    so both accept the same identifiers. NFKC matches Django's ``UsernameField``.
    """
    identifier = unicodedata.normalize("NFKC", identifier).strip()
    if "@" in identifier:
        user = User.objects.filter(email__iexact=identifier).only("username").first()
        return user.username if user else identifier
    return identifier.lower()
