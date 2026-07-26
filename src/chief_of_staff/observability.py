"""Structured logging with a deny-by-default context boundary."""

from __future__ import annotations

import json
import logging
import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Final, TextIO

REDACTED: Final = "[REDACTED]"

_EVENT_NAME: Final = re.compile(r"[a-z][a-z0-9_.-]{0,63}")
_SECRET_ASSIGNMENT: Final = re.compile(
    r"(?i)\b("
    r"api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|"
    r"password|passwd|authorization|cookie|credential"
    r")\b(\s*[:=]\s*)(\S+)"
)
_BEARER_TOKEN: Final = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/\-=]+")
_PROVIDER_TOKEN: Final = re.compile(
    r"\b(?:sk|xox[baprs]|gh[pousr])[-_][a-zA-Z0-9_-]{8,}\b"
)

# Only operational metadata is emitted. Unknown fields are represented by a
# count so accidental attempts to log source content remain visible without
# disclosing either field names or values.
_SAFE_CONTEXT_FIELDS: Final = frozenset(
    {
        "component",
        "connector",
        "cost_estimate",
        "coverage_status",
        "duration_ms",
        "environment",
        "error_category",
        "error_count",
        "freshness_status",
        "item_count",
        "latency_ms",
        "model",
        "operation",
        "policy_version",
        "prompt_version",
        "provider",
        "record_count",
        "request_class",
        "request_id",
        "run_id",
        "schema_version",
        "sensitivity_tier",
        "source",
        "status",
        "token_count",
        "validation_result",
        "warning_count",
    }
)


class StructuredJsonFormatter(logging.Formatter):
    """Render allow-listed operational metadata as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        """Format a record without emitting its free-form message."""

        raw_event = getattr(record, "event", None)
        event = (
            raw_event
            if isinstance(raw_event, str) and _EVENT_NAME.fullmatch(raw_event)
            else "unstructured_log"
        )

        raw_context = getattr(record, "context", {})
        context = (
            _sanitize_context(raw_context) if isinstance(raw_context, Mapping) else {}
        )

        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": event,
            **context,
        }

        if record.exc_info is not None:
            exception_class = record.exc_info[0]
            payload["exception_type"] = (
                exception_class.__name__
                if exception_class is not None
                else "UnknownException"
            )

        return json.dumps(
            payload,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )


def configure_logging(
    *,
    level: int = logging.INFO,
    stream: TextIO | None = None,
) -> logging.Logger:
    """Configure and return the application logger."""

    logger = logging.getLogger("chief_of_staff")
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredJsonFormatter())

    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    **context: object,
) -> None:
    """Emit a validated event with deny-by-default structured context."""

    if _EVENT_NAME.fullmatch(event) is None:
        raise ValueError(
            "event must use lowercase letters, numbers, dots, dashes, or underscores"
        )

    logger.log(
        level,
        event,
        extra={
            "event": event,
            "context": context,
        },
    )


def _sanitize_context(context: Mapping[object, object]) -> dict[str, object]:
    sanitized: dict[str, object] = {}
    redacted_field_count = 0
    for raw_key, value in context.items():
        if isinstance(raw_key, str) and raw_key in _SAFE_CONTEXT_FIELDS:
            sanitized[raw_key] = _sanitize_value(value)
        else:
            redacted_field_count += 1
    if redacted_field_count:
        sanitized["redacted_field_count"] = redacted_field_count
    return sanitized


def _sanitize_value(value: object) -> object:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        return _redact_text(value)
    return f"<{type(value).__name__}>"


def _redact_text(value: str) -> str:
    redacted = _BEARER_TOKEN.sub(f"Bearer {REDACTED}", value)
    redacted = _PROVIDER_TOKEN.sub(REDACTED, redacted)
    redacted = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}",
        redacted,
    )
    return redacted[:512]
