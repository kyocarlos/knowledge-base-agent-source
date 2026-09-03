"""
執行環境連線設定輔助。
"""

from __future__ import annotations

import os
import socket
from urllib.parse import urlparse


def _can_connect(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def resolve_neo4j_uri(candidate: str | None = None) -> str:
    """
    解析 Neo4j 連線 URI。

    優先順序：
    1. 明確設定的 `NEO4J_URI`
    2. 傳入的 candidate
    3. 預設 `bolt://neo4j:7687`

    若預設 service name 在目前 runtime 無法解析，會自動回退到本機映射的 17687。
    """
    value = os.getenv("NEO4J_URI") or candidate or "bolt://neo4j:7687"
    parsed = urlparse(value)
    host = parsed.hostname or ""
    port = parsed.port or 7687

    if host and _can_connect(host, port):
        return value

    fallback_candidates = (
        "bolt://127.0.0.1:17687",
        "bolt://localhost:17687",
        "bolt://127.0.0.1:7687",
    )
    for fallback in fallback_candidates:
        parsed_fallback = urlparse(fallback)
        fallback_host = parsed_fallback.hostname or ""
        fallback_port = parsed_fallback.port or 7687
        if fallback_host and _can_connect(fallback_host, fallback_port):
            return fallback

    return value


def resolve_qdrant_url(candidate: str | None = None) -> str:
    """
    解析 QDrant 連線 URL。

    優先順序：
    1. 明確設定的 `QDRANT_URL`
    2. 傳入的 candidate
    3. 預設值

    若預設位址在目前 runtime 無法連線，會回退到本機 6335。
    """
    explicit = os.getenv("QDRANT_URL", "").strip()
    if explicit:
        # An explicit deployment contract must never silently cross to another
        # Qdrant endpoint when that endpoint is unavailable.
        return explicit

    value = candidate or "http://host.docker.internal:6333"
    parsed = urlparse(value)
    host = parsed.hostname or ""
    port = parsed.port or 6333

    if host and _can_connect(host, port):
        return value

    fallback_candidates = (
        "http://127.0.0.1:6335",
        "http://localhost:6335",
        "http://127.0.0.1:6333",
    )
    for fallback in fallback_candidates:
        parsed_fallback = urlparse(fallback)
        fallback_host = parsed_fallback.hostname or ""
        fallback_port = parsed_fallback.port or 6333
        if fallback_host and _can_connect(fallback_host, fallback_port):
            return fallback

    return value
