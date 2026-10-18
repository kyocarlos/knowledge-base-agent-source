"""Shared Knowledge Package identity and version metadata contract."""

from __future__ import annotations

import hashlib
import re
from typing import Any


PACKAGE_SCHEMA_VERSION = "1.0"
DEFAULT_DOCUMENT_VERSION = "1.0.0"
DEFAULT_PUBLISH_STATUS = "draft"
PUBLISH_STATUSES = frozenset({"draft", "ready", "published", "superseded"})
_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){0,2}$")


def resolve_document_version(metadata: dict[str, Any] | None) -> str:
    """Read an explicit document version without accepting ambiguous values."""
    values = metadata or {}
    value = values.get("document_version") or values.get("documentVersion") or values.get("version")
    version = str(value).strip() if value is not None else DEFAULT_DOCUMENT_VERSION
    if not _VERSION_RE.fullmatch(version):
        raise ValueError("document_version must be a numeric dotted version")
    return version


def build_package_id(document_id: str, document_version: str) -> str:
    """Return a deterministic package identity for one document revision."""
    if not document_id or not document_version:
        raise ValueError("document_id and document_version are required")
    return hashlib.sha256(f"{document_id}\n{document_version}".encode("utf-8")).hexdigest()


def build_chunk_id(document_id: str, document_version: str, chunk_index: int, content: str) -> str:
    """Return a stable chunk identity scoped to a document revision."""
    if chunk_index < 0:
        raise ValueError("chunk_index must be non-negative")
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"{document_id}@{document_version}::chunk::{chunk_index}::{content_hash[:16]}"


def build_package_metadata(
    *,
    document_id: str,
    document_version: str,
    content_hash: str = "",
    publish_status: str = DEFAULT_PUBLISH_STATUS,
    is_current: bool = False,
) -> dict[str, Any]:
    """Build the shared revision fields carried by every chunk."""
    if publish_status not in PUBLISH_STATUSES:
        raise ValueError(f"unsupported publish_status: {publish_status}")
    if not isinstance(is_current, bool):
        raise ValueError("is_current must be boolean")
    if publish_status != "published" and is_current:
        raise ValueError("only published packages can be current")
    return {
        "package_schema_version": PACKAGE_SCHEMA_VERSION,
        "package_id": build_package_id(document_id, document_version),
        "document_id": document_id,
        "document_version": document_version,
        "content_hash": content_hash,
        "publish_status": publish_status,
        "is_current": is_current,
    }
