"""WP10C bridge from document routing to the existing KM ingest pipeline.

This module owns only orchestration metadata. Conversion, chunking, embedding,
Neo4j, Qdrant, and Search remain delegated to the existing implementations.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from .document_intelligence import DocumentRoutePlan, detect_document
from .document_normalization import NormalizationCatalog, NormalizedValue, normalize_record
from .knowledge_package import build_package_metadata, resolve_document_version


class DocumentPipelineError(RuntimeError):
    """Stable, fail-closed error for WP10C orchestration failures."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class DocumentPipelineResult:
    """Auditable output of one document-to-existing-ingest orchestration."""

    route_plan: DocumentRoutePlan
    normalized_values: Mapping[str, NormalizedValue]
    package_metadata: Mapping[str, Any]
    source_metadata_path: str
    converted_output_path: str
    ingest_result: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "route": self.route_plan.as_dict(),
            "normalized_values": {
                field: value.as_dict() for field, value in self.normalized_values.items()
            },
            "package_metadata": dict(self.package_metadata),
            "source_metadata_path": self.source_metadata_path,
            "converted_output_path": self.converted_output_path,
            "ingest_result": self.ingest_result,
        }


def _content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _build_source_metadata(
    *,
    metadata: Mapping[str, Any],
    route_plan: DocumentRoutePlan,
    normalized_values: Mapping[str, NormalizedValue],
    package_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge WP10 evidence into the existing sidecar contract."""
    source_metadata = dict(metadata)
    source_metadata.update(package_metadata)
    source_metadata.update(
        {
            "document_route": route_plan.as_dict(),
            "source_locator": route_plan.source_locator.as_dict(),
            "normalization_provenance": {
                field: value.as_dict()["provenance"]
                for field, value in normalized_values.items()
            },
            "normalization_status": {
                field: value.status.value for field, value in normalized_values.items()
            },
        }
    )
    return source_metadata


def run_document_pipeline(
    *,
    input_path: str | Path,
    document_id: str,
    metadata: Mapping[str, Any],
    normalization_catalog: NormalizationCatalog,
    normalization_values: Mapping[str, object],
    output_dir: str | Path,
    normalization_namespaces: Mapping[str, str] | None = None,
    converter: Any | None = None,
    ingest_fn: Callable[..., Any] | None = None,
    publish_status: str = "draft",
    is_current: bool = False,
) -> DocumentPipelineResult:
    """Run WP10C through the existing converter and ingest contracts.

    ``converter`` and ``ingest_fn`` are injectable solely for contract tests;
    production callers should leave them unset so the established
    ``FileConverter`` and ``src.ingest.ingest_document`` are used.
    """
    source_path = Path(input_path)
    if not source_path.is_file():
        raise DocumentPipelineError("INPUT_NOT_FOUND", "input document is unavailable")

    content = source_path.read_bytes()
    route_plan = detect_document(
        document_id=document_id,
        filename=source_path.name,
        content=content,
    )

    normalized_values_result = normalize_record(
        normalization_values,
        normalization_catalog,
        namespaces=normalization_namespaces,
    )
    non_publishable = [
        field
        for field, value in normalized_values_result.items()
        if not value.publishable
    ]
    if non_publishable:
        fields = ",".join(non_publishable)
        raise DocumentPipelineError(
            "NORMALIZATION_NOT_PUBLISHABLE",
            f"normalization did not resolve fields: {fields}",
        )

    document_metadata = dict(metadata)
    document_metadata["document_id"] = document_id
    document_version = resolve_document_version(document_metadata)
    package_metadata = build_package_metadata(
        document_id=document_id,
        document_version=document_version,
        content_hash=_content_hash(content),
        publish_status=publish_status,
        is_current=is_current,
    )

    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"{document_id}.md"
    sidecar_path = output_root / f"{document_id}.source.json"

    if converter is None:
        from .converter import FileConverter

        converter = FileConverter()
    converted = converter.convert_file(str(source_path), str(output_path))
    if not isinstance(converted, Mapping) or converted.get("status") != "success":
        raise DocumentPipelineError("CONVERSION_FAILED", "existing converter did not complete")

    source_metadata = _build_source_metadata(
        metadata=document_metadata,
        route_plan=route_plan,
        normalized_values=normalized_values_result,
        package_metadata=package_metadata,
    )
    sidecar_path.write_text(
        json.dumps(source_metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if ingest_fn is None:
        from .ingest import ingest_document

        ingest_fn = ingest_document
    ingest_result = ingest_fn(
        str(output_path),
        enable_vector=True,
        extraction_mode="report",
        preserve_assets=True,
    )
    if ingest_result is False:
        raise DocumentPipelineError("INGEST_FAILED", "existing ingest returned failure")

    return DocumentPipelineResult(
        route_plan=route_plan,
        normalized_values=normalized_values_result,
        package_metadata=package_metadata,
        source_metadata_path=str(sidecar_path),
        converted_output_path=str(output_path),
        ingest_result=ingest_result,
    )
