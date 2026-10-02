"""Controlled CSIT KM manifest download and ingest orchestration.

This module is the KM-owned boundary after the dedicated manifest Pull.  It
does not infer lifecycle state, access CSIT storage, or write databases
directly.  Downloads are hash/size verified, staged below a caller-owned
directory, and handed to the existing document pipeline.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ..document_normalization import NormalizationCatalog
from ..document_pipeline import DocumentPipelineResult, run_document_pipeline
from ..ingest_registry import IngestRegistry
from ..knowledge_package import build_package_id
from .manifest import CsitManifestEntry, CsitManifestError, verify_download_hash


class CsitManifestIngestError(RuntimeError):
    """Stable, fail-closed error for one CSIT manifest entry."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class CsitManifestIngestResult:
    entry: CsitManifestEntry
    status: str
    staged_path: str | None = None
    pipeline_result: DocumentPipelineResult | Any | None = None
    error_code: str = ""


def _safe_filename(filename: str, fallback: str) -> str:
    """Return a basename only; CSIT metadata never controls a parent path."""
    name = Path(str(filename or "")).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or fallback


def _safe_identity(value: str) -> str:
    """Use a stable opaque directory name for external IDs."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


class CsitManifestIngestor:
    """Download and ingest eligible CSIT entries through existing KM code.

    ``pipeline_fn`` is injectable for isolated contract tests.  Production
    callers leave it unset, which delegates to ``run_document_pipeline`` and
    therefore preserves the existing converter/chunker/vector/graph path.
    """

    def __init__(
        self,
        client: Any,
        registry: IngestRegistry,
        *,
        staging_dir: str | Path,
        output_dir: str | Path,
        normalization_catalog: NormalizationCatalog,
        normalization_values: Mapping[str, object] | None = None,
        normalization_namespaces: Mapping[str, str] | None = None,
        pipeline_fn: Callable[..., Any] | None = None,
    ) -> None:
        self.client = client
        self.registry = registry
        self.staging_dir = Path(staging_dir)
        self.output_dir = Path(output_dir)
        self.normalization_catalog = normalization_catalog
        self.normalization_values = dict(normalization_values or {})
        self.normalization_namespaces = dict(normalization_namespaces or {})
        self.pipeline_fn = pipeline_fn or run_document_pipeline

    def ingest_one(self, entry: CsitManifestEntry) -> CsitManifestIngestResult:
        """Process one manifest entry; never import an ineligible revision."""
        if not entry.importable:
            raise CsitManifestIngestError("NOT_IMPORTABLE", "CSIT lifecycle does not permit KM import")

        existing = self.registry.find_csit_pull(entry.document_id, entry.file_id, entry.version)
        if existing and existing["status"] == "ingested" and existing["sha256"] == entry.sha256:
            return CsitManifestIngestResult(entry=entry, status="already_ingested")

        identity = {
            "document_id": entry.document_id,
            "file_id": entry.file_id,
            "document_version": entry.version,
            "sha256": entry.sha256,
        }
        self.registry.record_csit_pull(**identity, status="discovered")
        staged_path: Path | None = None
        package_id = build_package_id(entry.document_id, entry.version)
        package = self.registry.find_package_revision(package_id)
        if package is None:
            package = self.registry.register_package_revision(
                package_id=package_id,
                document_id=entry.document_id,
                document_version=entry.version,
                content_hash=entry.sha256,
            )
        try:
            response = self.client.download(
                "/api/files/{fileId}/download",
                path_params={"fileId": entry.file_id},
            )
            try:
                content = bytes(response.content)
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
            verify_download_hash(content, entry)
            if len(content) != entry.file_size:
                raise CsitManifestError(
                    f"下載檔案大小不符: expected={entry.file_size}, actual={len(content)}"
                )

            document_dir = self.staging_dir / _safe_identity(entry.document_id)
            document_dir.mkdir(parents=True, exist_ok=True)
            filename = _safe_filename(entry.file_name, f"{entry.file_id}.bin")
            staged_path = document_dir / f"{_safe_identity(entry.file_id)}-{_safe_filename(entry.version, 'version')}-{filename}"
            staged_path.write_bytes(content)
            self.registry.record_csit_pull(**identity, status="downloaded")

            metadata = entry.to_source_metadata()
            pipeline_result = self.pipeline_fn(
                input_path=staged_path,
                document_id=entry.document_id,
                metadata=metadata,
                normalization_catalog=self.normalization_catalog,
                normalization_values=self.normalization_values,
                normalization_namespaces=self.normalization_namespaces,
                output_dir=self.output_dir / _safe_identity(entry.document_id),
                publish_status="published" if entry.importable else "draft",
                is_current=entry.file_kind == "TestReport" and entry.importable,
            )
            package = self.registry.find_package_revision(package_id)
            if package and package["publish_status"] == "draft":
                self.registry.mark_package_ready(package_id)
                self.registry.publish_package_revision(
                    package_id,
                    is_current=entry.file_kind == "TestReport" and entry.importable,
                )
            elif package and package["publish_status"] == "ready":
                self.registry.publish_package_revision(
                    package_id,
                    is_current=entry.file_kind == "TestReport" and entry.importable,
                )
            self.registry.record_csit_pull(**identity, status="ingested")
            return CsitManifestIngestResult(
                entry=entry,
                status="ingested",
                staged_path=str(staged_path),
                pipeline_result=pipeline_result,
            )
        except (CsitManifestError, CsitManifestIngestError) as exc:
            code = getattr(exc, "code", "MANIFEST_VALIDATION_FAILED")
            self.registry.record_csit_pull(**identity, status="failed", error=code)
            raise CsitManifestIngestError(code, str(exc)) from exc
        except Exception as exc:
            self.registry.record_csit_pull(
                **identity,
                status="failed",
                error=type(exc).__name__,
            )
            raise CsitManifestIngestError("PIPELINE_FAILED", type(exc).__name__) from exc
