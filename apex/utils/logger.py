"""Structured JSON logging with correlation IDs.

Correlation IDs let you trace a single decision across discovery → strategy → scoring →
sizing → order placement → fill → resolution in the logs.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

_correlation_id: ContextVar[str] = ContextVar("apex_correlation_id", default="")


def new_correlation_id(prefix: str = "cor") -> str:
    """Generate and set a new correlation ID for the current context."""
    cid = f"{prefix}-{uuid.uuid4().hex[:12]}"
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str:
    return _correlation_id.get()


def set_correlation_id(cid: str) -> None:
    _correlation_id.set(cid)


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        cid = get_correlation_id()
        if cid:
            payload["cid"] = cid
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Arbitrary extras
        extra = getattr(record, "extra_fields", None)
        if extra and isinstance(extra, dict):
            for k, v in extra.items():
                if k not in payload:
                    payload[k] = v
        try:
            return json.dumps(payload, default=str)
        except (TypeError, ValueError):
            return json.dumps({"level": record.levelname, "msg": str(record.getMessage())})


_configured = False


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON handler on the root logger once."""
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Wrap logging.getLogger to ensure logging is configured."""
    if not _configured:
        configure_logging()
    return logging.getLogger(name)


def log_event(logger: logging.Logger, level: int, msg: str, **fields: Any) -> None:
    """Log a message with structured extra fields."""
    extra = {"extra_fields": fields} if fields else None
    logger.log(level, msg, extra=extra)
