from django import forms

from analytics.search import LEVELS, LogSearchCriteria

DATETIME_LOCAL_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"]


class DateTimeLocalInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, attrs=None):
        super().__init__(attrs={"step": 1, **(attrs or {})}, format="%Y-%m-%dT%H:%M:%S")


class LogSearchForm(forms.Form):

    after = forms.DateTimeField(
        label="From",
        required=False,
        input_formats=DATETIME_LOCAL_FORMATS,
        widget=DateTimeLocalInput(),
    )
    before = forms.DateTimeField(
        label="To",
        required=False,
        input_formats=DATETIME_LOCAL_FORMATS,
        widget=DateTimeLocalInput(),
    )
    levels = forms.MultipleChoiceField(
        label="Level",
        required=False,
        choices=[(level, level.title()) for level in LEVELS],
        widget=forms.CheckboxSelectMultiple,
    )
    text = forms.CharField(
        label="Message contains",
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={"type": "search", "placeholder": "e.g. repository deleted", "autocomplete": "off"}),
    )

    def clean(self):
        cleaned_data = super().clean()
        after, before = cleaned_data.get("after"), cleaned_data.get("before")
        if after and before and after > before:
            raise forms.ValidationError("“From” must not be later than “To”.")
        return cleaned_data

    def to_criteria(self):
        data = self.cleaned_data
        return LogSearchCriteria(
            after=data["after"],
            before=data["before"],
            levels=tuple(data["levels"]),
            text=data["text"],
        )
