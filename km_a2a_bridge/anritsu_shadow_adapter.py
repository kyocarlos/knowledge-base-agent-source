"""Local Anritsu OpenClaw adapter contract for shadow verification.

This module models the loopback sidecar-to-agent boundary only. The included
adapter is a deterministic shadow implementation and cannot access hardware,
start processes, or upload artifacts.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .real_contracts import RealRunCorrelation

_ALLOWED_PROFILE = "ncq2200b2v-throughput-v1"
_ALLOWED_CASES = frozenset({"sa_dl_tcp", "sa_ul_tcp"})
_COUNTER_NAMES = (
    "manual_test_state_mutation",
    "scpi_command",
    "excel_report",
    "instrument_lock",
    "km_ingest",
    "instrument_connection",
    "iperf_process",
)


class ShadowAdapterRequest(BaseModel):
    """Fixed loopback payload accepted by the Anritsu OpenClaw adapter."""

    model_config = ConfigDict(extra="forbid")

    adapter_schema_version: Literal["1.0"] = "1.0"
    dry_run: Literal[True] = True
    job_type: Literal["run_iperf_test"]
    environment: Literal["anritsu"]
    profile_id: Literal[_ALLOWED_PROFILE]
    run_id: str
    requested_by: str
    duration_seconds: int = Field(ge=1, le=3600)
    test_cases: list[str] = Field(min_length=1, max_length=2)
    context_id: str
    a2a_task_id: str

    @field_validator("run_id", "requested_by", "context_id", "a2a_task_id")
    @classmethod
    def _nonblank(cls, value: str) -> str:
        if not value.strip() or any(char in value for char in "\r\n"):
            raise ValueError("identifier must be nonblank and single-line")
        return value

    @field_validator("test_cases")
    @classmethod
    def _allowlisted_cases(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or not set(values) <= _ALLOWED_CASES:
            raise ValueError("test case is not allowed")
        return values


class ShadowSideEffectCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manual_test_state_mutation: Literal[0] = 0
    scpi_command: Literal[0] = 0
    excel_report: Literal[0] = 0
    instrument_lock: Literal[0] = 0
    km_ingest: Literal[0] = 0
    instrument_connection: Literal[0] = 0
    iperf_process: Literal[0] = 0


class ShadowAdapterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter_schema_version: Literal["1.0"] = "1.0"
    state: Literal["accepted", "canceled", "failed"]
    execution_owner: Literal["anritsu-openclaw"] = "anritsu-openclaw"
    correlation: RealRunCorrelation
    side_effect_counts: ShadowSideEffectCounts = Field(default_factory=ShadowSideEffectCounts)
    instrument_available: Literal[False] = False
    real_instrument_access: Literal[False] = False
    error_code: str | None = None

    @model_validator(mode="after")
    def _correlation_owner(self) -> "ShadowAdapterResponse":
        if self.correlation.execution_owner != self.execution_owner:
            raise ValueError("execution owner must match correlation")
        if self.state == "failed" and not self.error_code:
            raise ValueError("failed response requires error_code")
        return self


class MockAnritsuOpenClawAdapter:
    """Shadow adapter with explicit no-side-effect behavior."""

    def __init__(self):
        self.received: list[ShadowAdapterRequest] = []

    def execute(self, request: ShadowAdapterRequest) -> ShadowAdapterResponse:
        self.received.append(request)
        return ShadowAdapterResponse(
            state="accepted",
            correlation=RealRunCorrelation(
                run_id=request.run_id,
                context_id=request.context_id,
                a2a_task_id=request.a2a_task_id,
                approval_id=f"shadow-{request.run_id}",
                execution_owner="anritsu-openclaw",
                audit_id=f"shadow-audit-{request.run_id}",
            ),
        )

    def cancel(self, request: ShadowAdapterRequest) -> ShadowAdapterResponse:
        return ShadowAdapterResponse(
            state="canceled",
            correlation=RealRunCorrelation(
                run_id=request.run_id,
                context_id=request.context_id,
                a2a_task_id=request.a2a_task_id,
                approval_id=f"shadow-{request.run_id}",
                execution_owner="anritsu-openclaw",
                audit_id=f"shadow-audit-{request.run_id}",
            ),
        )
