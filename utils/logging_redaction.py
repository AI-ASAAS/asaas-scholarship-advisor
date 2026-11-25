"""Logging redaction filter to keep secrets and key-shaped tokens out of logs."""

from __future__ import annotations

import logging
import re
from typing import Any

_REDACTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"AIza[0-9A-Za-z_\-]{10,}"), "[REDACTED_KEY]"),
    (re.compile(r"sk-or-[0-9A-Za-z_\-]{8,}"), "[REDACTED_KEY]"),
    (re.compile(r"sk-[0-9A-Za-z_\-]{12,}"), "[REDACTED_KEY]"),
    (re.compile(r"gsk_[0-9A-Za-z_\-]{10,}"), "[REDACTED_KEY]"),
    (re.compile(r"tvly-[0-9A-Za-z_\-]{8,}"), "[REDACTED_KEY]"),
    (re.compile(r"(?i)(Bearer\s+)[0-9A-Za-z._\-]{10,}"), r"\1[REDACTED_TOKEN]"),
    (
        re.compile(
            r"(?i)((?:x-admin-key|x-api-key|api[_-]?key|admin[_-]?key|secret|password|token)"
            r"\s*[:=]\s*)([^\s,;\"'&]{4,})"
        ),
        r"\1[REDACTED]",
    ),
    (re.compile(r"(?i)([?&](?:key|api_key|token|secret)=)([^&\s]+)"), r"\1[REDACTED]"),
)


def redact_text(value: str) -> str:
    """Replace any API keys, bearer tokens, or key-shaped substrings with placeholders."""
    text = value
    for pattern, replacement in _REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _redact_arg(arg: Any) -> Any:
    if isinstance(arg, str):
        return redact_text(arg)
    if isinstance(arg, dict):
        return {k: _redact_arg(v) for k, v in arg.items()}
    if isinstance(arg, tuple):
        return tuple(_redact_arg(item) for item in arg)
    if isinstance(arg, list):
        return [_redact_arg(item) for item in arg]
    return arg


class SecretRedactionFilter(logging.Filter):
    """Logging filter that strips key-shaped secrets from record messages and args."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        if record.args:
            record.args = _redact_arg(record.args)
        if record.exc_text:
            record.exc_text = redact_text(record.exc_text)
        return True


def install_log_redaction() -> None:
    """Attach SecretRedactionFilter idempotently to the root logger and handlers."""
    root = logging.getLogger()
    if not any(isinstance(f, SecretRedactionFilter) for f in root.filters):
        root.addFilter(SecretRedactionFilter())
    for handler in root.handlers:
        if not any(isinstance(f, SecretRedactionFilter) for f in handler.filters):
            handler.addFilter(SecretRedactionFilter())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "httpcore"):
        lg = logging.getLogger(name)
        if not any(isinstance(f, SecretRedactionFilter) for f in lg.filters):
            lg.addFilter(SecretRedactionFilter())
