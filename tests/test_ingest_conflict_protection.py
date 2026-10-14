from pathlib import Path

import pytest
from openpyxl import Workbook

from src.ingest_conflict_protection import (
    IngestContractError,
    build_document_id,
    build_idempotency_key,
    read_km_metadata,
    validate_ingest_file,
)
from src.ingest_registry import IngestRegistry, IngestRegistryConflict


def test_csit_pull_registry_tracks_revision_without_delete_on_absence(tmp_path):
    registry = IngestRegistry(tmp_path / "registry.sqlite3")
    discovered = registry.record_csit_pull(
        document_id="doc-1", file_id="file-1", document_version="1",
        sha256="a" * 64, status="discovered",
    )
    assert discovered["status"] == "discovered"
    ingested = registry.record_csit_pull(
        document_id="doc-1", file_id="file-1", document_version="1",
        sha256="a" * 64, status="ingested",
    )
    assert ingested["status"] == "ingested"
    assert ingested["ingested_at"]
    assert registry.find_csit_pull("doc-1", "file-1", "1")["document_id"] == "doc-1"
from src.knowledge_package import (
    build_chunk_id,
    build_package_id,
    build_package_metadata,
    resolve_document_version,
)


def _identity() -> dict[str, str]:
    return {
        "sourceSystem": "anritsu",
        "environmentId": "env-local",
        "projectId": "project-1",
        "runId": "run-001",
        "artifactType": "single",
        "reportSchema": "1.0",
        "originalFileName": "report.xlsx",
        "sourceFileHash": "a" * 64,
        "generatedAt": "2026-08-03T00:00:00Z",
    }


def test_identity_derivation_is_deterministic():
    metadata = _identity()
    metadata["documentId"] = build_document_id("4g5g", metadata)
    metadata["idempotencyKey"] = build_idempotency_key(metadata)
    assert metadata["documentId"] == "4g5g:anritsu:env-local:run-001:single"
    assert len(metadata["idempotencyKey"]) == 64
    assert build_idempotency_key(metadata) == metadata["idempotencyKey"]


def test_knowledge_package_revision_and_chunk_ids_are_deterministic():
    package = build_package_metadata(document_id="doc-1", document_version="2.0.0", content_hash="a" * 64)
    assert package["package_schema_version"] == "1.0"
    assert package["publish_status"] == "draft"
    assert package["is_current"] is False
    assert package["package_id"] == build_package_id("doc-1", "2.0.0")
    assert build_chunk_id("doc-1", "2.0.0", 0, "same") == build_chunk_id("doc-1", "2.0.0", 0, "same")
    assert build_chunk_id("doc-1", "1.0.0", 0, "same") != build_chunk_id("doc-1", "2.0.0", 0, "same")


def test_document_version_requires_explicit_numeric_shape():
    assert resolve_document_version({}) == "1.0.0"
    assert resolve_document_version({"documentVersion": "2"}) == "2"
    with pytest.raises(ValueError):
        resolve_document_version({"document_version": "latest"})


def test_package_status_rejects_unknown_values():
    with pytest.raises(ValueError):
        build_package_metadata(document_id="doc-1", document_version="1.0.0", publish_status="archived")


def test_current_revision_must_be_published():
    with pytest.raises(ValueError):
        build_package_metadata(
            document_id="doc-1",
            document_version="1.0.0",
            publish_status="draft",
            is_current=True,
        )


def test_package_publish_transaction_supersedes_previous_current_revision(tmp_path: Path):
    registry = IngestRegistry(tmp_path / "registry.sqlite3")
    first = registry.register_package_revision(
        package_id="package-v1",
        document_id="doc-1",
        document_version="1.0.0",
        content_hash="a" * 64,
    )
    assert first["publish_status"] == "draft"
    registry.mark_package_ready("package-v1")
    assert registry.publish_package_revision("package-v1")["is_current"] == 1

    registry.register_package_revision(
        package_id="package-v2",
        document_id="doc-1",
        document_version="2.0.0",
        content_hash="b" * 64,
    )
    registry.mark_package_ready("package-v2")
    published = registry.publish_package_revision("package-v2")
    assert published["publish_status"] == "published"
    assert published["is_current"] == 1
    revisions = registry.list_package_revisions("doc-1")
    assert [(r["document_version"], r["publish_status"], r["is_current"]) for r in revisions] == [
        ("1.0.0", "superseded", 0),
        ("2.0.0", "published", 1),
    ]


