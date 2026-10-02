from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx

from src.csit.ingest import CsitManifestIngestor
from src.csit.manifest import importable_entries, parse_manifest
from src.document_normalization import NormalizationCatalog
from src.ingest_registry import IngestRegistry


FIXTURE = Path(__file__).parent / "fixtures/csit_km_uat_manifest.json"


def _catalog() -> NormalizationCatalog:
    return NormalizationCatalog.from_dict({})


def test_fixed_uat_fixture_enforces_report_lifecycle_and_expected_revisions():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    parsed = parse_manifest(payload)
    importable = importable_entries(payload)
    assert {entry.file_id for entry in importable} == set(payload["expected_importable"])
    assert {entry.file_id for entry in parsed if not entry.importable} == set(payload["expected_excluded"])


def test_manifest_ingestor_verifies_size_hash_uses_existing_pipeline_and_is_idempotent(tmp_path):
    content = b"controlled-uAT!"  # 15 bytes
    entry_payload = {
        "source": "CSIT", "moduleCode": "UAT", "documentId": "doc-1", "fileId": "file-1",
        "projectId": "project-1", "caseId": "case-1", "taskId": "task-1", "fileName": "../report.txt",
        "fileKind": "Attachment", "version": 1, "reviewStatus": "Pending", "isFinal": False,
        "contentType": "text/plain", "fileSize": len(content), "sha256": hashlib.sha256(content).hexdigest(),
        "uploadedBy": "uat", "uploadedAt": "2026-09-18T00:00:00Z", "finalizedAt": "",
        "relativePath": "uat/report.txt",
    }
    entry = parse_manifest([entry_payload])[0]
    registry = IngestRegistry(tmp_path / "registry.sqlite3")
    calls = []

    class FakeClient:
        def download(self, path, *, path_params):
            assert path == "/api/files/{fileId}/download"
            assert path_params == {"fileId": "file-1"}
            return httpx.Response(200, content=content)

    def fake_pipeline(**kwargs):
        calls.append(kwargs)
        assert kwargs["metadata"]["csit_file_id"] == "file-1"
        assert kwargs["publish_status"] == "published"
        return {"status": "accepted"}

    ingestor = CsitManifestIngestor(
        FakeClient(), registry,
        staging_dir=tmp_path / "staging",
        output_dir=tmp_path / "output",
        normalization_catalog=_catalog(),
        pipeline_fn=fake_pipeline,
    )
    first = ingestor.ingest_one(entry)
    second = ingestor.ingest_one(entry)

    assert first.status == "ingested"
    assert second.status == "already_ingested"
    assert len(calls) == 1
    assert Path(first.staged_path).parent == tmp_path / "staging" / first.staged_path.split("/")[-2]
    assert ".." not in Path(first.staged_path).name
    assert registry.find_csit_pull("doc-1", "file-1", "1")["status"] == "ingested"
    assert registry.list_package_revisions("doc-1")[0]["publish_status"] == "published"
    assert registry.list_package_revisions("doc-1")[0]["is_current"] == 0


def test_manifest_ingestor_supersedes_previous_final_report_revision(tmp_path):
    entries = []
    for version in (1, 2):
        content = f"report-{version}".encode("utf-8")
        entries.append(parse_manifest([{
            "source": "CSIT", "moduleCode": "UAT", "documentId": "doc-r", "fileId": f"file-{version}",
            "projectId": "project-1", "caseId": "case-1", "taskId": "task-1", "fileName": f"r{version}.txt",
            "fileKind": "TestReport", "version": version, "reviewStatus": "Approved", "isFinal": True,
            "contentType": "text/plain", "fileSize": len(content), "sha256": hashlib.sha256(content).hexdigest(),
            "uploadedBy": "uat", "uploadedAt": "2026-09-18T00:00:00Z", "finalizedAt": "2026-09-18T00:01:00Z",
            "relativePath": f"uat/r{version}.txt",
        }])[0])

    class FakeClient:
        def __init__(self):
            self.entry = entries[0]

        def download(self, _path, *, path_params):
            assert path_params["fileId"] == self.entry.file_id
            return httpx.Response(200, content=f"report-{self.entry.version}".encode("utf-8"))

    client = FakeClient()
    registry = IngestRegistry(tmp_path / "registry.sqlite3")
    ingestor = CsitManifestIngestor(
        client, registry, staging_dir=tmp_path / "staging", output_dir=tmp_path / "output",
        normalization_catalog=_catalog(), pipeline_fn=lambda **_: {"status": "accepted"},
    )
    ingestor.ingest_one(entries[0])
    client.entry = entries[1]
    ingestor.ingest_one(entries[1])

    assert [
        (row["document_version"], row["publish_status"], row["is_current"])
        for row in registry.list_package_revisions("doc-r")
    ] == [("1", "superseded", 0), ("2", "published", 1)]
