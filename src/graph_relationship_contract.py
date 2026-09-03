"""Deterministic graph entity/relationship contract for KM006.

The contract keeps endpoint identity separate from display names and carries
source provenance on every relationship. It is intentionally storage-neutral
so the existing Neo4j writers can adopt it without a second graph pipeline.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any


_SAFE_TOKEN = re.compile(r"[^A-Za-z0-9._:-]+")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _token(value: Any, fallback: str) -> str:
    value = _SAFE_TOKEN.sub("_", _text(value)).strip("._:-")
    return value or fallback


def _unresolved_key(name: str, entity_type: str, namespace: str) -> str:
    raw = "|".join((namespace, entity_type, name)).encode("utf-8")
    return "unresolved:" + hashlib.sha256(raw).hexdigest()[:24]


def normalize_entity(entity: Mapping[str, Any], *, namespace: str = "default") -> dict[str, Any] | None:
    name = _text(entity.get("Name") or entity.get("name"))
    if not name:
        return None
    entity_type = _token(entity.get("type") or entity.get("entity_type"), "Concept")
    entity_namespace = _token(entity.get("namespace") or namespace, "default")
    entity_key = _text(entity.get("entity_key") or entity.get("entity_id"))
    if not entity_key:
        entity_key = _unresolved_key(name, entity_type, entity_namespace)
    return {
        "entity_key": entity_key,
        "name": name,
        "type": entity_type,
        "description": _text(entity.get("description")),
        "namespace": entity_namespace,
        "source_document": _text(entity.get("source_document") or entity.get("source") or "") or None,
    }


def build_graph_contract(
    entities: list[Mapping[str, Any]],
    relationships: list[Mapping[str, Any]],
    *,
    source_document: str,
    source_chunk_id: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Normalize endpoints and add mandatory relationship provenance."""
    namespace = _token(source_document, "document")
    normalized_entities = [
        item for item in (normalize_entity(entity, namespace=namespace) for entity in entities) if item
    ]
    by_name = {(item["name"], item["type"]): item["entity_key"] for item in normalized_entities}
    by_name_only: dict[str, str] = {}
    for item in normalized_entities:
        by_name_only.setdefault(item["name"], item["entity_key"])

    default_chunk = source_chunk_id or f"{source_document}::chunk::0"
    normalized_relationships: list[dict[str, Any]] = []
    for relationship in relationships:
        source_name = _text(relationship.get("source_entity") or relationship.get("source") or relationship.get("Source"))
        target_name = _text(relationship.get("target_entity") or relationship.get("target") or relationship.get("Target"))
        if not source_name or not target_name:
            continue
        source_key = _text(relationship.get("source_entity_id")) or by_name_only.get(source_name)
        target_key = _text(relationship.get("target_entity_id")) or by_name_only.get(target_name)
        if not source_key or not target_key:
            # Do not invent formal master IDs for unresolved endpoints.
            continue
        normalized_relationships.append({
            "source_entity": source_key,
            "target_entity": target_key,
            "relationship_type": _token(relationship.get("relationship_type") or relationship.get("type") or relationship.get("Type"), "RELATED_TO").upper(),
            "description": _text(relationship.get("description")),
            "source_document": _text(relationship.get("source_document") or source_document),
            "source_chunk_id": _text(relationship.get("source_chunk_id") or default_chunk),
            "evidence_type": _token(relationship.get("evidence_type"), "ai_inferred"),
            "review_status": _token(relationship.get("review_status"), "pending"),
        })
    return {"entities": normalized_entities, "relationships": normalized_relationships}
