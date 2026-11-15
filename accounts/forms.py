from django import forms
from django.contrib.auth.forms import AuthenticationForm, BaseUserCreationForm, UsernameField
from django.core.exceptions import ValidationError

from .models import User
from .validators import validate_not_reserved_username

EMAIL_MAX_LENGTH = 254


class LoginForm(AuthenticationForm):
    """Sign in with a username or an email address, like Docker Hub.

    Usernames cannot contain "@" (see ``validate_username_format``), so an
    identifier with "@" is always treated as an email address. The error for a
    wrong identifier and a wrong password is the same, so the form does not
    reveal which accounts exist.
    """

    username = UsernameField(
        label="Username or email",
        max_length=EMAIL_MAX_LENGTH,
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}),
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Incorrect username/email or password.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # AuthenticationForm limits the field to the username length (30),
        # which would reject longer email addresses.
        username_field = self.fields["username"]
        username_field.max_length = EMAIL_MAX_LENGTH
        username_field.widget.attrs["maxlength"] = str(EMAIL_MAX_LENGTH)

    def clean_username(self):
        identifier = self.cleaned_data["username"].strip()
        if "@" in identifier:
            user = User.objects.filter(email__iexact=identifier).only("username").first()
            return user.username if user else identifier
        return identifier.lower()


class SignUpForm(BaseUserCreationForm):
    """Self-registration of regular users.

    The form deliberately has no ``role`` field: everyone who signs up becomes a
    regular user, and a ``role`` sent in the request is ignored.
    """

    class Meta(BaseUserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs["autocomplete"] = "email"
        self.fields["username"].widget.attrs["autocomplete"] = "username"

    def clean_username(self):
        username = self.cleaned_data["username"].strip().lower()
        validate_not_reserved_username(username)
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("A user with that username already exists.", code="unique")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("A user with this email already exists.", code="unique")
        return email
