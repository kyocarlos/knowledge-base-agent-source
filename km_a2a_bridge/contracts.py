"""Stable, dependency-light A2A bridge contracts."""

from __future__ import annotations

from enum import Enum
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import BridgeConfig

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class TestJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_type: Literal["run_iperf_test"]
    environment: Literal["anritsu", "amarisoft"]
    profile_id: str
    run_id: str
    requested_by: str
    duration_seconds: int = Field(ge=1, le=3600)
    test_cases: list[str] = Field(min_length=1)

    @field_validator("profile_id", "run_id")
    @classmethod
    def _safe_identifier(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("must use a safe identifier")
        return value

    @field_validator("requested_by")
    @classmethod
    def _nonblank_requester(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("test_cases")
    @classmethod
    def _safe_cases(cls, values: list[str]) -> list[str]:
        if not values:
            raise ValueError("test_cases must not be empty")
        if any(not isinstance(v, str) or not _IDENTIFIER.fullmatch(v) for v in values):
            raise ValueError("test_cases must use safe identifiers")
        return values


class A2ATaskCorrelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    context_id: str | None = None
    a2a_task_id: str | None = None
    run_id: str
    ingest_task_id: str | None = None
    file_hash: str | None = None

    @field_validator("run_id", "context_id", "a2a_task_id", "ingest_task_id", "file_hash")
    @classmethod
    def _trim_nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("identifiers must not be blank")
        return value


class TestStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RunStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    test_status: TestStatus = TestStatus.PENDING
    report_status: ReportStatus = ReportStatus.PENDING
    ingest_status: IngestStatus = IngestStatus.PENDING


class A2ATaskState(str, Enum):
    SUBMITTED = "submitted"
    QUEUED = "queued"
    WORKING = "working"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELED = "canceled"


class TaskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_key: str
    job: TestJob
    state: A2ATaskState = A2ATaskState.SUBMITTED
    correlation: A2ATaskCorrelation
    status: RunStatus = Field(default_factory=RunStatus)
    rejection_reason: RejectionReason | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str


class RejectionReason(str, Enum):
    BUSY = "busy"
    POLICY_DENIED = "policy_denied"
    CAPACITY_EXCEEDED = "capacity_exceeded"
    PROFILE_NOT_ALLOWED = "profile_not_allowed"
    INVALID_REQUEST = "invalid_request"
    AGENT_OFFLINE = "agent_offline"


class BridgeDispatchError(ValueError):
    def __init__(self, reason: RejectionReason, message: str | None = None):
        self.reason = reason
        super().__init__(message or reason.value)


def validate_dispatch(config: BridgeConfig, job: TestJob) -> None:
    if not config.enabled:
        raise BridgeDispatchError(RejectionReason.POLICY_DENIED, "bridge is disabled")
    if job.environment not in config.agent_endpoints:
        raise BridgeDispatchError(RejectionReason.AGENT_OFFLINE, "agent endpoint is not configured")
    allowed = config.allowed_profiles.get(job.environment, frozenset())
    if job.profile_id not in allowed:
        raise BridgeDispatchError(RejectionReason.PROFILE_NOT_ALLOWED, "profile is not allowed")


# Short public name retained for callers that refer to the domain concept directly.
Correlation = A2ATaskCorrelation
