"""Pure v1.0 implementation-spec contracts for metadata and data routing.

This module validates a package boundary and produces a routing plan only. It
does not call CSIT, write files, or mutate Neo4j, Qdrant, TimescaleDB, or KM
registries.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


class KMSpecContractError(ValueError):
    """Fail-closed validation error with stable machine-readable code."""

    def __init__(self, code: str, message: str, *, fields: tuple[str, ...] = ()) -> None:
        self.code = code
        self.fields = fields
        super().__init__(f"{code}: {message}")


REQUIRED_METADATA = (
    "document_id",
    "document_version",
    "document_type",
    "source_system",
    "access_roles",
    "visibility",
    "publish_status",
    "approval_status",
    "is_current",
)
_PUBLISHABLE = {"published"}
_APPROVED = {"approved", "published"}
_ROUTES = {
    "knowledge": ("neo4j", "qdrant"),
    "report": ("neo4j", "qdrant"),
    "timeseries": ("timescaledb",),
}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def validate_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Validate required v1.0 metadata without inventing missing values."""
    if not isinstance(metadata, Mapping):
        raise KMSpecContractError("metadata_invalid", "metadata must be an object")
    missing = tuple(field for field in REQUIRED_METADATA if field not in metadata)
    if missing:
        raise KMSpecContractError("metadata_missing", "required metadata is missing", fields=missing)

    empty = tuple(field for field in REQUIRED_METADATA if field != "is_current" and not _text(metadata[field]))
    if empty:
        raise KMSpecContractError("metadata_empty", "required metadata is empty", fields=empty)
    if not isinstance(metadata["is_current"], bool):
        raise KMSpecContractError("metadata_invalid", "is_current must be boolean", fields=("is_current",))
    if metadata["publish_status"] not in {"draft", "ready", "published", "superseded"}:
        raise KMSpecContractError("publish_status_invalid", "unsupported publish_status", fields=("publish_status",))
    if metadata["is_current"] and metadata["publish_status"] != "published":
        raise KMSpecContractError("lifecycle_invalid", "only published metadata can be current", fields=("publish_status", "is_current"))
    if metadata["publish_status"] in _PUBLISHABLE and metadata["approval_status"] not in _APPROVED:
        raise KMSpecContractError("approval_required", "published metadata requires approval", fields=("approval_status",))
    if not isinstance(metadata["access_roles"], (list, tuple, str)):
        raise KMSpecContractError("metadata_invalid", "access_roles must be explicit", fields=("access_roles",))
    if not _text(metadata["visibility"]):
        raise KMSpecContractError("metadata_empty", "visibility is required", fields=("visibility",))
    return dict(metadata)


@dataclass(frozen=True, slots=True)
class RoutingPlan:
    """Deterministic, auditable destination plan with no side effects."""

    decision_id: str
    artifact_type: str
    destinations: tuple[str, ...]
    indexable: bool
    published_only: bool
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "artifact_type": self.artifact_type,
            "destinations": list(self.destinations),
            "indexable": self.indexable,
            "published_only": self.published_only,
            "reason": self.reason,
        }


def build_routing_plan(metadata: Mapping[str, Any], *, artifact_type: str) -> RoutingPlan:
    """Create a fixed route; unknown types and non-publishable packages fail closed."""
    checked = validate_metadata(metadata)
    route = _ROUTES.get(_text(artifact_type).lower())
    if route is None:
        raise KMSpecContractError("route_unknown", "artifact type has no approved route", fields=("artifact_type",))
    publishable = checked["publish_status"] in _PUBLISHABLE and checked["approval_status"] in _APPROVED
    if not publishable:
        return RoutingPlan(
            decision_id=_decision_id(checked, artifact_type),
            artifact_type=_text(artifact_type).lower(),
            destinations=(),
            indexable=False,
            published_only=True,
            reason="package is not approved and published",
        )
    return RoutingPlan(
        decision_id=_decision_id(checked, artifact_type),
        artifact_type=_text(artifact_type).lower(),
        destinations=route,
        indexable=True,
        published_only=True,
        reason="approved published package route",
    )


def _decision_id(metadata: Mapping[str, Any], artifact_type: str) -> str:
    material = json.dumps(
        {"document_id": metadata["document_id"], "document_version": metadata["document_version"], "artifact_type": _text(artifact_type).lower()},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
