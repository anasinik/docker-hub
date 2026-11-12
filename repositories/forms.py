from django import forms
from django.core.exceptions import ValidationError

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
