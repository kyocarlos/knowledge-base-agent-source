"""Validation helpers for the CSIT-owned approval boundary."""

from __future__ import annotations

from typing import Mapping


CSIT_APPROVAL_STATUSES = frozenset({"pending", "approved", "rejected"})
REQUIRED_FIELDS = (
    "source_record_id",
    "approval_status",
    "revision",
    "correlation_id",
)


class CSITBoundaryError(ValueError):
    pass


def validate_csit_metadata(metadata: Mapping[str, object]) -> dict[str, str]:
    """Return a sanitized CSIT decision or reject an incomplete contract."""
    result = {field: str(metadata.get(field, "")).strip() for field in REQUIRED_FIELDS}
    if not any(result.values()):
        return {}
    if any(not result[field] for field in REQUIRED_FIELDS):
        raise CSITBoundaryError("CSIT approval metadata is incomplete")
    if result["approval_status"] not in CSIT_APPROVAL_STATUSES:
        raise CSITBoundaryError("unsupported CSIT approval status")
    return result


def csit_metadata_from_request(headers: Mapping[str, str], manifest: Mapping[str, object]) -> dict[str, str]:
    supplied = {
        "source_record_id": headers.get("X-CSIT-Source-Record-ID", ""),
        "approval_status": headers.get("X-CSIT-Approval-Status", ""),
        "revision": headers.get("X-CSIT-Revision", ""),
        "correlation_id": headers.get("X-CSIT-Correlation-ID", ""),
    }
    from_manifest = manifest.get("csit")
    if isinstance(from_manifest, Mapping):
        for key in supplied:
            if not supplied[key]:
                supplied[key] = from_manifest.get(key, "")
    return validate_csit_metadata(supplied)
