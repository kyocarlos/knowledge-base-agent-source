from __future__ import annotations

import hashlib

import httpx

from src.csit import sync_csit_manifest
from src.document_normalization import NormalizationCatalog
from src.ingest_registry import IngestRegistry


def _payload():
    content = b"sync-test"
    return [{
        "source": "CSIT", "moduleCode": "M1", "documentId": "doc-sync", "fileId": "file-sync",
        "projectId": "project-1", "fileName": "sync.txt", "fileKind": "Attachment", "version": 1,
        "reviewStatus": "Pending", "isFinal": False, "contentType": "text/plain", "fileSize": len(content),
        "sha256": hashlib.sha256(content).hexdigest(), "uploadedBy": "uat",
        "uploadedAt": "2026-09-18T00:00:00Z", "finalizedAt": None, "relativePath": "uat/sync.txt",
    }]


class FakeClient:
    def __init__(self):
        self.downloads = 0

    def get(self, path, *, path_params=None, query=None):
        if path == "/api/modules/enabled":
            return {"items": [{"code": "M1"}]}
        assert path == "/api/modules/{moduleCode}/records"
        return {"items": [{"id": "project-1"}]}

    def get_km_manifest(self, project_id):
        assert project_id == "project-1"
        return {"items": _payload()}

    def download(self, path, *, path_params):
        self.downloads += 1
        assert path == "/api/files/{fileId}/download"
        return httpx.Response(200, content=b"sync-test")


def test_sync_service_dry_run_never_downloads_or_writes(tmp_path):
    client = FakeClient()
    result = sync_csit_manifest(client)
    assert result.as_dict()["mode"] == "dry-run"
    assert result.eligible_entries == 1
    assert client.downloads == 0


def test_sync_service_execute_returns_sanitized_batch_summary(tmp_path):
    client = FakeClient()
    registry = IngestRegistry(tmp_path / "registry.sqlite3")
    result = sync_csit_manifest(
        client,
        registry=registry,
        execute=True,
        staging_dir=str(tmp_path / "staging"),
        output_dir=str(tmp_path / "output"),
        normalization_catalog=NormalizationCatalog.from_dict({}),
        pipeline_fn=lambda **_: {"status": "accepted"},
    )
    assert result.ingested == 1
    assert result.failed == 0
    assert result.entry_results[0]["status"] == "ingested"
    assert client.downloads == 1
