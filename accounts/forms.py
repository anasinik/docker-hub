from django.contrib.auth.forms import BaseUserCreationForm
from django.core.exceptions import ValidationError

from .models import User
from .validators import validate_not_reserved_username


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
