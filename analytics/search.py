from dataclasses import dataclass, field
from datetime import datetime

from elasticsearch import ApiError, TransportError

from analytics.documents import LogEntry

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# elasticsearch pages only through the first 10 000 hits (index.max_result_window)
MAX_RESULT_WINDOW = 10_000


class LogSearchError(Exception):
    """Elasticsearch could not run the search (unreachable, overloaded, ...)."""


@dataclass(frozen=True)
class LogSearchCriteria:
    # every criterion is optional (they are combined with AND)

    after: datetime | None = None
    before: datetime | None = None
    levels: tuple[str, ...] = ()
    text: str = "" # words in the message, ranked by relevance

    def is_empty(self):
        return not (self.after or self.before or self.levels or self.text)


@dataclass(frozen=True)
class LogHit:
    timestamp: datetime | None
    level: str
    logger: str
    message: str
    exception: str = ""
    score: float | None = None

    @classmethod
    def from_document(cls, document):
        return cls(
            timestamp=document.timestamp,
            level=document.level,
            logger=getattr(document, "logger", "") or "",
            message=getattr(document, "message", "") or "",
            exception=getattr(document, "exception", "") or "",
            score=getattr(document.meta, "score", None),
        )


@dataclass(frozen=True)
class LogSearchResult:
    hits: list[LogHit] = field(default_factory=list)
    total: int = 0  # at most MAX_RESULT_WINDOW
    total_is_exact: bool = True


def build_search(criteria):
    # translate 'criteria' into an elasticsearch search over the log index
    
    search = LogEntry.search().params(ignore_unavailable=True)  # no index yet -> no results

    timestamp_range = {}
    if criteria.after:
        timestamp_range["gte"] = criteria.after.isoformat()
    if criteria.before:
        timestamp_range["lte"] = criteria.before.isoformat()
    if timestamp_range:
        search = search.filter("range", timestamp=timestamp_range)

    if criteria.levels:
        search = search.filter("terms", level=list(criteria.levels))

    if criteria.text:
        # every word must occur in the message (the exact phrase ranks higher)
        search = search.query(
            "bool",
            must=[{"match": {"message": {"query": criteria.text, "operator": "and"}}}],
            should=[{"match_phrase": {"message": {"query": criteria.text, "boost": 2}}}],
        )
        return search.sort("_score", {"timestamp": {"order": "desc"}})

    return search.sort({"timestamp": {"order": "desc"}})


def search_logs(criteria, page=1, per_page=50):
    # return one page (1-based) of log entries matching criteria
    start = (page - 1) * per_page
    end = min(start + per_page, MAX_RESULT_WINDOW)
    if page < 1 or start >= end:
        raise ValueError(f"Page {page} is outside the first {MAX_RESULT_WINDOW} results.")

    search = build_search(criteria)[start:end].extra(track_total_hits=MAX_RESULT_WINDOW)
    try:
        response = search.execute()
    except (ApiError, TransportError) as error:
        raise LogSearchError(str(error)) from error

    total = response.hits.total
    return LogSearchResult(
        hits=[LogHit.from_document(document) for document in response],
        total=min(total.value, MAX_RESULT_WINDOW),
        total_is_exact=total.relation == "eq",
    )
