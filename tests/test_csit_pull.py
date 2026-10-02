import hashlib

from src.csit.pull import CsitTraversalPuller
from src.csit import KM_MANIFEST_PATH


def file_item(file_id="f1", document_id="d1", version=1, file_kind="TestReport"):
    return {
        "fileId": file_id,
        "documentId": document_id,
        "version": version,
        "fileKind": file_kind,
        "reviewStatus": "Approved" if file_kind == "TestReport" else "Pending",
        "isFinal": file_kind == "TestReport",
        "sha256": hashlib.sha256(b"data").hexdigest(),
        "fileSize": 4,
        "uploadedAt": "2026-09-18T00:00:00Z",
        "finalizedAt": "2026-09-18T00:00:00Z" if file_kind == "TestReport" else None,
        "relativePath": "reports/report.txt",
    }


class FakeClient:
    def __init__(self):
        self.calls = []

    def get(self, path, *, path_params=None, query=None):
        self.calls.append((path, path_params, query))
        values = {
            "/api/modules/enabled": {"items": [{"code": "M1"}]},
            "/api/modules/{moduleCode}/records": {"items": [{"id": "p1", "recordNo": "P1"}]},
            "/api/records/{id}": {"id": "p1", "projectNo": "P1"},
            "/api/records/{recordId}/cases": {"items": [{"id": "c1", "caseNo": "C1"}]},
            "/api/cases/{id}": {"id": "c1", "caseNo": "C1"},
            "/api/cases/{caseId}/files": {"items": [file_item("fa", "da", 1, "Attachment")]},
            "/api/cases/{caseId}/tasks": {"items": [{"id": "t1", "taskNo": "T1"}]},
            "/api/tasks/{id}": {"id": "t1", "taskNo": "T1"},
            "/api/tasks/{taskId}/files": {"items": [file_item()]},
        }
        return values[path]

    def get_km_manifest(self, project_id):
        assert project_id == "p1"
        return {"items": [file_item()]}


def test_traversal_pulls_only_dedicated_project_manifest():
    client = FakeClient()
    result = CsitTraversalPuller(client).pull()

    assert {(item.document_id, item.file_id) for item in result.entries} == {("d1", "f1")}
    assert result.modules_seen == 1
    assert result.records_seen == result.projects_pulled == 1
    assert all("files" not in path for path, _, _ in client.calls)
    assert KM_MANIFEST_PATH == "/api/km/v1/projects/{projectId}/manifest"


def test_missing_core_metadata_is_skipped_fail_closed():
    client = FakeClient()
    client.get_km_manifest = lambda project_id: {"items": [{"fileId": "missing", "fileKind": "TestReport"}]}
    result = CsitTraversalPuller(client).pull()
    assert len(result.entries) == 0
    assert any(item["stage"] == "manifest" for item in result.skipped)
