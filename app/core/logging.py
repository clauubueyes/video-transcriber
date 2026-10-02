"""Logs JSON con una lista explícita de campos seguros."""

import json
import logging
from datetime import UTC, datetime

_SAFE_FIELDS = (
    "job_id",
    "status",
    "duration_seconds",
    "removed_uploads",
    "expired_results",
    "requeued_jobs",
)


class JsonFormatter(logging.Formatter):
    """Serializa solo los campos operativos permitidos en cada evento."""

    def format(self, record: logging.LogRecord) -> str:
        event: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for field in _SAFE_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                event[field] = value
        return json.dumps(event, ensure_ascii=False)


def configure_logging() -> logging.Logger:
    """Configura una vez el logger del servicio sin modificar el logger raíz."""
    logger = logging.getLogger("video_transcriber")
    if any(isinstance(handler.formatter, JsonFormatter) for handler in logger.handlers):
        return logger

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
