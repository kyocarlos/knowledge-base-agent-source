"""Request trace propagation and response correlation."""

from __future__ import annotations

import contextvars
import logging
import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


TRACE_HEADER = "X-Trace-ID"
_VALID_TRACE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
current_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="unavailable")
logger = logging.getLogger(__name__)


def normalize_trace_id(value: str | None) -> str:
    candidate = (value or "").strip()
    if candidate and _VALID_TRACE_ID.fullmatch(candidate):
        return candidate
    return uuid.uuid4().hex


class TraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = normalize_trace_id(request.headers.get(TRACE_HEADER))
        request.state.trace_id = trace_id
        token = current_trace_id.set(trace_id)
        try:
            response = await call_next(request)
            response.headers[TRACE_HEADER] = trace_id
            logger.info(
                "HTTP request trace_id=%s method=%s path=%s status=%s",
                trace_id,
                request.method,
                request.url.path,
                response.status_code,
            )
            return response
        finally:
            current_trace_id.reset(token)
