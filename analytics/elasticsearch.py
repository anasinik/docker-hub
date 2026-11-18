from django.conf import settings
from elasticsearch_dsl import connections


def connection_kwargs():
    kwargs = {
        "hosts": [settings.ELASTICSEARCH_URL],
        "request_timeout": settings.ELASTICSEARCH_TIMEOUT,
    }
    if settings.ELASTICSEARCH_PASSWORD:
        kwargs["basic_auth"] = (settings.ELASTICSEARCH_USERNAME, settings.ELASTICSEARCH_PASSWORD)
    return kwargs


def configure_connection():
    connections.configure(default=connection_kwargs())


def get_client():
    return connections.get_connection()
