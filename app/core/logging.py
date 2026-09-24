from __future__ import annotations

import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

REQUEST_ID_CTX: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", REQUEST_ID_CTX.get()),
        }
        for attr in ("method", "path", "status_code", "duration_ms", "username", "action", "detail", "filename", "rows", "rows_inserted", "rows_replaced", "rows_skipped", "rows_errored"):
            value = getattr(record, attr, None)
            if value is not None:
                payload[attr] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(record, "request_id", REQUEST_ID_CTX.get())
        return True


def configure_logging() -> logging.Logger:
    level_name = os.getenv("SRWB_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    formatter = JsonFormatter()
    context_filter = RequestContextFilter()

    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        handler.addFilter(context_filter)
        root.addHandler(handler)
    else:
        for handler in root.handlers:
            handler.setFormatter(formatter)
            handler.addFilter(context_filter)

    app_logger = logging.getLogger("opsapp")
    app_logger.setLevel(level)
    return app_logger


logger = configure_logging()
