"""CSIT x AI KM spec v1.4: /v2/ wire contracts (document jobs, analysis results, metadata changes, deletions)."""
import copy
import re
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field, StrictInt, field_validator, model_validator
from .doclib_models import (Wire, Classification, DOCUMENT_TYPES, CLEANUP_ITEMS, RESULT_SCHEMA, _ts)
from .models import safe_filename

JOB_SOURCE_TYPES = ("VerificationApplicationAttachment", "VendorFile", "EquipmentAttachment", "TestReport", "DocumentLibraryFile")
ALL_SOURCE_TYPES = ("DocumentLibraryFile", "TestReport", "VerificationApplicationAttachment", "VendorFile", "EquipmentAttachment")
# Spec v1.4.1 C.4: the closed set. The last two are the existing v1 names, used here only for a new version that names `supersedes`.
EVENT_SOURCE = {"VerificationApplicationAttachmentArchived": "VerificationApplicationAttachment",
                "VendorFileArchived": "VendorFile",
                "EquipmentDocumentArchived": "EquipmentAttachment",
                "EquipmentAttachmentArchived": "EquipmentAttachment",
                "TestReportCommitted": "TestReport",
                "DocumentLibraryFileUploaded": "DocumentLibraryFile"}
REPLACEMENT_EVENTS = ("TestReportCommitted", "DocumentLibraryFileUploaded")
# Spec v1.4.1 C.4 / answer 9: closed and case sensitive. The v1 reason codes stay on the v1 route.
DELETION_REASONS = ("SourceDeleted", "VersionSuperseded", "AdministrativeCleanup")

def _tz(value):
    if value.tzinfo is None:
        raise ValueError("timestamp timezone required")
    return value

def _sha(value):
    value = value.lower()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("sha256 must be 64 hex characters")
    return value

# ---- CSIT -> KM: document-jobs (spec 4.2) ----
class V2Source(Wire):
    type: Literal["VerificationApplicationAttachment", "VendorFile", "EquipmentAttachment", "TestReport", "DocumentLibraryFile"]
    entityId: UUID
    moduleCode: Optional[str] = Field(default=None, max_length=128)
    applicationId: Optional[UUID] = None
    recordId: Optional[UUID] = None
    vendorId: Optional[UUID] = None
    equipmentId: Optional[UUID] = None

class V2Approval(Wire):
    mode: Literal["Approved", "ApprovalBypassed"]
    referenceId: str = Field(min_length=1, max_length=128)
    approvedAt: datetime
    _tz = field_validator("approvedAt")(_tz)

class V2Document(Wire):
    id: UUID
    version: StrictInt = Field(ge=1, le=2147483647)
    originalFileName: str = Field(min_length=1, max_length=255)
    contentType: str = Field(min_length=1, max_length=128)
    sizeBytes: StrictInt = Field(gt=0)
    sha256: str
    downloadUrl: Optional[str] = Field(default=None, max_length=2048)
    archivedAt: datetime
    approval: V2Approval
    _name = field_validator("originalFileName", mode="before")(safe_filename)
    _sha = field_validator("sha256")(_sha)
    _tz = field_validator("archivedAt")(_tz)

class V2Supersedes(Wire):
    oldDocumentId: UUID
    oldVersion: StrictInt = Field(ge=1, le=2147483647)
    oldSha256: str
    _sha = field_validator("oldSha256")(_sha)

class DocumentJobRequest(Wire):
    schemaVersion: Literal["2.0"]
    eventId: UUID
    csitJobId: UUID
    eventType: Literal["VerificationApplicationAttachmentArchived", "VendorFileArchived", "EquipmentDocumentArchived", "EquipmentAttachmentArchived",
                       "TestReportCommitted", "DocumentLibraryFileUploaded"]
    sourceSystem: Literal["CSIT"]
    source: V2Source
    document: V2Document
    classification: Classification = Classification()
    supersedes: Optional[V2Supersedes] = None
    occurredAt: datetime
    _tz = field_validator("occurredAt")(_tz)
    @model_validator(mode="after")
    def consistent(self):
        if EVENT_SOURCE[self.eventType] != self.source.type:
            raise ValueError("eventType does not match source.type")
        if self.source.type in ("VendorFile", "EquipmentAttachment", "DocumentLibraryFile") and self.source.entityId != self.document.id:
            raise ValueError(self.source.type + " uses the same id for source.entityId and document.id")
        # TestReport: sourceEntityId is ModuleCaseFile.Id and documentId is ModuleCaseFile.DocumentId, two different ids.
        if self.eventType in REPLACEMENT_EVENTS and self.supersedes is None:
            raise ValueError(self.eventType + " on the v2 route is only for a new version that names supersedes")
        if self.supersedes and (self.supersedes.oldDocumentId == self.document.id and self.supersedes.oldVersion == self.document.version):
            raise ValueError("supersedes must name an older version")
        return self

