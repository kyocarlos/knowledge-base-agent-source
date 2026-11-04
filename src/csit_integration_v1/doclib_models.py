"""CSIT x AI KM spec v1.3: document-library and deletion wire contracts."""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID
import re
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from .models import safe_filename

class Wire(BaseModel):
    # CSIT may add fields without a schemaVersion bump; unknown keys are ignored, never stored as structure.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

class Level(Wire):
    id: str | int | UUID
    name: Optional[str] = None

class Classification(Wire):
    l1: Optional[Level] = None
    l2: Optional[Level] = None
    l3: Optional[Level] = None

class FileInfo(Wire):
    originalFileName: str = Field(min_length=1, max_length=255)
    standardFileName: Optional[str] = Field(default=None, max_length=255)
    contentType: str = Field(min_length=1, max_length=128)
    fileSizeBytes: StrictInt = Field(ge=0)
    sha256: str
    downloadUrl: Optional[str] = Field(default=None, max_length=2048)
    _name = field_validator("originalFileName", mode="before")(safe_filename)
    @field_validator("sha256")
    @classmethod
    def sha(cls, value):
        value = value.lower()
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("sha256 must be 64 hex characters")
        return value

class DocLibRequest(Wire):
    schemaVersion: Literal["1.0"]
    sourceSystem: Literal["CSIT"]
    eventType: Literal["DocumentLibraryFileUploaded"]
    documentFileId: UUID
    csitJobId: UUID
    occurredAt: datetime
    file: FileInfo
    classification: Classification = Classification()
    @field_validator("occurredAt")
    @classmethod
    def tz(cls, value):
        if value.tzinfo is None:
            raise ValueError("timestamp timezone required")
        return value

class DocLibAccepted(BaseModel):
    csitJobId: UUID
    kmJobId: str
    status: Literal["Accepted"] = "Accepted"

SOURCE_TYPES = ("DocumentLibraryFile", "TestReport", "VerificationApplicationAttachment")

class Resource(Wire):
    sourceType: Literal["DocumentLibraryFile", "TestReport", "VerificationApplicationAttachment"]
    documentFileId: Optional[UUID] = None
    documentId: Optional[UUID] = None
    version: Optional[StrictInt] = None
    sourceEntityId: Optional[UUID] = None
    applicationId: Optional[UUID] = None
    recordId: Optional[UUID] = None
    @model_validator(mode="after")
    def exact_identity(self):
        t = self.sourceType
        if t == "DocumentLibraryFile":
            if self.documentFileId is None or any(x is not None for x in (self.documentId, self.version, self.sourceEntityId)):
                raise ValueError("DocumentLibraryFile needs documentFileId only")
        else:
            if self.documentFileId is not None or self.documentId is None or self.sourceEntityId is None:
                raise ValueError(t + " needs documentId and sourceEntityId")
            if self.version is None or self.version < 1 or (t == "VerificationApplicationAttachment" and self.version != 1):
                raise ValueError("invalid version for " + t)
        return self
    def key(self) -> str:
        """Exact source identity. Never derived from a file or model name."""
        if self.sourceType == "DocumentLibraryFile":
            return str(self.documentFileId)
        return f"{self.documentId}:{self.version}:{self.sourceEntityId}"
    def wire(self) -> dict:
        return {"sourceType": self.sourceType,
                **{k: (str(v) if isinstance(v, UUID) else v) for k, v in self.model_dump().items() if k != "sourceType"}}

class DeletionRequest(Wire):
    schemaVersion: Literal["1.0"]
    sourceSystem: Literal["CSIT"]
    eventType: Literal["DocumentDeletionRequested"]
    deletionRequestId: UUID
    requestedAt: datetime
    reasonCode: str = Field(min_length=1, max_length=128)
    resource: Resource
    @field_validator("requestedAt")
    @classmethod
    def tz(cls, value):
        if value.tzinfo is None:
            raise ValueError("timestamp timezone required")
        return value

class DeletionAccepted(BaseModel):
    deletionRequestId: UUID
    kmDeletionJobId: str
    status: Literal["Accepted"] = "Accepted"

# ---- callbacks KM -> CSIT (spec 4.3, 5, 7.2) ----
DOCUMENT_TYPES = ("Specification", "Manual", "TestReport", "SOP", "MeetingMinutes", "IssueAnalysis", "Presentation", "Other")
CLEANUP_ITEMS = ("metadata", "extractedText", "chunks", "vectorIndex", "graphRelations", "cache", "storedCopies")

_S = {"type": ["string", "null"]}
_SA = {"type": "array", "items": {"type": "string"}}
def _obj(props, required=None):
    return {"type": "object", "properties": props, "required": list(required or props), "additionalProperties": False}

