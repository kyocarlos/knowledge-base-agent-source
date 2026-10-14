from datetime import datetime
from typing import Literal
import re
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class Reference(ContractModel):
    id: str = Field(min_length=1, max_length=256)
    number: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=1024)

def safe_filename(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("filename must be a string")
    if value in {".", ".."} or any(c in value for c in "/\\:") or any(ord(c)<32 for c in value):
        raise ValueError("unsafe filename")
    if value.rstrip(". ") != value or "\x00" in value:
        raise ValueError("unsafe filename")
    return value

class Document(ContractModel):
    fileName: str = Field(min_length=1, max_length=255)
    contentType: str = Field(min_length=1, max_length=128)
    sizeBytes: StrictInt = Field(ge=0)
    _filename = field_validator("fileName",mode="before")(safe_filename)
    @field_validator("contentType")
    @classmethod
    def mime(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", value):
            raise ValueError("invalid MIME type")
        return value.lower()

class IngestionRequest(ContractModel):
    eventId: str = Field(min_length=1, max_length=256)
    eventType: Literal["TestReportCommitted"]
    sourceSystem: Literal["CSIT"]
    documentId: str = Field(min_length=1, max_length=256)
    version: StrictInt = Field(gt=0, le=2147483647)
    project: Reference
    case: Reference
    task: Reference
    document: Document
    committedAt: datetime
    @field_validator("committedAt")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("timestamp timezone required")
        return value

class JobResponse(ContractModel):
    jobId: str
    sourceSystem: Literal["CSIT"]
    documentId: str
    version: int
    status: Literal["Accepted", "Processing", "Completed", "Failed"]
