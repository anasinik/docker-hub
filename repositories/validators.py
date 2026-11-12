from django.core.validators import RegexValidator

REPOSITORY_NAME_MIN_LENGTH = 2
REPOSITORY_NAME_MAX_LENGTH = 100
# Same limit as Docker Hub's short description.
REPOSITORY_DESCRIPTION_MAX_LENGTH = 100

# The name becomes the second part of the image path ("alice/my-app"), so it
# follows Docker's rules for path components: lowercase letters and digits,
# optionally separated by single ".", "_" or "-" characters. A separator may not
# start or end the name, and two separators may not follow each other.
validate_repository_name = RegexValidator(
    regex=(
        rf"^(?=.{{{REPOSITORY_NAME_MIN_LENGTH},{REPOSITORY_NAME_MAX_LENGTH}}}$)"
        r"[a-z0-9]+(?:[._-][a-z0-9]+)*$"
    ),
    message=(
        f"Repository name must be {REPOSITORY_NAME_MIN_LENGTH}-{REPOSITORY_NAME_MAX_LENGTH} "
        "characters long and contain only lowercase letters, digits and single "
        "separators (., _ or -) between them."
    ),
    code="invalid_repository_name",
)
