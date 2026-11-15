import json
import logging
from datetime import datetime, timezone

# attributes every LogRecord has; anything else came from extra={...}
_RECORD_ATTRIBUTES = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):

    def format(self, record):
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "process_id": record.process,
            "thread_name": record.threadName,
        }

        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            entry["stack"] = self.formatStack(record.stack_info)

        for key, value in record.__dict__.items():
            if key not in _RECORD_ATTRIBUTES and key not in entry:
                entry[key] = value

        # default=str so logging never crashes on non-serializable values
        return json.dumps(entry, ensure_ascii=False, default=str)