def test_package_publish_requires_ready_and_rejects_duplicate_revision(tmp_path: Path):
    registry = IngestRegistry(tmp_path / "registry.sqlite3")
    registry.register_package_revision(
        package_id="package-v1", document_id="doc-1", document_version="1.0.0"
    )
    with pytest.raises(IngestRegistryConflict) as error:
        registry.publish_package_revision("package-v1")
    assert error.value.code == "invalid_package_transition"
    with pytest.raises(IngestRegistryConflict) as error:
        registry.register_package_revision(
            package_id="other", document_id="doc-1", document_version="1.0.0"
        )
    assert error.value.code == "package_revision_conflict"


def test_registry_deduplicates_and_rejects_document_overwrite(tmp_path: Path):
    registry = IngestRegistry(tmp_path / "registry.sqlite3")
    metadata = _identity()
    metadata["documentId"] = build_document_id("4g5g", metadata)
    metadata["ingestFileHash"] = "b" * 64
    metadata["idempotencyKey"] = build_idempotency_key(metadata)
    identity = {
        "source_system": metadata["sourceSystem"],
        "environment_id": metadata["environmentId"],
        "project_id": metadata["projectId"],
        "run_id": metadata["runId"],
        "artifact_type": metadata["artifactType"],
        "report_schema": metadata["reportSchema"],
        "original_file_name": metadata["originalFileName"],
        "source_file_hash": metadata["sourceFileHash"],
        "ingest_file_hash": metadata["ingestFileHash"],
        "document_id": metadata["documentId"],
        "idempotency_key": metadata["idempotencyKey"],
        "generated_at": metadata["generatedAt"],
    }

    first, duplicate = registry.register(identity, "task-1")
    assert duplicate is False
    second, duplicate = registry.register(identity, "task-2")
    assert duplicate is True
    assert second["task_id"] == first["task_id"] == "task-1"

    different = dict(identity, idempotency_key="c" * 64)
    with pytest.raises(IngestRegistryConflict) as conflict:
        registry.register(different, "task-3")
    assert conflict.value.code == "document_conflict"


def test_km_metadata_sheet_is_read_without_filename_assumptions(tmp_path: Path):
    path = tmp_path / "report.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "KM_Metadata"
    sheet.append(["key", "value"])
    sheet.append(["sourceSystem", "amarisoft"])
    sheet.append(["runId", "run-2"])
    workbook.save(path)
    assert read_km_metadata(path)["sourceSystem"] == "amarisoft"


def test_missing_identity_headers_are_explicit(tmp_path: Path):
    path = tmp_path / "report.xlsx"
    workbook = Workbook()
    workbook.active.title = "KM_Metadata"
    workbook.save(path)
    with pytest.raises(IngestContractError) as error:
        validate_ingest_file(path=path, headers={}, extraction_mode="4g5g")
    assert error.value.code == "headers_missing"


def test_ingest_hash_is_server_generated_without_circular_metadata(tmp_path: Path):
    path = tmp_path / "report.xlsx"
    metadata = _identity()
    metadata["documentId"] = build_document_id("4g5g", metadata)
    metadata["idempotencyKey"] = build_idempotency_key(metadata)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "KM_Metadata"
    sheet.append(["key", "value"])
    for key, value in metadata.items():
        sheet.append([key, value])
    workbook.save(path)
    headers = {
        "Authorization": "Bearer test",
        "Idempotency-Key": metadata["idempotencyKey"],
        "X-KB-Source-System": metadata["sourceSystem"],
        "X-KB-Environment-Id": metadata["environmentId"],
        "X-KB-Run-Id": metadata["runId"],
        "X-KB-Artifact-Type": metadata["artifactType"],
        "X-KB-Document-Id": metadata["documentId"],
    }
    identity = validate_ingest_file(path=path, headers=headers, extraction_mode="4g5g", original_file_name="ANRITSU__envelope__report.xlsx")
    assert len(identity.ingest_file_hash) == 64
