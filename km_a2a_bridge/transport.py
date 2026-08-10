"""Transport boundary; mock implementation never touches a real instrument."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from pydantic import SecretStr

from .contracts import A2ATaskCorrelation, A2ATaskState, RejectionReason, RunStatus, TestJob


class TransportRejected(RuntimeError):
    def __init__(self, reason: RejectionReason, message: str | None = None):
        self.reason = reason
        super().__init__(message or reason.value)


@dataclass(frozen=True)
class TransportResult:
    state: A2ATaskState
    correlation: A2ATaskCorrelation
    status: RunStatus


class A2ATransport(Protocol):
    async def dispatch(self, endpoint: str, credential: SecretStr, job: TestJob) -> TransportResult: ...


class MockA2ATransport:
    """Protocol-shaped dry-run transport used before real Anritsu connectivity."""

    def __init__(self, rejection: RejectionReason | None = None):
        self.rejection = rejection
        self.calls = 0

    async def dispatch(self, endpoint: str, credential: SecretStr, job: TestJob) -> TransportResult:
        del endpoint, credential
        self.calls += 1
        if self.rejection is not None:
            raise TransportRejected(self.rejection)
        correlation = A2ATaskCorrelation(
            context_id=f"ctx-{uuid4().hex}",
            a2a_task_id=f"task-{uuid4().hex}",
            run_id=job.run_id,
        )
        return TransportResult(
            state=A2ATaskState.COMPLETED,
            correlation=correlation,
            status=RunStatus(),
        )
