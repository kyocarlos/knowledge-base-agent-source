"""Stable API error mapping that does not expose internal exception details."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException

from app.schemas.common import ApiError, ApiResponse


logger = logging.getLogger(__name__)


def _trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", "unavailable")


def _is_versioned_api(request: Request) -> bool:
    return request.url.path == "/api/v1" or request.url.path.startswith("/api/v1/")


def _error_response(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    body = ApiResponse[None](
        data=None,
        error=ApiError(code=code, message=message),
        trace_id=_trace_id(request),
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers={"X-Trace-ID": _trace_id(request)},
    )


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        if not _is_versioned_api(request):
            return await request_validation_exception_handler(request, exc)
        return _error_response(request, 422, "validation_error", "Request validation failed")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        if not _is_versioned_api(request):
            return await http_exception_handler(request, exc)
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return _error_response(request, exc.status_code, f"http_{exc.status_code}", message)

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception):
        if not _is_versioned_api(request):
            return PlainTextResponse("Internal Server Error", status_code=500)
        logger.error(
            "Unhandled API exception trace_id=%s type=%s",
            _trace_id(request),
            type(exc).__name__,
        )
        return _error_response(request, 500, "internal_error", "Internal server error")
