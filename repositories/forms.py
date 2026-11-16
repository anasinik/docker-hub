from django import forms
from django.core.exceptions import ValidationError
from django.utils.html import format_html

from .models import Repository


class LowercaseCharField(forms.CharField):
    """Lowercases the input before validators run, so ``My-App`` becomes ``my-app``."""

    def to_python(self, value):
        return super().to_python(value).lower()


class RepositoryForm(forms.ModelForm):
    """Create a repository for ``owner``.

    The form deliberately has no ``owner`` or ``is_official`` field: the owner is
    always the logged-in user, and an ``owner`` sent in the request is ignored.
    """

    class Meta:
        model = Repository
        fields = ("name", "description", "visibility")
        field_classes = {"name": LowercaseCharField}
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, owner, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner
        self.instance.owner = owner
        self.fields["name"].widget.attrs["autocomplete"] = "off"

    def clean_name(self):
        name = self.cleaned_data["name"]
        if Repository.objects.filter(owner=self.owner, name=name).exists():
            raise ValidationError("You already have a repository with this name.", code="unique")
        return name


class RepositorySettingsForm(forms.ModelForm):
    """Change the description and visibility of an existing repository.

    The name is not editable: it is part of the registry path ``owner/name``
    that images are pushed to and pulled from.
    """

    class Meta:
        model = Repository
        fields = ("description", "visibility")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
        }


class RepositoryDeleteForm(forms.Form):
    """Confirm deleting ``repository`` by typing its name."""

    confirm_name = forms.CharField(label="Repository name", strip=True)

    def __init__(self, *args, repository, **kwargs):
        super().__init__(*args, **kwargs)
        self.repository = repository
        self.fields["confirm_name"].widget.attrs["autocomplete"] = "off"
        self.fields["confirm_name"].help_text = format_html("Type <code>{}</code> to confirm.", repository.name)

    def clean_confirm_name(self):
        confirm_name = self.cleaned_data["confirm_name"]
        if confirm_name != self.repository.name:
            raise ValidationError("The name does not match this repository.", code="mismatch")
        return confirm_name
