from django import forms
from django.contrib.auth.forms import AuthenticationForm, BaseUserCreationForm, PasswordChangeForm, UsernameField
from django.core.exceptions import ValidationError

from .identifiers import normalize_login_identifier
from .models import Badge, Role, User
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
        return normalize_login_identifier(self.cleaned_data["username"])


class SignUpForm(BaseUserCreationForm):
    """Self-registration of regular users.

    The form deliberately has no ``role`` field: everyone who signs up becomes a
    regular user, and a ``role`` sent in the request is ignored.
    """

    class Meta(BaseUserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    # Reserved names (see RESERVED_USERNAMES) are refused here; admins
    # registered by the super admin may use them.
    allow_reserved_usernames = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs["autocomplete"] = "email"
        self.fields["username"].widget.attrs["autocomplete"] = "username"

    def clean_username(self):
        username = self.cleaned_data["username"].strip().lower()
        if not self.allow_reserved_usernames:
            validate_not_reserved_username(username)
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("A user with that username already exists.", code="unique")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("A user with this email already exists.", code="unique")
        return email


class AdminRegistrationForm(SignUpForm):
    """The super admin registers an administrator with an initial password.

    Same username, email and password rules as sign-up, except that reserved
    usernames are allowed. The role is always ADMIN (a ``role`` in the request
    is ignored), and the admin must change the initial password at the first
    sign-in, because the super admin knows it.
    """

    allow_reserved_usernames = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The super admin types a password for someone else.
        for name in ("password1", "password2"):
            self.fields[name].widget.attrs["autocomplete"] = "new-password"
        self.fields["password1"].label = "Initial password"
        self.fields["password2"].label = "Initial password confirmation"

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = Role.ADMIN
        user.password_change_required = True
        if commit:
            user.save()
        return user

class AccountPasswordChangeForm(PasswordChangeForm):
    """Change the password with the current one; the new one must be different.

    Saving clears ``password_change_required``, which gives the super admin
    (generated password) and new admins (password set by the super admin)
    access after the first sign-in.
    """

    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get("new_password1")
        if new_password and self.user.check_password(new_password):
            self.add_error("new_password1", "The new password must be different from the current one.")
        return cleaned_data

    def save(self, commit=True):
        self.user.password_change_required = False
        return super().save(commit=commit)


class UserBadgeAssignmentForm(forms.Form):
    badge = forms.ChoiceField(choices=Badge.choices, required=False, label="Publisher badge")

    def clean(self):
        cleaned_data = super().clean()

        if "badge" not in self.data:
            self.add_error("badge", "Please select a badge.")

        return cleaned_data