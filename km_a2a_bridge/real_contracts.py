"""Independent real-run contracts.

These models are intentionally not imported by the existing dry-run service or
transport. Wiring them into a runtime requires a separate approval and Gate
implementation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REQUESTER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")
MAX_APPROVAL_TTL = timedelta(minutes=15)


class RealRunApproval(BaseModel):
    """A single-use approval bound to exactly one real-run request."""

    model_config = ConfigDict(extra="forbid")

    approval_id: str
    run_id: str
    operator_id: str
    issued_at: datetime
    expires_at: datetime
    single_use: Literal[True] = True

    @field_validator("approval_id", "run_id")
    @classmethod
    def _safe_identifier(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("must use a safe identifier")
        return value

    @field_validator("operator_id")
    @classmethod
    def _safe_operator(cls, value: str) -> str:
        if not _REQUESTER.fullmatch(value):
            raise ValueError("must use a safe operator identifier")
        return value

    @model_validator(mode="after")
    def _validate_window(self) -> "RealRunApproval":
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("approval timestamps must include a timezone")
        if self.expires_at <= self.issued_at:
            raise ValueError("approval must expire after it is issued")
        if self.expires_at - self.issued_at > MAX_APPROVAL_TTL:
            raise ValueError("approval lifetime exceeds the 15 minute policy")
        return self


class RealArtifactPolicy(BaseModel):
    """Constraints for the report artifact produced by a real run."""

    model_config = ConfigDict(extra="forbid")

    format: Literal["xlsx"] = "xlsx"
    sha256_algorithm: Literal["sha256"] = "sha256"
    max_size_bytes: int = Field(default=100 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    ingest_required: Literal[True] = True


class RealRunJob(BaseModel):
    """Request contract kept separate from the existing dry-run ``TestJob``."""

    model_config = ConfigDict(extra="forbid")

    job_schema_version: Literal["1.0"] = "1.0"
    dry_run: Literal[False] = False
    job_type: Literal["run_iperf_test"]
    environment: Literal["anritsu"]
    profile_id: str
    run_id: str
    requested_by: str
    duration_seconds: int = Field(ge=1, le=3600)
    test_cases: list[str] = Field(min_length=1, max_length=1)
    approval: RealRunApproval
    artifact_policy: RealArtifactPolicy = Field(default_factory=RealArtifactPolicy)

    @field_validator("profile_id", "run_id")
    @classmethod
    def _safe_identifier(cls, value: str) -> str:
        if not _IDENTIFIER.fullmatch(value):
            raise ValueError("must use a safe identifier")
        return value

    @field_validator("requested_by")
    @classmethod
    def _safe_requester(cls, value: str) -> str:
        if not _REQUESTER.fullmatch(value):
            raise ValueError("must use a safe requester identifier")
        return value

    @field_validator("test_cases")
    @classmethod
    def _safe_single_case(cls, values: list[str]) -> list[str]:
        if len(values) != 1 or not _IDENTIFIER.fullmatch(values[0]):
            raise ValueError("real-run requires exactly one safe test case")
        return values

    @model_validator(mode="after")
    def _bind_approval(self) -> "RealRunJob":
        if self.approval.run_id != self.run_id:
            raise ValueError("approval is bound to a different run_id")
        if self.approval.operator_id != self.requested_by:
            raise ValueError("approval operator does not match requested_by")
        return self


class RealRunState(str, Enum):
    SUBMITTED = "submitted"
    APPROVED = "approved"
    QUEUED = "queued"
    RUNNING = "running"
    COLLECTING = "collecting"
    INGESTING = "ingesting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class RealRunCorrelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    context_id: str
    a2a_task_id: str
    approval_id: str
    execution_owner: Literal["anritsu-openclaw"]
    audit_id: str
    instrument_lock_id: str | None = None
    artifact_sha256: str | None = None
    ingest_task_id: str | None = None

    @field_validator("run_id", "context_id", "a2a_task_id", "approval_id", "audit_id")
    @classmethod
    def _nonblank_identifier(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("correlation identifiers must not be blank")
        return value

    @field_validator("artifact_sha256")
    @classmethod
    def _valid_hash(cls, value: str | None) -> str | None:
        if value is not None and not _SHA256.fullmatch(value):
            raise ValueError("artifact_sha256 must be a SHA-256 hex digest")
        return value


class RealRunResponse(BaseModel):
    """Response contract; completion requires artifact and ingest correlation."""

    model_config = ConfigDict(extra="forbid")

    state: RealRunState
    correlation: RealRunCorrelation
    test_status: Literal["pending", "running", "completed", "failed", "canceled"]
    report_status: Literal["pending", "running", "completed", "failed", "canceled"]
    ingest_status: Literal["pending", "running", "completed", "failed", "canceled"]

    @model_validator(mode="after")
    def _completed_requires_artifact(self) -> "RealRunResponse":
        if self.state is RealRunState.COMPLETED:
            if self.test_status != "completed" or self.report_status != "completed" or self.ingest_status != "completed":
                raise ValueError("completed real-run requires completed test, report, and ingest")
            if not self.correlation.artifact_sha256 or not self.correlation.ingest_task_id:
                raise ValueError("completed real-run requires artifact hash and ingest task id")
        return self


def validate_real_run_approval(job: RealRunJob, now: datetime | None = None) -> None:
    """Validate that a bound approval is currently usable.

    Persistence, atomic single-use consumption, and authorization are runtime
    responsibilities and are intentionally outside this pure contract module.
    """

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("validation time must include a timezone")
    issued_at = job.approval.issued_at.astimezone(timezone.utc)
    expires_at = job.approval.expires_at.astimezone(timezone.utc)
    current = current.astimezone(timezone.utc)
    if current < issued_at:
        raise ValueError("approval is not active yet")
    if current >= expires_at:
        raise ValueError("approval has expired")
