from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

USERNAME_MIN_LENGTH = 4
USERNAME_MAX_LENGTH = 30

# Usernames are also the namespace of a user's repositories ("alice/nginx"),
# so they follow Docker Hub's rules: lowercase letters and digits only.
validate_username_format = RegexValidator(
    regex=rf"^[a-z0-9]{{{USERNAME_MIN_LENGTH},{USERNAME_MAX_LENGTH}}}$",
    message=(
        f"Username must be {USERNAME_MIN_LENGTH}-{USERNAME_MAX_LENGTH} characters long "
        "and contain only lowercase letters and digits."
    ),
    code="invalid_username",
)

# Names a self-registered user may not take: they would let a user pose as an
# official publisher ("library" is Docker Hub's namespace for official images)
# or clash with application URLs. Admins created by the super admin may still
# use them.
RESERVED_USERNAMES = frozenset(
    {
        "accounts",
        "admin",
        "administrator",
        "analytics",
        "api",
        "docker",
        "dockerhub",
        "explore",
        "health",
        "library",
        "login",
        "logout",
        "media",
        "official",
        "profile",
        "register",
        "repositories",
        "repository",
        "root",
        "search",
        "settings",
        "signup",
        "static",
        "superadmin",
        "support",
    }
)


def validate_not_reserved_username(value):
    if value.lower() in RESERVED_USERNAMES:
        raise ValidationError("This username is reserved.", code="reserved_username")