class DocumentJobAccepted(BaseModel):
    eventId: UUID
    csitJobId: UUID
    kmJobId: str
    status: Literal["Accepted"] = "Accepted"

# ---- CSIT -> KM: document-metadata-changes (spec 6.2) ----
class Attributes(Wire):
    tags: list[str] = Field(default_factory=list, max_length=200)
    keywords: list[str] = Field(default_factory=list, max_length=200)
    displayName: Optional[str] = Field(default=None, max_length=512)
    modelNumbers: list[str] = Field(default_factory=list, max_length=200)
    vendorReference: Optional[str] = Field(default=None, max_length=512)

class MetadataChangeRequest(Wire):
    schemaVersion: Literal["2.0"]
    changeId: UUID
    sourceSystem: Literal["CSIT"]
    sourceType: Literal["DocumentLibraryFile", "TestReport", "VerificationApplicationAttachment", "VendorFile", "EquipmentAttachment"]
    sourceEntityId: UUID
    documentId: UUID
    version: StrictInt = Field(ge=1, le=2147483647)
    sourceRevision: StrictInt = Field(ge=1, le=2147483647)
    occurredAt: datetime
    classification: Classification
    attributes: Attributes
    changedFields: list[str] = Field(default_factory=list, max_length=100)
    _tz = field_validator("occurredAt")(_tz)
    def key(self):
        return identity_key(self.sourceType, self.sourceEntityId, self.documentId, self.version)

class MetadataChangeAccepted(BaseModel):
    changeId: UUID
    kmChangeJobId: str
    status: Literal["Accepted"] = "Accepted"

# ---- CSIT -> KM: document-deletions (spec 7.2) ----
class V2Resource(Wire):
    sourceType: Literal["DocumentLibraryFile", "TestReport", "VerificationApplicationAttachment", "VendorFile", "EquipmentAttachment"]
    sourceEntityId: UUID
    documentId: UUID
    version: StrictInt = Field(ge=1, le=2147483647)
    sha256: str
    applicationId: Optional[UUID] = None
    recordId: Optional[UUID] = None
    vendorId: Optional[UUID] = None
    equipmentId: Optional[UUID] = None
    canonicalIngestionEventId: UUID
    scope: Literal["DocumentVersion"]
    _sha = field_validator("sha256")(_sha)
    def key(self):
        """The tombstone key. Equal to the v1 key for the same source, so a v1 and a v2 deletion protect the same thing."""
        if self.sourceType == "DocumentLibraryFile":
            return str(self.documentId)
        return f"{self.documentId}:{self.version}:{self.sourceEntityId}"
    def wire(self):
        return {k: (str(v) if isinstance(v, UUID) else v) for k, v in self.model_dump().items()}
    def exec_resource(self):
        """What the cleanup executor looks at; the callback echoes wire() unchanged."""
        r = self.wire()
        if self.sourceType == "DocumentLibraryFile":
            r["documentFileId"] = r["documentId"]
        return r

class V2DeletionRequest(Wire):
    schemaVersion: Literal["2.0"]
    sourceSystem: Literal["CSIT"]
    eventType: Literal["DocumentDeletionRequested"]
    deletionRequestId: UUID
    requestedAt: datetime
    reasonCode: Literal["SourceDeleted", "VersionSuperseded", "AdministrativeCleanup"]
    resource: V2Resource
    _tz = field_validator("requestedAt")(_tz)

class V2DeletionAccepted(BaseModel):
    deletionRequestId: UUID
    kmDeletionJobId: str
    status: Literal["Accepted"] = "Accepted"

def identity_key(source_type, source_entity_id, document_id, version):
    if source_type == "DocumentLibraryFile":
        return str(document_id)
    return f"{document_id}:{version}:{source_entity_id}"

# ---- Completed.result of spec 5.2 (v2) ----
def _result_schema_v2():
    s = copy.deepcopy(RESULT_SCHEMA)
    p = s["properties"]
    p["metadataSchemaVersion"] = {"const": "2.0"}
    p["extraction"]["properties"]["method"] = {"enum": ["Text", "OCR", "Mixed", "Visual", "None"]}
    p["sourceSpecific"] = {"type": "object"}
    s["required"] = list(p)
    return s

RESULT_SCHEMA_V2 = _result_schema_v2()
_RESULT_V2 = Draft202012Validator(RESULT_SCHEMA_V2)

