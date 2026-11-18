from django.conf import settings as django_settings
from elasticsearch_dsl import Date, Document, Float, Integer, Ip, Keyword, Long, MetaField, Text


class LogEntry(Document):
    # Fields written by JsonFormatter for every record
    timestamp = Date(required=True)
    level = Keyword(required=True)
    logger = Keyword()
    message = Text(fields={"raw": Keyword(ignore_above=1024)})
    module = Keyword()
    function = Keyword()
    line = Integer()
    process_id = Integer()
    thread_name = Keyword()
    exception = Text()
    stack = Text()

    # extra={...} fields of RequestLoggingMiddleware (logger "dockerhub.requests")
    http_method = Keyword()
    http_path = Keyword()
    http_status = Integer()
    duration_ms = Float()
    username = Keyword()
    client_ip = Ip()

    # extra={...} fields of the other apps
    repo_id = Long()

    class Index:
        name = django_settings.ELASTICSEARCH_LOG_INDEX
        settings = {
            "number_of_shards": 1,
            "number_of_replicas": 0,  # single-node cluster
        }

    class Meta:
        # New extra={...} fields are mapped as keywords (exact match, filters)
        # instead of Elasticsearch's default text + keyword pair.
        dynamic_templates = MetaField([
            {
                "strings_as_keywords": {
                    "match_mapping_type": "string",
                    "mapping": {"type": "keyword", "ignore_above": 1024},
                }
            }
        ])
