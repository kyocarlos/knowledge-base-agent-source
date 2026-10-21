import hashlib

import pytest

from src.csit.manifest import CsitManifestError, importable_entries, normalize_file_contract, parse_manifest, verify_download_hash


def entry(**overrides):
    value = {
        "source": "CSIT", "moduleCode": "M1", "documentId": "doc-1", "fileId": "file-1",
        "projectId": "project-1", "projectNo": "P1", "caseId": "case-1", "caseNo": "C1",
        "taskId": "task-1", "taskNo": "T1", "fileName": "report.txt", "fileKind": "TestReport",
        "version": 1, "reviewStatus": "Approved", "isFinal": True, "contentType": "text/plain",
        "fileSize": 4, "sha256": "a" * 64, "uploadedBy": "tester", "uploadedAt": "2026-09-17T00:00:00Z",
        "finalizedAt": "2026-09-17T00:00:00Z", "relativePath": "reports/report.txt",
    }
    value.update(overrides)
    return value


def test_only_approved_final_report_is_importable():
    result = importable_entries([entry(), entry(documentId="doc-2", fileId="file-2", reviewStatus="Rejected", isFinal=False)])
    assert [(item.document_id, item.file_id) for item in result] == [("doc-1", "file-1")]
    assert result[0].to_source_metadata()["publish_status"] == "published"


def test_attachment_is_importable_without_report_approval():
    result = importable_entries([entry(fileKind="Attachment", documentId="doc-a", fileId="file-a", reviewStatus="Pending", isFinal=False)])
    assert result[0].file_kind == "Attachment"
    assert result[0].to_source_metadata()["is_current"] is False


def test_manifest_rejects_traversal_and_duplicate_revision():
    with pytest.raises(CsitManifestError, match="traversal"):
        parse_manifest([entry(relativePath="../report.txt")])
    with pytest.raises(CsitManifestError, match="重複"):
        parse_manifest([entry(), entry()])
    with pytest.raises(CsitManifestError, match="version"):
        parse_manifest([entry(version="latest")])


def test_download_hash_is_fail_closed():
    content = b"test"
    valid = entry(sha256=hashlib.sha256(content).hexdigest(), fileSize=len(content))
    verify_download_hash(content, parse_manifest([valid])[0])
    with pytest.raises(CsitManifestError, match="SHA-256"):
        verify_download_hash(b"other", parse_manifest([valid])[0])


def test_confirmed_dto_aliases_normalize_but_internal_paths_are_dropped():
    normalized = normalize_file_contract(
        {"id": "file-1", "versionNo": 2, "createdAt": "2026-09-18T00:00:00Z", "filePath": "D:\\\\secret.xlsx"},
        {"projectId": "p1"},
    )
    assert normalized["fileId"] == "file-1"
    assert normalized["version"] == 2
    assert normalized["uploadedAt"] == "2026-09-18T00:00:00Z"
    assert normalized["projectId"] == "p1"
    assert "filePath" not in normalized
    assert "relativePath" not in normalized
