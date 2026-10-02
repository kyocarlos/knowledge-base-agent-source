"""Logging helpers that attach the active request trace identifier."""

from __future__ import annotations

import logging

from app.core.trace import current_trace_id


class TraceContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = current_trace_id.get("unavailable")
        return True


def configure_logging() -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(item, TraceContextFilter) for item in handler.filters):
            handler.addFilter(TraceContextFilter())
