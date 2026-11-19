from django.conf import settings
from django.utils.module_loading import import_string


def get_registry_client():
    client_class = import_string(settings.REGISTRY_CLIENT_CLASS)
    return client_class()