def validate_result_v2(result: dict) -> None:
    errors = sorted(_RESULT_V2.iter_errors(result), key=lambda e: list(e.path))
    if errors:
        e = errors[0]
        raise ValueError("Completed.result invalid at " + ".".join(str(x) for x in e.path) + ": " + e.message[:120])

SOURCE_SPECIFIC_DEFAULTS = {
    "VerificationApplicationAttachment": {"applicationReference": None, "modelReferences": [], "extractedTables": [], "sheetNames": [], "evidenceLocations": []},
    "VendorFile": {"vendorReferences": [], "certifications": [], "productCatalogReferences": [], "extractedTables": []},
    "EquipmentAttachment": {"specifications": [], "capabilitySummary": None, "limitations": []},
    "TestReport": {"testCaseIds": [], "testItems": [], "measurements": [], "passFail": None, "environment": None, "equipmentReferences": [], "evidenceLocations": []},
    "DocumentLibraryFile": {},
}

def _timestamps(job, status):
    return {"startedAt": _ts(job["started_at"]),
            "completedAt": _ts(job["completed_at"]) if status == "Completed" else None,
            "failedAt": _ts(job["failed_at"]) if status == "Failed" else None}

def _error(error):
    return {"code": error.code, "message": error.message, "retryable": bool(error.retryable)}

# ---- KM -> CSIT callbacks (spec 5.1, 6.2, 7.2, 5.4) ----
def build_job_callback(callback_id, job, status, *, error=None, result=None) -> dict:
    payload = {"schemaVersion": "2.0", "callbackId": str(callback_id), "eventId": str(job["event_id"]),
        "csitJobId": str(job["csit_job_id"]), "kmJobId": job["km_job_id"], "sourceSystem": "CSIT",
        "sourceType": job["source_type"], "sourceEntityId": str(job["source_entity_id"]),
        "documentId": str(job["document_id"]), "version": job["version"], "sourceSha256": job["expected_sha256"],
        "status": status, "timestamps": _timestamps(job, status), "result": None, "error": None}
    if status == "Processing":
        if payload["timestamps"]["startedAt"] is None:
            raise ValueError("Processing needs startedAt")
    elif status == "Completed":
        if payload["timestamps"]["completedAt"] is None:
            raise ValueError("Completed needs completedAt")
        validate_result_v2(result)
        payload["result"] = result
    elif status == "Failed":
        if error is None or payload["timestamps"]["failedAt"] is None:
            raise ValueError("Failed needs failedAt and error")
        payload["error"] = _error(error)
    else:
        raise ValueError("unsupported status")
    return payload

def build_change_callback(callback_id, change, status, *, error=None, result=None) -> dict:
    payload = {"schemaVersion": "2.0", "callbackId": str(callback_id), "changeId": str(change["change_id"]),
        "kmChangeJobId": change["km_change_job_id"], "sourceSystem": "CSIT", "status": status,
        "appliedRevision": change["source_revision"] if status == "Completed" else None,
        "timestamps": _timestamps(change, status), "error": None}
    if status == "Failed":
        if error is None:
            raise ValueError("Failed needs an error")
        payload["error"] = _error(error)
    elif status not in ("Processing", "Completed"):
        raise ValueError("unsupported status")
    return payload

def build_deletion_callback_v2(callback_id, job, status, *, error=None, result=None) -> dict:
    payload = {"schemaVersion": "2.0", "callbackId": str(callback_id), "sourceSystem": "CSIT",
        "deletionRequestId": str(job["deletion_request_id"]), "kmDeletionJobId": job["km_deletion_job_id"],
        "resource": job["resource"], "status": status, "timestamps": _timestamps(job, status), "result": None, "error": None}
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
        payload["error"] = _error(error)
    elif status != "Processing":
        raise ValueError("unsupported status")
    return payload

def build_analysis_payload(callback_id, analysis_result_id, *, source_entity_id, document_id, version, csit_job_id, km_job_id,
                           source_sha256, result, analyzed_at) -> dict:
    validate_result_v2(result)
    return {"schemaVersion": "2.0", "analysisResultId": str(analysis_result_id), "callbackId": str(callback_id),
        "sourceSystem": "CSIT", "sourceType": "TestReport", "sourceEntityId": str(source_entity_id),
        "documentId": str(document_id), "version": version, "csitJobId": str(csit_job_id), "kmJobId": km_job_id,
        "sourceSha256": source_sha256, "metadataSchemaVersion": "2.0", "result": result,
        "analyzedAt": _ts(analyzed_at), "supersedesAnalysisResultId": None}
