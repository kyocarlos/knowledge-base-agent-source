"""Validate and select the CSIT ``km-manifest.json`` contract.

The manifest is a CSIT-owned inventory.  This module deliberately does not
download files or write Neo4j/Qdrant; it only validates identity/lifecycle
metadata and returns safe candidates for the existing KM ingest adapter.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping


class CsitManifestError(ValueError):
    """Raised when a CSIT manifest is malformed or unsafe."""


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _value(item: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in item:
            return item[name]
    return None


def _required(item: Mapping[str, Any], *names: str) -> str:
    value = _value(item, *names)
    result = str(value or "").strip()
    if not result:
        raise CsitManifestError(f"manifest 欠缺必要欄位: {names[0]}")
    return result


def _bool(item: Mapping[str, Any], *names: str) -> bool:
    value = _value(item, *names)
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "1", "yes"}:
        return True
    if isinstance(value, str) and value.strip().lower() in {"false", "0", "no"}:
        return False
    raise CsitManifestError(f"manifest 欄位必須是 boolean: {names[0]}")


def _non_negative_integer(item: Mapping[str, Any], *names: str) -> int:
    value = _value(item, *names)
    if isinstance(value, bool):
        raise CsitManifestError(f"manifest 欄位必須是非負整數: {names[0]}")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise CsitManifestError(f"manifest 欄位必須是非負整數: {names[0]}") from exc
    if str(value).strip() != str(result) and not isinstance(value, int):
        raise CsitManifestError(f"manifest 欄位必須是非負整數: {names[0]}")
    if result < 0:
        raise CsitManifestError(f"manifest 欄位必須是非負整數: {names[0]}")
    return result


def normalize_file_contract(item: Mapping[str, Any], context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Map confirmed CSIT DTO aliases to formal KM V1 field names.

    Internal path fields are intentionally ignored; ``relativePath`` must
    come from the KM contract and is never derived from a server-local path.
    """
    normalized = {**(context or {}), **dict(item)}
    aliases = {"fileId": ("id",), "version": ("versionNo",), "uploadedAt": ("createdAt",)}
    for canonical, candidates in aliases.items():
        if str(normalized.get(canonical) or "").strip():
            continue
        for candidate in candidates:
            if str(normalized.get(candidate) or "").strip():
                normalized[canonical] = normalized[candidate]
                break
    for internal_path in ("filePath", "localFilePath", "nasFilePath", "nasFolderPath"):
        normalized.pop(internal_path, None)
    return normalized


