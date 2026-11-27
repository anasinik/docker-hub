import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from elasticsearch import ApiError, TransportError
from elasticsearch.helpers import bulk

from analytics.documents import LogEntry
from analytics.elasticsearch import get_client
from analytics.models import LogShippingState

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("timestamp", "level", "message")


class ShippingError(Exception):
    """Elasticsearch did not accept a batch, it is sent again on the next run."""


@dataclass
class ShipResult:
    sent: int = 0
    failed: int = 0
    invalid: int = 0

    def add(self, other):
        self.sent += other.sent
        self.failed += other.failed
        self.invalid += other.invalid


def ensure_index():
    try:
        LogEntry.init()
    except (ApiError, TransportError) as error:
        raise ShippingError(f"cannot create index {LogEntry._index._name}: {error}") from error


def file_identity(stat_result):
    return str(stat_result.st_ino) if stat_result.st_ino else ""


def read_batches(path, offset, batch_size):
    """Yield ``([(line_offset, raw), ...], end_offset)`` for complete lines."""
    with open(path, "rb") as file:
        file.seek(offset)
        batch = []
        while True:
            line = file.readline()
            if not line.endswith(b"\n"):
                break  # end of file or a line still being written
            batch.append((offset, line))
            offset += len(line)
            if len(batch) >= batch_size:
                yield batch, offset
                batch = []
        if batch:
            yield batch, offset


def parse_line(raw):
    try:
        entry = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return None
    if not isinstance(entry, dict) or any(field not in entry for field in REQUIRED_FIELDS):
        return None
    return entry


def document_id(file_id, line_offset, raw):
    digest = hashlib.sha1(f"{file_id}:{line_offset}:".encode())
    digest.update(raw)
    return digest.hexdigest()


def _status(error_item):
    return next(iter(error_item.values()), {}).get("status", 0)


def send_batch(client, actions):
    """Return ``(sent, failed)``. 4xx entries are skipped, 429/5xx are retried."""
    try:
        # chunk_size: bulk() would otherwise split the batch into requests of 500
        sent, errors = bulk(client, actions, chunk_size=len(actions), raise_on_error=False)
    except (ApiError, TransportError) as error:
        raise ShippingError(f"Elasticsearch is not available: {error}") from error

    retryable = [item for item in errors if _status(item) == 429 or _status(item) >= 500]
    if retryable:
        raise ShippingError(f"Elasticsearch could not store {len(retryable)} log entries")

    if errors:
        first = next(iter(errors[0].values()), {})
        logger.warning(
            "Elasticsearch rejected %d log entries: index=%s first_error=%s",
            len(errors), first.get("_index"), first.get("error"),
        )
    return sent, len(errors)


def _ship_file(path, state, batch_size):
    client = get_client()
    index = LogEntry._index._name
    result = ShipResult()

    for lines, end_offset in read_batches(path, state.offset, batch_size):
        actions = []
        for line_offset, raw in lines:
            entry = parse_line(raw)
            if entry is None:
                if raw.strip():
                    result.invalid += 1
                continue
            actions.append({
                "_index": index,
                "_id": document_id(state.file_id, line_offset, raw),
                "_source": entry,
            })

        if actions:
            sent, failed = send_batch(client, actions)
            result.sent += sent
            result.failed += failed

        state.offset = end_offset
        state.save(update_fields=["offset", "updated_at"])

    return result


def _rotated_file(path, file_id):
    rotated = Path(f"{path}.1")
    try:
        if file_identity(os.stat(rotated)) == file_id:
            return rotated
    except FileNotFoundError:
        pass
    return None


def ship_logs(path=None, batch_size=None):
    path = Path(path or settings.LOG_SHIP_FILE)
    batch_size = batch_size or settings.LOG_SHIP_BATCH_SIZE
    state, _ = LogShippingState.objects.get_or_create(path=str(path))
    result = ShipResult()

    try:
        current = os.stat(path)
    except FileNotFoundError:
        return result
    current_id = file_identity(current)

    if state.file_id and current_id and current_id != state.file_id:  # rotated
        rotated = _rotated_file(path, state.file_id)
        if rotated is not None:
            result.add(_ship_file(rotated, state, batch_size))
        state.file_id, state.offset = current_id, 0
        state.save()
    elif current.st_size < state.offset:  # truncated
        logger.warning("Log file is smaller than the shipped offset, reading it from the start: path=%s", path)
        state.offset = 0
        state.save()

    if state.file_id != current_id:  # first run
        state.file_id = current_id
        state.save()

    result.add(_ship_file(path, state, batch_size))

    if result.invalid:
        logger.warning("Skipped %d lines that are not JSON log entries: path=%s", result.invalid, path)
    return result
