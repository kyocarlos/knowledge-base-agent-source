"""Canonical Knowledge Package v1 contract for the KM ingest boundary.

The package is deliberately storage-neutral.  Parsers and the CSIT adapter may
produce it, but only a validated package may be handed to a formal ingest
writer.  Business publication remains an upstream (CSIT) decision; KM keeps a
separate technical lifecycle in ``publish_status``.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


PACKAGE_SCHEMA = "ai_km_knowledge_v1"
LIFECYCLE_STATES = frozenset({"draft", "published", "superseded"})


class KnowledgePackageError(ValueError):
    """Raised when a package cannot safely enter the formal ingest path."""


def stable_chunk_id(document_id: str, document_version: str, content: str, locator: str = "") -> str:
    """Return an identity stable across filename changes and repeated runs."""
    material = "\x1f".join((document_id, document_version, locator, content))
    return "chunk_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KnowledgePackageError(f"{name} must be a non-empty string")
    return value.strip()


def validate_package(package: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize the canonical package without mutating input."""
    if not isinstance(package, Mapping):
        raise KnowledgePackageError("package must be an object")

    schema = _required_text(package.get("schema"), "schema")
    if schema != PACKAGE_SCHEMA:
        raise KnowledgePackageError(f"unsupported package schema: {schema}")

    document_id = _required_text(package.get("document_id"), "document_id")
    version = _required_text(package.get("version"), "version")
    metadata = package.get("metadata")
    if not isinstance(metadata, Mapping):
        raise KnowledgePackageError("metadata must be an object")

    chunks = package.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise KnowledgePackageError("chunks must be a non-empty array")
    normalized_chunks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(chunks):
        if not isinstance(raw, Mapping):
            raise KnowledgePackageError(f"chunks[{index}] must be an object")
        content = _required_text(raw.get("content"), f"chunks[{index}].content")
        locator = str(raw.get("source_locator") or raw.get("locator") or f"chunk:{index}").strip()
        chunk_id = str(raw.get("chunk_id") or stable_chunk_id(document_id, version, content, locator)).strip()
        if not chunk_id or chunk_id in seen_ids:
            raise KnowledgePackageError(f"chunks[{index}].chunk_id must be unique")
        seen_ids.add(chunk_id)
        item = dict(raw)
        item.update({"chunk_id": chunk_id, "content": content, "source_locator": locator})
        normalized_chunks.append(item)

    nodes = package.get("nodes", [])
    relationships = package.get("relationships", [])
    if not isinstance(nodes, list) or not isinstance(relationships, list):
        raise KnowledgePackageError("nodes and relationships must be arrays")
    status = str(package.get("publish_status") or "draft").strip().lower()
    if status not in LIFECYCLE_STATES:
        raise KnowledgePackageError(f"unsupported publish_status: {status}")

    normalized = dict(package)
    normalized.update({
        "schema": PACKAGE_SCHEMA,
        "document_id": document_id,
        "version": version,
        "metadata": dict(metadata),
        "chunks": normalized_chunks,
        "nodes": [dict(node) if isinstance(node, Mapping) else node for node in nodes],
        "relationships": [dict(rel) if isinstance(rel, Mapping) else rel for rel in relationships],
        "publish_status": status,
    })
    return normalized


def package_digest(package: Mapping[str, Any]) -> str:
    """Digest a validated package for idempotency/provenance records."""
    normalized = validate_package(package)
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProcessorResult:
    """Explicit result required before a receiver event may be completed."""

    success: bool
    stage: str
    required_stores: tuple[str, ...] = ()
    completed_stores: tuple[str, ...] = ()
    error_code: str = ""

    @property
    def complete(self) -> bool:
        return self.success and set(self.required_stores).issubset(self.completed_stores)