RESULT_SCHEMA = _obj({
    "metadataSchemaVersion": {"const": "1.0"},
    "document": _obj({"title": _S, "documentType": {"enum": list(DOCUMENT_TYPES)}, "summary": _S, "language": _S,
        "documentDate": _S, "authors": _SA, "department": _S, "documentVersionLabel": _S, "keywords": _SA, "tags": _SA}),
    "technical": _obj({**{k: _SA for k in ("productNames", "modelNumbers", "vendorNames", "technologies", "standards",
        "softwareVersions", "hardwareVersions", "projectNames", "testItems", "issueKeys", "errorCodes")},
        "measurements": {"type": "array", "items": _obj({"metric": {"type": "string"}, "value": {"type": ["string", "number"]},
            "unit": _S, "context": _S})}}),
    "extraction": _obj({"sourceFormat": {"type": "string"}, "method": {"enum": ["Text", "OCR", "Mixed"]},
        "pageCount": {"type": ["integer", "null"], "minimum": 0}, "sheetNames": _SA,
        "extractedCharacterCount": {"type": "integer", "minimum": 0}, "ocrUsed": {"type": "boolean"}}),
    "indexing": _obj({"status": {"const": "Completed"}, "indexId": {"type": "string", "minLength": 1},
        "chunkCount": {"type": "integer", "minimum": 0}, "indexedAt": {"type": "string", "minLength": 1}}),
    "warnings": _SA,
})

from jsonschema import Draft202012Validator
_RESULT_VALIDATOR = Draft202012Validator(RESULT_SCHEMA)

def validate_result(result: dict) -> None:
    errors = sorted(_RESULT_VALIDATOR.iter_errors(result), key=lambda e: list(e.path))
    if errors:
        e = errors[0]
        raise ValueError("Completed.result invalid at " + ".".join(str(p) for p in e.path) + ": " + e.message[:120])

def _ts(value) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")

def build_ingestion_callback(callback_id, job, status, *, error=None, result=None) -> dict:
    """job is a km_csit_doclib_jobs row. All three timestamps keys are always present (spec A.1)."""
    payload = {"schemaVersion": "1.0", "callbackId": str(callback_id), "sourceSystem": "CSIT",
        "documentFileId": str(job["document_file_id"]), "csitJobId": str(job["csit_job_id"]), "kmJobId": job["km_job_id"],
        "status": status,
        "timestamps": {"startedAt": _ts(job["started_at"]) if status == "Processing" else None,
                       "completedAt": _ts(job["completed_at"]) if status == "Completed" else None,
                       "failedAt": _ts(job["failed_at"]) if status == "Failed" else None},
        "result": None, "error": None}
    if status == "Processing":
        if payload["timestamps"]["startedAt"] is None:
            raise ValueError("Processing needs startedAt")
    elif status == "Completed":
        if payload["timestamps"]["completedAt"] is None:
            raise ValueError("Completed needs completedAt")
        validate_result(result)
        payload["result"] = result
    elif status == "Failed":
        if error is None or payload["timestamps"]["failedAt"] is None:
            raise ValueError("Failed needs failedAt and error")
        payload["error"] = {"code": error.code, "message": error.message, "retryable": bool(error.retryable)}
    else:
        raise ValueError("unsupported status")
    return payload

def build_deletion_callback(callback_id, job, status, *, error=None, result=None) -> dict:
    payload = {"schemaVersion": "1.0", "callbackId": str(callback_id), "sourceSystem": "CSIT",
        "deletionRequestId": str(job["deletion_request_id"]), "kmDeletionJobId": job["km_deletion_job_id"],
        "resource": job["resource"], "status": status,
        "timestamps": {"startedAt": _ts(job["started_at"]) if status == "Processing" else None,
                       "completedAt": _ts(job["completed_at"]) if status == "Completed" else None,
                       "failedAt": _ts(job["failed_at"]) if status == "Failed" else None},
        "result": None, "error": None}
    if status == "Completed":
        cleanup = (result or {}).get("cleanup") or {}
        if set(cleanup) != set(CLEANUP_ITEMS) or any(v not in ("Deleted", "NotPresent") for v in cleanup.values()):
            raise ValueError("Completed needs all seven cleanup items Deleted or NotPresent")
        if result.get("cleanupVerified") is not True or not result.get("verifiedAt"):
            raise ValueError("Completed needs cleanupVerified=true and verifiedAt")
        payload["result"] = result
    elif status == "Failed":
        if error is None:
            raise ValueError("Failed needs an error")
        payload["error"] = {"code": error.code, "message": error.message, "retryable": bool(error.retryable)}
    elif status != "Processing":
        raise ValueError("unsupported status")
    return payload
