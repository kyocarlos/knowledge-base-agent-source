"""Fail-closed loading of source sidecar metadata.

The converted-document and original-upload layouts use the same sidecar
contract. Keeping path discovery and JSON validation here prevents callers
from silently indexing a document with fallback identity after corruption.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SOURCE_METADATA_SUFFIX = ".source.json"


class SourceMetadataError(ValueError):
    """Raised when an existing source metadata sidecar is not valid JSON."""


def find_source_metadata_path(source_path: str | Path) -> Path:
    """Return the canonical sibling sidecar, or an original-upload sidecar."""
    path = Path(source_path)
    sibling = path.with_name(f"{path.stem}{SOURCE_METADATA_SUFFIX}")
    if sibling.exists():
        return sibling
    for ancestor in path.parents:
        candidate = ancestor / "original" / f"{path.stem}{SOURCE_METADATA_SUFFIX}"
        if candidate.exists():
            return candidate
    return sibling


def load_source_metadata(source_path: str | Path, *, required: bool = False) -> dict[str, Any]:
    """Load a source sidecar and reject malformed or non-object content."""
    metadata_path = find_source_metadata_path(source_path)
    if not metadata_path.exists():
        if required:
            raise SourceMetadataError(f"source metadata missing: {metadata_path}")
        return {}
    try:
        value = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceMetadataError(f"source metadata invalid: {metadata_path}") from exc
    if not isinstance(value, dict):
        raise SourceMetadataError(f"source metadata must be an object: {metadata_path}")
    return value
