"""KM <-> CSIT wire contract for equipment-level cross-document synthesis.

Kept field-for-field compatible with CSIT's own contract (pattymou/CSIT-System, Services/KmIntegration/EquipmentAggregateAnalysisContracts.cs,
pinned at commit d4d11f05486efe2be2ca74f8ab4f3808060500a1): the inbound request matches EquipmentAggregateAnalysisRequestContract, and the
result/callback KM sends back match EquipmentAggregateAnalysisResult / EquipmentAggregateAnalysisCallback exactly, including their
[JsonUnmappedMemberHandling.Disallow] attribute -- CSIT's own deserializer rejects a callback carrying one extra key, so build_*_payload()
below never adds a field beyond what those two C# records declare. CSIT's contract is the highest authority; nothing here invents a shape.
"""
import re
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from .models import safe_filename

class Wire(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

def _sha(value):
    value = value.lower()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("sha256 must be 64 hex characters")
    return value

def _tz(value):
    if value.tzinfo is None:
        raise ValueError("timestamp timezone required")
    return value

# ---- CSIT -> KM: the request (EquipmentAggregateAnalysisRequestContract) ----

class SourceDocument(Wire):
    fileId: UUID
    version: StrictInt = Field(ge=1, le=2147483647)
    sha256: str
    kmJobId: str = Field(min_length=1, max_length=128)
    analysisResultId: UUID          # CSIT's own id for that single-document result; echoed in evidence, never minted or replaced here
    fileName: Optional[str] = Field(default=None, max_length=255)
    analyzedAt: datetime
    _name = field_validator("fileName", mode="before")(lambda v: safe_filename(v) if v else v)
    _sha = field_validator("sha256")(_sha)
    _tz = field_validator("analyzedAt")(_tz)

class EquipmentAggregateRequest(Wire):
    schemaVersion: Literal["1.0"]
    requestId: UUID
    sourceSystem: Literal["CSIT"]
    moduleCode: str = Field(min_length=1, max_length=128)
    apparatusId: str = Field(min_length=1, max_length=128)
    manifestHash: str
    analysisVersion: str = Field(min_length=1, max_length=32)  # a CSIT config value (not a revision counter); echoed back as-is
    documents: list[SourceDocument] = Field(default_factory=list, max_length=500)
    requestedAt: datetime
    _hash = field_validator("manifestHash")(_sha)
    _tz = field_validator("requestedAt")(_tz)
    @model_validator(mode="after")
    def _one_version_per_file(self):
        seen = set()
        for d in self.documents:
            if d.fileId in seen:
                raise ValueError("a request lists one version per fileId")
            seen.add(d.fileId)
        return self

class EquipmentAggregateAccepted(BaseModel):
    requestId: UUID
    kmJobId: str
    status: Literal["Accepted"] = "Accepted"

# ---- KM -> CSIT: the result and the callback (EquipmentAggregateAnalysisResult / ...Callback) ----

def build_equipment_aggregate_result(*, overview, technical_specifications, test_capabilities, limitations, conflicts, evidence, warnings):
    """One EquipmentAggregateAnalysisResult, with exactly the 7 keys CSIT's record declares (JsonUnmappedMemberHandling.Disallow: an
    extra key here makes CSIT refuse the whole callback)."""
    return {
        "overview": overview,
        "technicalSpecifications": [{"name": s["name"], "value": s["value"], "unit": s.get("unit"), "evidenceIds": s["evidenceIds"]}
                                     for s in technical_specifications],
        "testCapabilities": [{"name": c["name"], "description": c.get("description"), "evidenceIds": c["evidenceIds"]}
                              for c in test_capabilities],
        "limitations": list(limitations),
        "conflicts": [{"field": c["field"], "description": c["description"], "evidenceIds": c["evidenceIds"]} for c in conflicts],
        "evidence": [{"evidenceId": e["evidenceId"], "fileId": str(e["fileId"]), "analysisResultId": str(e["analysisResultId"]),
                      "description": e["description"], "location": e.get("location")} for e in evidence],
        "warnings": list(warnings),
    }

def build_equipment_aggregate_callback(callback_id, row, status, *, error=None, result=None, analyzed_at=None):
    """row is a km_csit_equipment_aggregate_requests row. Exactly the 10 keys of EquipmentAggregateAnalysisCallback; CallbackId is the
    Idempotency-Key CSIT's controller checks against (KmAnalysisCallbackController.EquipmentAggregateStatus)."""
    payload = {"schemaVersion": "1.0", "callbackId": str(callback_id), "requestId": str(row["request_id"]), "moduleCode": row["module_code"],
               "apparatusId": row["apparatus_id"], "manifestHash": row["manifest_hash"], "analysisVersion": row["analysis_version"],
               "status": status, "result": None, "error": None, "analyzedAt": None}
    if status == "Completed":
        if result is None or analyzed_at is None:
            raise ValueError("Completed needs result and analyzedAt")
        payload["result"] = result
        payload["analyzedAt"] = analyzed_at.isoformat().replace("+00:00", "Z")
    elif status == "Failed":
        if error is None:
            raise ValueError("Failed needs an error")
        payload["error"] = {"code": error.code, "message": error.message, "retryable": bool(error.retryable)}
    else:
        raise ValueError("unsupported status")
    return payload