@dataclass(frozen=True, slots=True)
class CsitManifestEntry:
    source: str
    module_code: str
    document_id: str
    file_id: str
    project_id: str = ""
    project_no: str = ""
    case_id: str = ""
    case_no: str = ""
    task_id: str = ""
    task_no: str = ""
    file_name: str = ""
    file_kind: str = ""
    version: str = ""
    review_status: str = ""
    is_final: bool = False
    content_type: str = ""
    file_size: int = 0
    sha256: str = ""
    uploaded_by: str = ""
    uploaded_at: str = ""
    finalized_at: str = ""
    relative_path: str = ""

    @classmethod
    def from_dict(cls, item: Mapping[str, Any]) -> "CsitManifestEntry":
        file_size = _non_negative_integer(item, "fileSize")
        version = _non_negative_integer(item, "version", "Version")

        sha256 = _required(item, "sha256", "Sha256").lower()
        if not _SHA256.fullmatch(sha256):
            raise CsitManifestError("manifest sha256 必須是 SHA-256")
        relative_path = _required(item, "relativePath")
        path = PurePosixPath(relative_path)
        if path.is_absolute() or ".." in path.parts or "\\" in relative_path:
            raise CsitManifestError("manifest relativePath 不可包含絕對路徑或 traversal")

        file_kind = _required(item, "fileKind", "FileKind")
        if file_kind not in {"TestReport", "Attachment"}:
            raise CsitManifestError("manifest fileKind 不受支援")
        return cls(
            source=str(_value(item, "source") or "CSIT").strip(),
            module_code=str(_value(item, "moduleCode") or "").strip(),
            document_id=_required(item, "documentId", "document_id"),
            file_id=_required(item, "fileId", "file_id"),
            project_id=str(_value(item, "projectId") or "").strip(),
            project_no=str(_value(item, "projectNo") or "").strip(),
            case_id=str(_value(item, "caseId") or "").strip(),
            case_no=str(_value(item, "caseNo") or "").strip(),
            task_id=str(_value(item, "taskId") or "").strip(),
            task_no=str(_value(item, "taskNo") or "").strip(),
            file_name=str(_value(item, "fileName") or "").strip(),
            file_kind=file_kind,
            version=str(version),
            review_status=_required(item, "reviewStatus", "ReviewStatus"),
            is_final=_bool(item, "isFinal", "IsFinal"),
            content_type=str(_value(item, "contentType") or "").strip(),
            file_size=file_size,
            sha256=sha256,
            uploaded_by=str(_value(item, "uploadedBy") or "").strip(),
            uploaded_at=_required(item, "uploadedAt"),
            finalized_at=str(_value(item, "finalizedAt", "FinalizedAt") or "").strip(),
            relative_path=relative_path,
        )

    @property
    def importable(self) -> bool:
        """Apply Patty's V1 lifecycle rule without changing CSIT state."""
        if self.file_kind == "Attachment":
            return True
        return self.review_status == "Approved" and self.is_final

    def to_source_metadata(self) -> dict[str, Any]:
        """Map the CSIT identity to existing KM source metadata."""
        return {
            "source_system": self.source,
            "source_record_id": self.project_id,
            "source_file_id": self.file_id,
            "document_id": self.document_id,
            "document_version": self.version,
            "csit_document_id": self.document_id,
            "csit_file_id": self.file_id,
            "csit_module_code": self.module_code,
            "csit_project_id": self.project_id,
            "csit_project_no": self.project_no,
            "csit_case_id": self.case_id,
            "csit_case_no": self.case_no,
            "csit_task_id": self.task_id,
            "csit_task_no": self.task_no,
            "source_file_name": self.file_name,
            "artifact_type": "test_report" if self.file_kind == "TestReport" else "attachment",
            "approval_status": self.review_status,
            "publish_status": "published" if self.importable else "draft",
            "is_current": self.importable and self.file_kind == "TestReport",
            "source_file_hash": self.sha256,
            "content_type": self.content_type,
            "relative_path": self.relative_path,
        }


def _entries(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("items", "entries", "documents", "files", "manifest"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, Mapping)]
        return [payload]
    raise CsitManifestError("manifest 必須是 JSON object 或 array")


def parse_manifest(payload: Any) -> tuple[CsitManifestEntry, ...]:
    """Validate all entries and enforce unique revision identity."""
    result = tuple(CsitManifestEntry.from_dict(item) for item in _entries(payload))
    if not result:
        raise CsitManifestError("manifest 不可為空")
    identities = [(item.document_id, item.file_id, item.version) for item in result]
    if len(set(identities)) != len(identities):
        raise CsitManifestError("manifest 含重複的 DocumentId/FileId/Version")
    current_reports = [item for item in result if item.file_kind == "TestReport" and item.importable]
    current_by_document: dict[str, int] = {}
    for item in current_reports:
        current_by_document[item.document_id] = current_by_document.get(item.document_id, 0) + 1
    if any(count > 1 for count in current_by_document.values()):
        raise CsitManifestError("同一 DocumentId 不可同時存在多個 Current Final TestReport")
    return result


def importable_entries(payload: Any) -> tuple[CsitManifestEntry, ...]:
    """Return only entries eligible for the first KM Pull import."""
    return tuple(item for item in parse_manifest(payload) if item.importable)


def verify_download_hash(content: bytes, entry: CsitManifestEntry) -> None:
    """Fail closed if the downloaded file is not the CSIT manifest artifact."""
    actual = hashlib.sha256(content).hexdigest()
    if actual != entry.sha256:
        raise CsitManifestError(f"下載檔案 SHA-256 不符: {entry.file_id}")
