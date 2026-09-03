"""Small, dependency-free Qdrant readiness contract."""

from __future__ import annotations

import os
from urllib.request import urlopen


class QdrantNotReadyError(RuntimeError):
    """Raised when the configured Qdrant endpoint cannot serve healthz."""


def configured_qdrant_url() -> str:
    value = os.getenv("QDRANT_URL", "").strip()
    if not value:
        raise QdrantNotReadyError("QDRANT_URL is required")
    return value.rstrip("/")


def check_qdrant_ready(url: str | None = None, timeout: float = 2.0) -> bool:
    endpoint = (url or configured_qdrant_url()).rstrip("/") + "/healthz"
    try:
        with urlopen(endpoint, timeout=timeout) as response:
            return response.status == 200
    except Exception as exc:
        raise QdrantNotReadyError("Qdrant readiness check failed") from exc
