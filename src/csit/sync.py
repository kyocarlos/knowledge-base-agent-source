"""Reusable KM-side CSIT manifest synchronization service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from ..document_normalization import NormalizationCatalog
from ..ingest_registry import IngestRegistry
from .ingest import CsitManifestIngestError, CsitManifestIngestor
from .pull import CsitTraversalPuller


@dataclass(frozen=True, slots=True)
class CsitSyncResult:
    """Sanitized result suitable for a task result or an audit artifact."""

    mode: str
    modules_seen: int
    records_seen: int
    projects_pulled: int
    eligible_entries: int
    ingested: int
    already_ingested: int
    failed: int
    skipped: tuple[dict[str, str], ...]
    entry_results: tuple[dict[str, str], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "modules_seen": self.modules_seen,
            "records_seen": self.records_seen,
            "projects_pulled": self.projects_pulled,
            "eligible_entries": self.eligible_entries,
            "ingested": self.ingested,
            "already_ingested": self.already_ingested,
            "failed": self.failed,
            "skipped": [dict(item) for item in self.skipped],
            "entry_results": [dict(item) for item in self.entry_results],
        }


def sync_csit_manifest(
    client: Any,
    *,
    registry: IngestRegistry | None = None,
    execute: bool = False,
    module_codes: Iterable[str] | None = None,
    page_size: int = 50,
    max_pages: int = 100,
    staging_dir: str = "data/staging/csit-km",
    output_dir: str = "data/processed/csit-km",
    normalization_catalog: NormalizationCatalog | None = None,
    normalization_values: Mapping[str, object] | None = None,
    normalization_namespaces: Mapping[str, str] | None = None,
    pipeline_fn: Callable[..., Any] | None = None,
) -> CsitSyncResult:
    """Pull manifests and optionally run the existing KM ingest pipeline.

    ``execute=False`` still performs the read-only Project/Manifest Pull but
    never downloads a file or writes the KM registry/stores.  Execution is
    explicit and requires a registry so callers cannot accidentally run a
    partial write path.
    """
    if execute and registry is None:
        raise ValueError("registry is required when execute=True")
    pulled = CsitTraversalPuller(client, page_size=page_size, max_pages=max_pages).pull(
        module_codes=set(module_codes or ()) or None
    )
    if not execute:
        return CsitSyncResult(
            mode="dry-run",
            modules_seen=pulled.modules_seen,
            records_seen=pulled.records_seen,
            projects_pulled=pulled.projects_pulled,
            eligible_entries=len(pulled.entries),
            ingested=0,
            already_ingested=0,
            failed=0,
            skipped=pulled.skipped,
            entry_results=tuple(
                {
                    "documentId": entry.document_id,
                    "fileId": entry.file_id,
                    "version": entry.version,
                    "status": "eligible",
                }
                for entry in pulled.entries
            ),
        )

    assert registry is not None
    ingestor = CsitManifestIngestor(
        client,
        registry,
        staging_dir=staging_dir,
        output_dir=output_dir,
        normalization_catalog=normalization_catalog or NormalizationCatalog.from_dict({}),
        normalization_values=normalization_values,
        normalization_namespaces=normalization_namespaces,
        pipeline_fn=pipeline_fn,
    )
    results: list[dict[str, str]] = []
    ingested = already_ingested = failed = 0
    for entry in pulled.entries:
        try:
            result = ingestor.ingest_one(entry)
            results.append({"documentId": entry.document_id, "fileId": entry.file_id, "version": entry.version, "status": result.status})
            if result.status == "already_ingested":
                already_ingested += 1
            else:
                ingested += 1
        except CsitManifestIngestError as exc:
            failed += 1
            results.append({"documentId": entry.document_id, "fileId": entry.file_id, "version": entry.version, "status": "failed", "error_code": exc.code})

    return CsitSyncResult(
        mode="execute",
        modules_seen=pulled.modules_seen,
        records_seen=pulled.records_seen,
        projects_pulled=pulled.projects_pulled,
        eligible_entries=len(pulled.entries),
        ingested=ingested,
        already_ingested=already_ingested,
        failed=failed,
        skipped=pulled.skipped,
        entry_results=tuple(results),
    )
